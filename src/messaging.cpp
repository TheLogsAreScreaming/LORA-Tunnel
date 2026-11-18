#include "messaging.h"
#include "meshtastic_message.h"
#include "meshcore_message.h"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <new>

namespace tunnel { namespace messaging {
namespace {
namespace mt=meshtastic;
namespace mc=meshcore_message;
constexpr std::uint32_t IdentityMagic=0x4c544d31,ContactsMagic=0x4c544331;
constexpr std::uint32_t IdBlock=256,ReceiptWait=120000,UserInterval=5000;
constexpr std::uint8_t MeshCoreGroupReplay=0x80|std::uint8_t(mesh::Protocol::MeshCore);
struct IdentityStore {
  std::uint32_t magic=IdentityMagic,node=0,next_id=0,last_time=0;
  std::uint8_t mt_secret[32]{},mc_seed[32]{};
  std::uint32_t checksum=0;
};
struct Replay {std::uint32_t peer=0,id=0;std::uint8_t protocol=0;};
struct ContactStore {
  std::uint32_t magic=ContactsMagic;
  Contact contacts[ContactCount]{};
  std::uint32_t last_time[ContactCount]{};
  Replay private_replay[16]{};
  std::uint8_t count=0,replay_next=0;
  std::uint32_t checksum=0;
};
struct Pending {
  bool used=false,direct=false,ready=false,inflight=false;
  std::uint8_t attempts=0;
  std::uint32_t id=0,timestamp=0,deadline=0;
  Contact contact{};
  char text[TextBytes+1]{};
  mt::Frame frame{};
  std::uint8_t ack[3][4]{};
};
struct State {
  Storage storage{};
  Settings settings{};
  mesh::Protocol protocol=mesh::Protocol::Unknown;
  bool tx=false,identity_ready=false,ack_inflight=false;
  IdentityStore identity{};
  ContactStore peers{};
  mt::Identity mt_identity{};
  mc::Identity mc_identity{};
  mt::Channel channel{};
  char channel_name[40]{},default_channel[40]{},status[64]{};
  Record history[HistoryCount]{};
  std::uint8_t history_count=0;
  Replay replay[16]{};std::uint8_t replay_next=0;
  std::uint32_t next_id=0,id_limit=0,last_user_send=0,ack_ready_at=0;
  bool user_sent=false;
  Pending pending{};
  mt::Frame response{};
};
State* state=nullptr;
Diagnostics metrics{};
char inactiveStatus[64]{};
void copy(char* target,std::size_t capacity,const char* source) {
  if(!capacity)return;
  std::snprintf(target,capacity,"%s",source?source:"");
}
void wipe(void* data,std::size_t size){volatile auto* p=static_cast<volatile std::uint8_t*>(data);while(size--)*p++=0;}
std::uint32_t hash(const void* data,std::size_t size) {
  auto* p=static_cast<const std::uint8_t*>(data);std::uint32_t h=2166136261U;
  while(size--){h^=*p++;h*=16777619U;}return h;
}
template<class T> std::uint32_t checksum(T& value) {
  const auto saved=value.checksum;value.checksum=0;
  const auto result=hash(&value,sizeof(value));value.checksum=saved;return result;
}
void status(const char* text){copy(state?state->status:inactiveStatus,64,text);}
bool saveIdentity() {
  auto& s=*state;s.identity.checksum=checksum(s.identity);
  if(s.storage.save("identity-v1",&s.identity,sizeof(s.identity)))return true;
  s.tx=false;s.identity_ready=false;status("Identity save failed; TX disabled");return false;
}
bool saveContacts() {
  auto& s=*state;s.peers.checksum=checksum(s.peers);
  if(s.storage.save("contacts-v1",&s.peers,sizeof(s.peers)))return true;
  s.tx=false;s.identity_ready=false;status("Contact save failed; TX disabled");return false;
}
bool reserveIds() {
  auto& s=*state;
  if(!s.identity.next_id||s.identity.next_id>UINT32_MAX-IdBlock){status("Packet counter exhausted; TX disabled");s.tx=false;s.identity_ready=false;return false;}
  const auto next=s.identity.next_id;s.identity.next_id+=IdBlock;
  if(!saveIdentity())return false;
  s.next_id=next;s.id_limit=s.identity.next_id;return true;
}
std::uint32_t packetId() {
  if(state->next_id==state->id_limit&&!reserveIds())return 0;
  return state->next_id++;
}
std::uint32_t timestamp(std::uint32_t unixTime) {
  auto& s=*state;
  if(!unixTime||unixTime<1704067200U){status("MeshCore needs a fresh GPS UTC time");return 0;}
  if(s.identity.last_time==UINT32_MAX){status("Timestamp exhausted; TX disabled");s.tx=false;return 0;}
  const auto chosen=std::max(unixTime,s.identity.last_time+1);
  // Reject a corrupt/far future clock instead of permanently advancing IDs.
  if(chosen-unixTime>3600){status("Clock behind identity; wait for valid UTC");return 0;}
  s.identity.last_time=chosen;return saveIdentity()?chosen:0;
}
mt::Contact mtContact(const Contact& value) {
  mt::Contact out;out.node=value.node;out.has_public_key=true;
  std::memcpy(out.public_key,value.public_key,32);return out;
}
mc::Contact mcContact(const Contact& value) {
  mc::Contact out;std::memcpy(out.public_key,value.public_key,32);copy(out.name,sizeof(out.name),value.name);return out;
}
mt::Tx tx(bool ack=false) {
  mt::Tx out;out.packet_id=packetId();out.hop_limit=state->settings.hop_limit;out.want_ack=ack;out.extra_nonce=state->storage.random();return out;
}
const std::uint8_t* mcKey() {return state->settings.meshcore_key_length?state->settings.meshcore_key:mc::publicGroupKey();}
std::size_t mcKeyLength(){return state->settings.meshcore_key_length?state->settings.meshcore_key_length:16;}
template<class T> void frameCopy(mt::Frame& out,const T& input) {out.length=input.length;std::memcpy(out.bytes,input.bytes,input.length);}
void setChannel(const char* defaultChannel) {
  auto& s=*state;copy(s.default_channel,sizeof(s.default_channel),defaultChannel);
  copy(s.channel_name,sizeof(s.channel_name),s.settings.meshtastic_channel[0]?s.settings.meshtastic_channel:s.default_channel);
  s.channel=mt::Channel{};
  const std::uint8_t publicKey[16]={0xd4,0xf1,0xbb,0x3a,0x20,0x29,0x07,0x59,0xf0,0xbc,0xff,0xab,0xcf,0x4e,0x69,0x01};
  s.channel.key_length=s.settings.meshtastic_key_length?s.settings.meshtastic_key_length:16;
  std::memcpy(s.channel.key,s.settings.meshtastic_key_length?s.settings.meshtastic_key:publicKey,s.channel.key_length);
  for(unsigned i=0;s.channel_name[i];++i)s.channel.hash^=std::uint8_t(s.channel_name[i]);
  for(unsigned i=0;i<s.channel.key_length;++i)s.channel.hash^=s.channel.key[i];
  copy(s.mt_identity.name,sizeof(s.mt_identity.name),s.settings.name);
  copy(s.mt_identity.short_name,sizeof(s.mt_identity.short_name),"LORA");
}
Record& addRecord(const Record& value) {
  auto& s=*state;
  for(std::size_t i=HistoryCount-1;i>0;--i)s.history[i]=s.history[i-1];
  s.history[0]=value;if(s.history_count<HistoryCount)++s.history_count;return s.history[0];
}
void delivery(std::uint32_t id,Delivery result) {
  for(auto& record:state->history)if(record.outgoing&&record.id==id&&record.protocol==state->protocol){record.delivery=result;break;}
}
bool duplicate(Replay* entries,std::uint32_t peer,std::uint32_t id,std::uint8_t domain) {
  for(unsigned i=0;i<16;++i)if(entries[i].peer==peer&&entries[i].id==id&&entries[i].protocol==domain)return true;
  return false;
}
bool remember(std::uint32_t peer,std::uint32_t id,bool direct) {
  auto& s=*state;
  const auto domain=std::uint8_t(s.protocol);
  if(duplicate(s.replay,peer,id,domain)||(direct&&duplicate(s.peers.private_replay,peer,id,domain)))return false;
  s.replay[s.replay_next++%16]={peer,id,std::uint8_t(s.protocol)};
  if(direct){s.peers.private_replay[s.peers.replay_next++%16]={peer,id,std::uint8_t(s.protocol)};if(!saveContacts())return false;}
  return true;
}
bool rememberGroup(const std::uint8_t fingerprint[8]) {
  // Group names/timestamps are not sender identities. Reuse the bounded RAM
  // ring for canonical packet digests under a domain distinct from private RX.
  std::uint32_t first=0,second=0;
  for(unsigned i=0;i<4;++i){first|=std::uint32_t(fingerprint[i])<<(8*i);second|=std::uint32_t(fingerprint[i+4])<<(8*i);}
  auto& s=*state;
  if(duplicate(s.replay,first,second,MeshCoreGroupReplay))return false;
  s.replay[s.replay_next++%16]={first,second,MeshCoreGroupReplay};return true;
}
int findContact(mesh::Protocol protocol,std::uint32_t node,const std::uint8_t* key=nullptr) {
  for(unsigned i=0;i<state->peers.count;++i){const auto& p=state->peers.contacts[i];
    if(p.protocol==protocol&&(protocol==mesh::Protocol::Meshtastic?p.node==node:key&&!std::memcmp(p.public_key,key,32)))return int(i);}
  return -1;
}
void discover(mesh::Protocol protocol,std::uint32_t node,const std::uint8_t key[32],const char* name) {
  auto& s=*state;
  int index=findContact(protocol,node,key);
  if(index<0){if(s.peers.count==ContactCount){status("Contacts full; forget one to discover more");return;}index=s.peers.count++;}
  auto& peer=s.peers.contacts[index];
  const bool changed=peer.trusted&&std::memcmp(peer.public_key,key,32);
  if(changed){peer.trusted=false;peer.key_changed=true;status("Contact key changed; verify before messaging");}
  peer.protocol=protocol;peer.node=node;std::memcpy(peer.public_key,key,32);copy(peer.name,sizeof(peer.name),name);
  if(changed)saveContacts();
}
bool makePendingFrame() {
  auto& s=*state;auto& p=s.pending;bool ok=false;
  if(s.protocol==mesh::Protocol::Meshtastic) {
    // Retransmit identical ciphertext and packet ID. Extra nonce is not reused
    // with different plaintext; receivers can recognize and ACK duplicates.
    if(p.attempts){p.ready=true;return true;}
    auto options=tx(p.direct);p.id=options.packet_id;
    if(!options.packet_id)return false;
    ok=p.direct?mt::encodePrivateText(s.mt_identity,mtContact(p.contact),options,p.text,p.frame,mt::platformCrypto()):
      mt::encodeChannelText(s.channel,s.mt_identity,options,p.text,p.frame,mt::platformCrypto());
  }else{
    mc::Frame frame;
    ok=p.direct?mc::directText(s.mc_identity,mcContact(p.contact),p.text,p.timestamp,p.attempts,mc::platformCrypto(),frame,p.ack[p.attempts]):
      mc::groupText(mcKey(),mcKeyLength(),s.settings.name,p.text,p.timestamp,0,mc::platformCrypto(),frame);
    if(ok)frameCopy(p.frame,frame);
  }
  p.ready=ok;return ok;
}
void clearPending(Delivery result){delivery(state->pending.id,result);wipe(&state->pending,sizeof(Pending));new(&state->pending)Pending{};}
bool canQueue(std::uint32_t now) {
  if(!state||!state->tx||!state->identity_ready){status("Enable TX to send messages");return false;}
  if(state->pending.used||state->ack_inflight){status("Wait for pending message or stop Messages");return false;}
  if(state->user_sent&&std::uint32_t(now-state->last_user_send)<UserInterval){status("Wait five seconds between messages");return false;}
  return true;
}
void queueReceipt(const mt::Parsed& received,const Contact& peer,std::uint32_t now) {
  auto& s=*state;if(!s.tx||s.response.length||s.ack_inflight||!received.header.want_ack)return;
  auto options=tx();if(!options.packet_id)return;const auto contact=mtContact(peer);
  if(mt::encodeReceipt(s.channel,s.mt_identity,peer.node,options,received.header.id,0,s.response,mt::platformCrypto(),&contact))
    s.ack_ready_at=now+250+s.storage.random()%500;
}
}

std::size_t workspaceBytes(){return sizeof(State);}
Diagnostics diagnostics(){return metrics;}
bool active(){return state!=nullptr;}
bool busy(){return state&&(state->pending.used||state->response.length||state->ack_inflight);}
bool transmitAllowed(){return state&&state->tx&&state->identity_ready;}
bool begin(mesh::Protocol protocol,const Settings& settings,const char* defaultChannel,const Storage& storage) {
  if(state||!validSettings(settings)||!printable(defaultChannel,39)||!storage.load||!storage.save||!storage.random||!storage.allocate||!storage.release||
      (protocol!=mesh::Protocol::Meshtastic&&protocol!=mesh::Protocol::MeshCore))return false;
  void* memory=storage.allocate(sizeof(State));if(!memory){status("Messaging memory unavailable");return false;}
  std::memset(memory,0,sizeof(State));state=new(memory)State{};++metrics.starts;auto& s=*state;s.storage=storage;s.protocol=protocol;s.settings=settings;
  auto loaded=storage.load("identity-v1",&s.identity,sizeof(s.identity));
  if(loaded==Load::Missing){
    s.identity=IdentityStore{};
    do{s.identity.node=storage.random();}while(!s.identity.node||s.identity.node==UINT32_MAX);
    s.identity.next_id=(storage.random()&0x7fffffffU)+1;
    for(unsigned i=0;i<32;i+=4){const auto a=storage.random(),b=storage.random();std::memcpy(s.identity.mt_secret+i,&a,4);std::memcpy(s.identity.mc_seed+i,&b,4);}
    if(!saveIdentity())return true;
  }else if(loaded!=Load::Ok||s.identity.magic!=IdentityMagic||s.identity.checksum!=checksum(s.identity)||!s.identity.node||s.identity.node==UINT32_MAX||!s.identity.next_id){
    status("Identity storage invalid; TX disabled");return true;
  }
  s.mt_identity.node=s.identity.node;std::memcpy(s.mt_identity.private_key,s.identity.mt_secret,32);
  const auto& crypto=mt::platformCrypto();
  if(!crypto.derivePublic||!crypto.derivePublic(s.identity.mt_secret,s.mt_identity.public_key)||!mc::identity(s.identity.mc_seed,mc::platformCrypto(),s.mc_identity)){
    status("Identity crypto failed; TX disabled");return true;
  }
  setChannel(defaultChannel);
  const auto contacts=storage.load("contacts-v1",&s.peers,sizeof(s.peers));
  if(contacts==Load::Missing){wipe(&s.peers,sizeof(s.peers));new(&s.peers)ContactStore{};}
  else if(contacts!=Load::Ok||s.peers.magic!=ContactsMagic||s.peers.count>ContactCount||s.peers.checksum!=checksum(s.peers)){
    wipe(&s.peers,sizeof(s.peers));new(&s.peers)ContactStore{};status("Contact storage invalid; TX disabled");return true;
  }
  for(unsigned i=0;i<s.peers.count;++i){auto& p=s.peers.contacts[i];
    if((p.protocol!=mesh::Protocol::Meshtastic&&p.protocol!=mesh::Protocol::MeshCore)||!std::memchr(p.name,0,sizeof(p.name))){wipe(&s.peers,sizeof(s.peers));new(&s.peers)ContactStore{};status("Contact storage invalid; TX disabled");return true;}}
  if(!reserveIds())return true;
  s.identity_ready=true;status("Listening; TX is off");return true;
}
void end() {
  if(!state)return;
  ++metrics.stops;
  const auto storage=state->storage;state->~State();wipe(state,sizeof(State));storage.release(state);state=nullptr;
  copy(inactiveStatus,sizeof(inactiveStatus),"Messages stopped; inbox cleared");
}
void view(View& out) {
  out=View{};
  if(!state){copy(out.status,sizeof(out.status),inactiveStatus);return;}
  const auto& s=*state;out.active=true;out.tx_enabled=s.tx;out.identity_ready=s.identity_ready;out.protocol=s.protocol;
  copy(out.status,sizeof(out.status),s.status);copy(out.name,sizeof(out.name),s.settings.name);
  copy(out.channel,sizeof(out.channel),s.protocol==mesh::Protocol::Meshtastic?s.channel_name:s.settings.meshcore_key_length?"Configured channel":"Public");
  const auto* key=s.protocol==mesh::Protocol::Meshtastic?s.mt_identity.public_key:s.mc_identity.public_key;
  for(unsigned i=0;i<32;++i)std::snprintf(out.identity+2*i,3,"%02x",key[i]);
  out.history=s.history;out.history_count=s.history_count;out.contacts=s.peers.contacts;out.contact_count=s.peers.count;
}
bool setTransmit(bool enabled) {
  if(enabled)++metrics.tx_enable_requests;else ++metrics.tx_disable_requests;
  if(!state)return false;
  if(enabled&&!state->identity_ready){status("Identity unavailable; TX disabled");return false;}
  state->tx=enabled;
  if(enabled)++metrics.tx_enabled;
  if(!enabled){if(state->pending.used)clearPending(Delivery::Cancelled);state->response=mt::Frame{};state->ack_inflight=false;}
  status(enabled?"TX enabled; send or announce explicitly":"Listening; TX is off");return true;
}
bool updateSettings(const Settings& settings,const char* defaultChannel) {
  if(!validSettings(settings)||!printable(defaultChannel,39))return false;
  if(!state)return true;
  if(busy()){status("Finish pending message before changing keys");return false;}
  state->settings=settings;setChannel(defaultChannel);status("Messaging settings saved");return true;
}
bool trustContact(unsigned index,const std::uint8_t key[32]) {
  if(!state||index>=state->peers.count||!key||std::memcmp(state->peers.contacts[index].public_key,key,32)||busy())return false;
  auto& peer=state->peers.contacts[index];const auto old=peer;peer.trusted=true;peer.key_changed=false;
  if(!saveContacts()){peer=old;return false;}
  status("Contact key trusted and saved");return true;
}
bool forgetContact(unsigned index,const std::uint8_t key[32]) {
  if(!state||index>=state->peers.count||!key||std::memcmp(state->peers.contacts[index].public_key,key,32)||busy())return false;
  // Preserve stable indices for queued UI actions; compact only this explicit
  // operation, which is bound to the fingerprint the user actually reviewed.
  auto& p=state->peers;
  for(unsigned i=index;i+1<p.count;++i){p.contacts[i]=p.contacts[i+1];p.last_time[i]=p.last_time[i+1];}
  --p.count;p.contacts[p.count]=Contact{};p.last_time[p.count]=0;
  if(!saveContacts())return false;
  status("Contact forgotten");return true;
}
bool send(int contact,const std::uint8_t expectedKey[32],const char* text,std::uint32_t now,std::uint32_t unixTime) {
  ++metrics.send_requests;
  if(!canQueue(now))return false;
  if(!printable(text,TextBytes)){status("Message must contain 1-120 printable characters");return false;}
  auto& s=*state;auto& p=s.pending;
  if(contact>=0){
    if(unsigned(contact)>=s.peers.count||!expectedKey){status("Select a contact first");return false;}
    const auto& peer=s.peers.contacts[contact];
    if(peer.protocol!=s.protocol||!peer.trusted||peer.key_changed||std::memcmp(expectedKey,peer.public_key,32)){status("Verify and trust this contact first");return false;}
    p.contact=peer;p.direct=true;
  }else if(contact!=-1)return false;
  copy(p.text,sizeof(p.text),text);
  if(s.protocol==mesh::Protocol::MeshCore){p.timestamp=timestamp(unixTime);p.id=p.timestamp;if(!p.timestamp){p=Pending{};return false;}}
  if(!makePendingFrame()){p=Pending{};status("Message encode failed");return false;}
  p.used=true;s.last_user_send=now;s.user_sent=true;
  Record record;record.protocol=s.protocol;record.outgoing=true;record.direct=p.direct;record.id=p.id;record.peer=p.contact.node;record.delivery=Delivery::Queued;
  copy(record.name,sizeof(record.name),p.direct?p.contact.name:s.settings.name);copy(record.text,sizeof(record.text),text);addRecord(record);
  ++metrics.send_queued;status("Message queued");return true;
}
bool announce(std::uint32_t now,std::uint32_t unixTime) {
  ++metrics.announce_requests;
  if(!canQueue(now))return false;
  auto& s=*state;auto& p=s.pending;bool ok=false;
  if(s.protocol==mesh::Protocol::Meshtastic){auto options=tx();p.id=options.packet_id;ok=options.packet_id&&mt::encodeNodeInfo(s.channel,s.mt_identity,options,p.frame,mt::platformCrypto(),true);}
  else {mc::Frame frame;const auto time=timestamp(unixTime);p.id=time;ok=time&&mc::advert(s.mc_identity,s.settings.name,time,mc::platformCrypto(),frame);if(ok)frameCopy(p.frame,frame);}
  if(!ok){p=Pending{};status("Identity announcement unavailable");return false;}
  p.used=p.ready=true;s.last_user_send=now;s.user_sent=true;++metrics.announce_queued;status("Identity announcement queued");return true;
}
bool nextFrame(std::uint32_t now,const std::uint8_t*& bytes,std::size_t& length) {
  bytes=nullptr;length=0;if(!state||!state->tx||!state->identity_ready)return false;
  auto& s=*state;
  if(s.ack_inflight||s.pending.inflight)return false;
  if(s.response.length&&std::int32_t(now-s.ack_ready_at)>=0){s.ack_inflight=true;bytes=s.response.bytes;length=s.response.length;return true;}
  if(!s.pending.used||!s.pending.ready)return false;
  s.pending.inflight=true;s.pending.ready=false;bytes=s.pending.frame.bytes;length=s.pending.frame.length;
  delivery(s.pending.id,Delivery::Transmitting);return true;
}
void transmitted(bool success,std::uint32_t now) {
  if(!state)return;auto& s=*state;
  if(s.ack_inflight){if(success)++metrics.tx_ok;else ++metrics.tx_fail;s.ack_inflight=false;s.response=mt::Frame{};if(!success)status("Reply transmission failed");return;}
  auto& p=s.pending;if(!p.used||!p.inflight)return;p.inflight=false;++p.attempts;
  if(success)++metrics.tx_ok;else ++metrics.tx_fail;
  if(!success){clearPending(Delivery::Failed);status("Transmit failed; reception restored");return;}
  if(!p.direct){
    if(s.protocol==mesh::Protocol::MeshCore){
      mc::Message group;
      // Announcements also use this branch; only a validated group frame can
      // seed echo suppression, and only after a successful local transmission.
      if(mc::parseGroup(p.frame.bytes,p.frame.length,mcKey(),mcKeyLength(),mc::platformCrypto(),group))rememberGroup(group.group_fingerprint);
    }
    clearPending(Delivery::Sent);status("Sent; delivery unconfirmed");return;
  }
  p.deadline=now+ReceiptWait;delivery(p.id,Delivery::AwaitingAck);status("Sent; waiting for recipient receipt");
}
void tick(std::uint32_t now) {
  if(!state)return;auto& p=state->pending;
  if(!p.used||!p.direct||p.inflight||p.ready||!p.attempts||std::int32_t(now-p.deadline)<0)return;
  if(p.attempts>=3){clearPending(Delivery::Failed);status("No receipt after three attempts");return;}
  if(!state->tx||!makePendingFrame()){clearPending(Delivery::Failed);status("Retry unavailable");return;}
  delivery(p.id,Delivery::Queued);status("Retry queued");
}
void radioFailure(const char* value) {if(state){++metrics.radio_failures;state->tx=false;if(state->pending.used)clearPending(Delivery::Failed);state->response=mt::Frame{};state->ack_inflight=false;}status(value);}

void receive(const std::uint8_t* frame,std::size_t length,std::uint32_t now,std::uint32_t unixTime) {
  if(!state||!frame||!length||length>255||!state->identity_ready)return;
  ++metrics.rx_frames;
  auto& s=*state;
  if(s.protocol==mesh::Protocol::Meshtastic){
    mt::Header header;if(!mt::peekHeader(frame,length,header)||header.from==s.identity.node)return;
    const int index=findContact(s.protocol,header.from);
    const Contact* peer=index>=0?&s.peers.contacts[index]:nullptr;
    const bool trusted=peer&&peer->trusted&&!peer->key_changed;
    const auto contact=peer?mtContact(*peer):mt::Contact{};
    mt::Parsed parsed;
    // PKI channel-zero packets addressed to this node get only the private
    // decoder. Failed CCM never falls through to an unauthenticated text path.
    const bool privateCandidate=header.to==s.identity.node&&header.channel==0;
    bool ok=privateCandidate?trusted&&mt::decodePrivate(frame,length,s.mt_identity,contact,parsed,mt::platformCrypto()):
      mt::decodeChannel(frame,length,s.channel,parsed,mt::platformCrypto(),&s.mt_identity,trusted?&contact:nullptr);
    if(!ok&&privateCandidate&&s.channel.hash==0){
      mt::Parsed control;
      if(mt::decodeChannel(frame,length,s.channel,control,mt::platformCrypto(),&s.mt_identity,trusted?&contact:nullptr)&&
          (control.kind==mt::Kind::NodeInfo||(control.kind==mt::Kind::Receipt&&control.authenticated))){parsed=control;ok=true;}
    }
    if(!ok)return;
    if(parsed.kind==mt::Kind::Receipt){
      auto& p=s.pending;
      if(p.used&&p.direct&&p.attempts&&!p.inflight&&mt::receiptMatches(parsed,s.identity.node,p.contact.node,p.id,false)){
        ++metrics.rx_receipts;
        if(parsed.routing_error){clearPending(Delivery::Failed);status("Recipient returned a routing error");}
        else {const bool authenticated=parsed.authenticated;clearPending(authenticated?Delivery::Delivered:Delivery::ReceiptUnverified);status(authenticated?"Private message delivered":"Receipt received; sender proof unavailable");}
      }return;
    }
    if(parsed.kind==mt::Kind::NodeInfo){
      ++metrics.rx_nodes;
      if(parsed.has_public_key)discover(s.protocol,header.from,parsed.public_key,parsed.name);
      if(parsed.request_response&&s.tx&&!s.response.length&&!s.ack_inflight){
        auto options=tx();if(options.packet_id&&mt::encodeNodeInfo(s.channel,s.mt_identity,options,s.response,mt::platformCrypto(),false,header.from))s.ack_ready_at=now+500+s.storage.random()%1000;
      }return;
    }
    if(parsed.kind!=mt::Kind::Text||(header.to!=mt::Broadcast&&header.to!=s.identity.node))return;
    const bool direct=header.to!=mt::Broadcast;
    if(direct&&(!trusted||!parsed.authenticated))return;
    if(direct)queueReceipt(parsed,*peer,now);
    if(!remember(header.from,header.id,direct))return;
    Record record;record.protocol=s.protocol;record.id=header.id;record.peer=header.from;record.direct=direct;record.authenticated=parsed.authenticated;
    if(peer&&peer->name[0])copy(record.name,sizeof(record.name),peer->name);else std::snprintf(record.name,sizeof(record.name),"!%08lx",static_cast<unsigned long>(header.from));
    copy(record.text,sizeof(record.text),parsed.text);addRecord(record);++metrics.rx_text;status(direct?"Private message received":"Channel message received");return;
  }
  mc::Contact discovered;
  if(mc::parseAdvert(frame,length,mc::platformCrypto(),discovered)){
    if(std::memcmp(discovered.public_key,s.mc_identity.public_key,32)){++metrics.rx_nodes;discover(s.protocol,0,discovered.public_key,discovered.name);}return;
  }
  if(s.pending.used&&s.pending.direct&&s.pending.attempts&&!s.pending.inflight){
    mc::Message receipt;
    bool matched=false;
    for(unsigned attempt=0;attempt<s.pending.attempts&&!matched;++attempt)
      matched=mc::parseReceipt(frame,length,s.mc_identity,mcContact(s.pending.contact),s.pending.ack[attempt],mc::platformCrypto(),receipt);
    if(matched){
      ++metrics.rx_receipts;
      const bool verified=receipt.receipt_trust==mc::ReceiptTrust::AuthenticatedPeer;
      clearPending(verified?Delivery::Delivered:Delivery::ReceiptUnverified);status(verified?"Private message delivered":"Receipt received; sender proof unavailable");return;
    }
  }
  for(unsigned i=0;i<s.peers.count;++i){
    const auto& peer=s.peers.contacts[i];if(peer.protocol!=s.protocol||!peer.trusted||peer.key_changed)continue;
    mc::Message message;const auto contact=mcContact(peer);
    if(!mc::parseDirect(frame,length,s.mc_identity,contact,mc::platformCrypto(),message))continue;
    if(unixTime<1704067200U){status("Private message needs a fresh GPS UTC time");return;}
    if(message.timestamp<1704067200U)return;
    const auto peerHash=hash(peer.public_key,32);
    const bool seen=duplicate(s.peers.private_replay,peerHash,message.timestamp,std::uint8_t(s.protocol));
    if(message.timestamp<=s.peers.last_time[i]&&!seen)return;
    if(message.timestamp>unixTime+3600)return;
    if(s.tx&&!s.response.length&&!s.ack_inflight){mc::Frame response;if(mc::reply(s.mc_identity,contact,message,mc::platformCrypto(),response)){frameCopy(s.response,response);s.ack_ready_at=now+250+s.storage.random()%500;}}
    if(seen)return;
    s.peers.last_time[i]=std::max(s.peers.last_time[i],message.timestamp);
    if(!remember(peerHash,message.timestamp,true))return;
    Record record;record.protocol=s.protocol;record.id=message.timestamp;record.direct=record.authenticated=true;copy(record.name,sizeof(record.name),peer.name);copy(record.text,sizeof(record.text),message.text);addRecord(record);++metrics.rx_text;status("Private message received");return;
  }
  mc::Message group;
  if(mc::parseGroup(frame,length,mcKey(),mcKeyLength(),mc::platformCrypto(),group)){
    if(!rememberGroup(group.group_fingerprint))return;
    Record record;record.protocol=s.protocol;record.id=group.timestamp;copy(record.name,sizeof(record.name),group.name);copy(record.text,sizeof(record.text),group.text);addRecord(record);++metrics.rx_text;status("Channel message received (claimed sender)");
  }
}
} }
