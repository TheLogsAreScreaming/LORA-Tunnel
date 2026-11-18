// Copyright (c) 2026 Valleytech Solutions. SPDX-License-Identifier: MIT
// Independently implemented from numeric protocol facts, not upstream code.
// References checked 2026-11-17:
// meshtastic/firmware@6d41e279f1f51bd59f687b9d441c1bf47b1594fc
//   src/mesh/{RadioInterface.h,CryptoEngine.cpp,Router.cpp}
// meshtastic/protobufs@62b09edf40711fd7bd17804b2fa62ba327fcea60/meshtastic/mesh.proto
#include "meshtastic_message.h"
#include "text_sanitize.h"
#include <cstring>

namespace tunnel { namespace meshtastic { namespace {
constexpr std::size_t HeaderBytes=16, PayloadBytes=239;
void wipe(void* value,std::size_t length) {
  volatile std::uint8_t* p=static_cast<volatile std::uint8_t*>(value);
  while(length--)*p++=0;
}
struct Secret {
  std::uint8_t bytes[PayloadBytes]{};
  ~Secret(){wipe(bytes,sizeof(bytes));}
};
void write32(std::uint8_t* p,std::uint32_t v) {
  for(unsigned i=0;i<4;++i)p[i]=std::uint8_t(v>>(8*i));
}
std::uint32_t read32(const std::uint8_t* p) {
  return std::uint32_t(p[0])|(std::uint32_t(p[1])<<8)|(std::uint32_t(p[2])<<16)|(std::uint32_t(p[3])<<24);
}
bool nonzero(const std::uint8_t* p,std::size_t n) {std::uint8_t v=0;while(n--)v|=*p++;return v!=0;}
bool nodeValid(std::uint32_t n) {return n>3 && n!=Broadcast;}
bool same(const std::uint8_t* a,const std::uint8_t* b,std::size_t n) {
  std::uint8_t diff=0;while(n--)diff|=*a++^*b++;return diff==0;
}
bool channelValid(const Channel& c) {return c.key_length==0 || c.key_length==16 || c.key_length==32;}
bool txValid(const Identity& i,const Tx& t,std::uint32_t to) {
  return nodeValid(i.node) && (nodeValid(to)||to==Broadcast) && to!=i.node && t.packet_id && t.hop_limit<=7;
}
bool peerValid(const Identity& local,const Contact& peer) {
  return nodeValid(local.node)&&nodeValid(peer.node)&&local.node!=peer.node&&peer.has_public_key&&
         nonzero(local.private_key,32)&&nonzero(peer.public_key,32);
}
bool textLength(const char* s,std::size_t maximum,std::size_t& n,bool empty=false) {
  if(!s)return false;
  n=0;while(n<=maximum&&s[n])++n;
  if(n>maximum || (!n&&!empty))return false;
  char checked[TextBytes+1];
  return !copyUtf8Bounded(checked,sizeof(checked),reinterpret_cast<const std::uint8_t*>(s),n);
}
struct Writer {
  std::uint8_t* p;std::size_t capacity,n=0;bool ok=true;
  Writer(std::uint8_t* b,std::size_t size):p(b),capacity(size){}
  void byte(std::uint8_t v){if(n>=capacity){ok=false;return;}p[n++]=v;}
  void var(std::uint32_t v){do{const auto b=std::uint8_t(v&127);v>>=7;byte(b|(v?128:0));}while(v);}
  void scalar(unsigned field,std::uint32_t v){var(field<<3);var(v);}
  void fixed(unsigned field,std::uint32_t v){var((field<<3)|5);for(unsigned i=0;i<4;++i)byte(std::uint8_t(v>>(i*8)));}
  void bytes(unsigned field,const std::uint8_t* b,std::size_t size) {
    var((field<<3)|2);var(std::uint32_t(size));
    if(size>capacity-n){ok=false;return;}if(size)std::memcpy(p+n,b,size);n+=size;
  }
};
struct Field {std::uint32_t number=0;std::uint8_t wire=0;std::uint64_t value=0;const std::uint8_t* bytes=nullptr;std::size_t length=0,start=0,end=0;};
struct Reader {
  const std::uint8_t* p;std::size_t n,at=0;bool ok=true;
  Reader(const std::uint8_t* b,std::size_t size):p(b),n(size){}
  bool var(std::uint64_t& v) {
    v=0;for(unsigned i=0;i<10;++i){if(at==n)return false;auto b=p[at++];if(i==9&&b>1)return false;
      v|=std::uint64_t(b&127)<<(7*i);if(!(b&128))return true;}return false;
  }
  bool next(Field& f) {
    if(!ok||at==n)return false;
    f=Field{};f.start=at;std::uint64_t tag;
    if(!var(tag)||tag>0xffffffffU||!(tag>>3))return ok=false;
    f.number=std::uint32_t(tag>>3);f.wire=std::uint8_t(tag&7);
    if(f.wire==0)ok=var(f.value);
    else if(f.wire==1||f.wire==5){const unsigned count=f.wire==1?8:4;if(count>n-at)return ok=false;
      for(unsigned i=0;i<count;++i)f.value|=std::uint64_t(p[at++])<<(8*i);}
    else if(f.wire==2){std::uint64_t size;if(!var(size)||size>n-at)return ok=false;
      f.bytes=p+at;f.length=std::size_t(size);at+=f.length;}
    else return ok=false;
    f.end=at;return ok;
  }
  bool complete()const{return ok&&at==n;}
};
bool once(std::uint32_t& seen,unsigned n){if(n>=32)return true;const auto bit=std::uint32_t(1)<<n;if(seen&bit)return false;seen|=bit;return true;}
void nonce(std::uint8_t bytes[16],std::uint32_t sender,std::uint32_t id,std::uint32_t extra=0) {
  std::memset(bytes,0,16);write32(bytes,id);write32(bytes+4,extra);write32(bytes+8,sender);
}
void header(Frame& f,const Identity& local,std::uint32_t to,const Tx& tx,std::uint8_t channel,bool ack) {
  f=Frame{};write32(f.bytes,to);write32(f.bytes+4,local.node);write32(f.bytes+8,tx.packet_id);
  f.bytes[12]=tx.hop_limit|(tx.hop_limit<<5)|(ack?8:0);f.bytes[13]=channel;
}
bool sealChannel(const std::uint8_t* plain,std::size_t n,const Channel& ch,const Identity& local,
                 std::uint32_t to,const Tx& tx,bool ack,Frame& out,const Crypto& crypto) {
  out=Frame{};if(!txValid(local,tx,to)||!channelValid(ch)||n>PayloadBytes)return false;
  header(out,local,to,tx,ch.hash,ack);
  if(ch.key_length){std::uint8_t iv[16];nonce(iv,local.node,tx.packet_id);
    const bool ok=crypto.ctr&&crypto.ctr(ch.key,ch.key_length,iv,plain,n,out.bytes+HeaderBytes);wipe(iv,sizeof(iv));
    if(!ok){out=Frame{};return false;}}
  else std::memcpy(out.bytes+HeaderBytes,plain,n);
  out.length=HeaderBytes+n;return true;
}
bool sealPrivate(const std::uint8_t* plain,std::size_t n,const Identity& local,const Contact& peer,
                 const Tx& tx,bool ack,Frame& out,const Crypto& crypto) {
  out=Frame{};if(!txValid(local,tx,peer.node)||!peerValid(local,peer)||n>PayloadBytes-12||!crypto.sharedKey||!crypto.ccmSeal)return false;
  std::uint8_t key[32]{},iv[16];nonce(iv,local.node,tx.packet_id,tx.extra_nonce);
  header(out,local,peer.node,tx,0,ack);
  const bool ok=crypto.sharedKey(local.private_key,peer.public_key,key)&&
      crypto.ccmSeal(key,iv,plain,n,out.bytes+HeaderBytes,out.bytes+HeaderBytes+n);
  wipe(key,sizeof(key));wipe(iv,sizeof(iv));
  if(!ok){out=Frame{};return false;}
  write32(out.bytes+HeaderBytes+n+8,tx.extra_nonce);out.length=HeaderBytes+n+12;return true;
}
bool textData(const char* text,Secret& plain,std::size_t& n) {
  std::size_t length;if(!textLength(text,TextBytes,length))return false;
  Writer w(plain.bytes,sizeof(plain.bytes));w.scalar(1,1);w.bytes(2,reinterpret_cast<const std::uint8_t*>(text),length);n=w.n;return w.ok;
}
bool receiptProof(const Identity& local,const Contact& peer,std::uint32_t from,std::uint32_t to,
                  std::uint32_t request,const std::uint8_t* routing,std::size_t n,std::uint8_t proof[8],const Crypto& crypto) {
  if(!peerValid(local,peer)||!request||n>PayloadBytes-15||!crypto.sharedKey||!crypto.hmac)return false;
  std::uint8_t key[32]{},digest[32]{};Secret input;
  input.bytes[0]='a';input.bytes[1]='c';input.bytes[2]='k';write32(input.bytes+3,from);write32(input.bytes+7,to);
  write32(input.bytes+11,request);std::memcpy(input.bytes+15,routing,n);
  const bool ok=crypto.sharedKey(local.private_key,peer.public_key,key)&&crypto.hmac(key,input.bytes,n+15,digest);
  if(ok)std::memcpy(proof,digest,8);else wipe(proof,8);
  wipe(key,sizeof(key));wipe(digest,sizeof(digest));return ok;
}
bool receiptData(Secret& plain,std::size_t& n,std::uint32_t request,std::uint32_t error,
                 const Identity& local,std::uint32_t to,const Contact* peer,const Crypto& crypto) {
  if(!request)return false;
  std::uint8_t routing[24]{};Writer rw(routing,sizeof(routing));rw.scalar(3,error);
  if(peer){if(peer->node!=to)return false;std::uint8_t proof[8]{};
    if(!receiptProof(local,*peer,local.node,to,request,routing,rw.n,proof,crypto))return false;
    rw.bytes(4,proof,sizeof(proof));wipe(proof,sizeof(proof));}
  Writer w(plain.bytes,sizeof(plain.bytes));w.scalar(1,5);w.bytes(2,routing,rw.n);w.fixed(6,request);n=w.n;return rw.ok&&w.ok;
}
struct RoutingProof {std::uint8_t bytes[PayloadBytes]{};std::size_t length=0;const std::uint8_t* proof=nullptr;};
bool parseRouting(const std::uint8_t* bytes,std::size_t n,Parsed& out,RoutingProof& proof) {
  Reader r(bytes,n);Field f;std::uint32_t seen=0;
  while(r.next(f)){
    if(f.number<=4&&!once(seen,f.number))return false;
    if(f.number==1||f.number==2)return false; // Route discovery is not a delivery receipt.
    if(f.number==3){if(f.wire!=0||f.value>UINT32_MAX)return false;out.routing_error=std::uint32_t(f.value);}
    if(f.number==4){if(f.wire!=2||f.length!=8)return false;out.has_receipt_proof=true;proof.proof=f.bytes;}
    else {const auto size=f.end-f.start;if(size>sizeof(proof.bytes)-proof.length)return false;
      std::memcpy(proof.bytes+proof.length,bytes+f.start,size);proof.length+=size;}
  }
  // Proto3 older peers may represent NONE with an empty message.
  return r.complete();
}
bool parseUser(const std::uint8_t* bytes,std::size_t n,Parsed& out) {
  Reader r(bytes,n);Field f;std::uint32_t seen=0;
  while(r.next(f)){
    if(f.number<=9&&!once(seen,f.number))return false;
    switch(f.number){
      case 1:case 4:if(f.wire!=2)return false;break;
      case 2:case 3:if(f.wire!=2)return false;
        out.sanitized|=copyUtf8Bounded(f.number==2?out.name:out.short_name,f.number==2?sizeof(out.name):sizeof(out.short_name),f.bytes,f.length);break;
      case 5:case 7:if(f.wire!=0||f.value>UINT32_MAX)return false;break;
      case 6:case 9:if(f.wire!=0||f.value>1)return false;break;
      case 8:if(f.wire!=2||(f.length!=0&&f.length!=32))return false;
        if(f.length){std::memcpy(out.public_key,f.bytes,32);out.has_public_key=nonzero(out.public_key,32);}break;
      default:break;
    }
  }
  return r.complete();
}
bool parseData(const std::uint8_t* bytes,std::size_t n,Parsed& out,const Identity* local,const Contact* peer,const Crypto& crypto) {
  Reader r(bytes,n);Field f;std::uint32_t seen=0,port=0;
  const std::uint8_t* payload=nullptr;std::size_t length=0;
  while(r.next(f)){
    if(f.number<=10&&!once(seen,f.number))return false;
    switch(f.number){
      case 1:if(f.wire!=0||f.value>UINT32_MAX)return false;port=std::uint32_t(f.value);break;
      case 2:if(f.wire!=2)return false;payload=f.bytes;length=f.length;break;
      case 3:if(f.wire!=0||f.value>1)return false;out.request_response|=f.value!=0;break;
      case 4:case 5:if(f.wire!=5)return false;
        if(f.value&&f.value!=(f.number==4?out.header.to:out.header.from))return false;break;
      case 6:case 7:case 8:if(f.wire!=5)return false;
        if(f.number==6)out.request_id=std::uint32_t(f.value);if(f.number==7)out.reply_id=std::uint32_t(f.value);break;
      case 9:if(f.wire!=0||f.value>UINT32_MAX)return false;
        out.request_response|=(f.value&2)!=0;break;
      default:break;
    }
  }
  if(!r.complete()||!port)return false;
  if(port==1){if(!payload||!length||length>TextBytes)return false;out.kind=Kind::Text;
    out.sanitized=copyUtf8Bounded(out.text,sizeof(out.text),payload,length);return true;}
  if(port==4){out.kind=Kind::NodeInfo;return parseUser(payload,length,out);}
  if(port==5){if(!out.request_id||out.header.to==Broadcast)return false;out.kind=Kind::Receipt;
    RoutingProof routing;if(!parseRouting(payload,length,out,routing))return false;
    if(out.has_receipt_proof&&local&&peer){
      if(out.header.to!=local->node||out.header.from!=peer->node)return false;
      std::uint8_t expected[8]{};
      out.receipt_proof_valid=receiptProof(*local,*peer,out.header.from,out.header.to,out.request_id,
                                         routing.bytes,routing.length,expected,crypto)&&same(expected,routing.proof,8);
      wipe(expected,sizeof(expected));
      if(!out.receipt_proof_valid){out.status=Status::CryptoFailed;return false;}
      out.authenticated=true;
    }
    return true;
  }
  out.status=Status::Unsupported;return false;
}
bool failure(Parsed& out,Status status){const Header h=out.header;out=Parsed{};out.header=h;out.status=status;return false;}
} // namespace

bool peekHeader(const std::uint8_t* bytes,std::size_t n,Header& h) {
  Header candidate;if(!lt::parseMeshHeader(bytes,n,candidate)||n<=HeaderBytes||!nodeValid(candidate.from)||
      (!nodeValid(candidate.to)&&candidate.to!=Broadcast)||!candidate.id)return false;
  h=candidate;return true;
}
bool encodeChannelText(const Channel& ch,const Identity& local,const Tx& tx,const char* text,Frame& out,const Crypto& crypto) {
  out=Frame{};Secret data;std::size_t n=0;return textData(text,data,n)&&sealChannel(data.bytes,n,ch,local,Broadcast,tx,tx.want_ack,out,crypto);
}
bool encodePrivateText(const Identity& local,const Contact& peer,const Tx& tx,const char* text,Frame& out,const Crypto& crypto) {
  out=Frame{};Secret data;std::size_t n=0;return textData(text,data,n)&&sealPrivate(data.bytes,n,local,peer,tx,tx.want_ack,out,crypto);
}
bool encodeNodeInfo(const Channel& ch,const Identity& local,const Tx& tx,Frame& out,const Crypto& crypto,bool request_response,std::uint32_t to) {
  out=Frame{};std::size_t nameLength,shortLength;
  if(!textLength(local.name,NameBytes,nameLength)||!textLength(local.short_name,4,shortLength,true))return false;
  std::uint8_t user[100]{};Writer u(user,sizeof(user));
  char id[9];id[0]='!';const char hex[]="0123456789abcdef";for(unsigned i=0;i<8;++i)id[i+1]=hex[(local.node>>(28-4*i))&15];
  u.bytes(1,reinterpret_cast<const std::uint8_t*>(id),sizeof(id));
  u.bytes(2,reinterpret_cast<const std::uint8_t*>(local.name),nameLength);
  if(shortLength)u.bytes(3,reinterpret_cast<const std::uint8_t*>(local.short_name),shortLength);
  if(nonzero(local.public_key,32))u.bytes(8,local.public_key,32);
  Secret data;Writer w(data.bytes,sizeof(data.bytes));w.scalar(1,4);w.bytes(2,user,u.n);if(request_response)w.scalar(3,1);
  return u.ok&&w.ok&&sealChannel(data.bytes,w.n,ch,local,to,tx,tx.want_ack,out,crypto);
}
bool encodeReceipt(const Channel& ch,const Identity& local,std::uint32_t to,const Tx& tx,std::uint32_t request,
                   std::uint32_t error,Frame& out,const Crypto& crypto,const Contact* peer) {
  out=Frame{};if(!nodeValid(to))return false;Secret data;std::size_t n=0;
  return receiptData(data,n,request,error,local,to,peer,crypto)&&sealChannel(data.bytes,n,ch,local,to,tx,false,out,crypto);
}
bool encodePrivateReceipt(const Identity& local,const Contact& peer,const Tx& tx,std::uint32_t request,
                          std::uint32_t error,Frame& out,const Crypto& crypto) {
  out=Frame{};Secret data;std::size_t n=0;
  return receiptData(data,n,request,error,local,peer.node,nullptr,crypto)&&sealPrivate(data.bytes,n,local,peer,tx,false,out,crypto);
}
bool decodeChannel(const std::uint8_t* bytes,std::size_t n,const Channel& ch,Parsed& out,const Crypto& crypto,
                   const Identity* local,const Contact* peer) {
  out=Parsed{};if(!peekHeader(bytes,n,out.header)||!channelValid(ch))return false;
  if(out.header.channel!=ch.hash)return failure(out,Status::WrongChannel);
  Secret plain;const auto length=n-HeaderBytes;
  if(ch.key_length){std::uint8_t iv[16];nonce(iv,out.header.from,out.header.id);
    const bool ok=crypto.ctr&&crypto.ctr(ch.key,ch.key_length,iv,bytes+HeaderBytes,length,plain.bytes);wipe(iv,sizeof(iv));
    if(!ok)return failure(out,Status::CryptoFailed);}
  else std::memcpy(plain.bytes,bytes+HeaderBytes,length);
  if(!parseData(plain.bytes,length,out,local,peer,crypto))return failure(out,out.status);
  out.status=Status::Ok;return true;
}
bool decodePrivate(const std::uint8_t* bytes,std::size_t n,const Identity& local,const Contact& peer,Parsed& out,const Crypto& crypto) {
  out=Parsed{};if(!peekHeader(bytes,n,out.header)||n<=HeaderBytes+12)return false;
  if(!peerValid(local,peer)||out.header.to!=local.node||out.header.from!=peer.node||out.header.channel!=0)return failure(out,Status::WrongPeer);
  if(!crypto.sharedKey||!crypto.ccmOpen)return failure(out,Status::CryptoFailed);
  const auto length=n-HeaderBytes-12;std::uint8_t key[32]{},iv[16];Secret plain;
  nonce(iv,out.header.from,out.header.id,read32(bytes+n-4));
  const bool ok=crypto.sharedKey(local.private_key,peer.public_key,key)&&
      crypto.ccmOpen(key,iv,bytes+HeaderBytes,length,bytes+HeaderBytes+length,plain.bytes);
  wipe(key,sizeof(key));wipe(iv,sizeof(iv));
  if(!ok)return failure(out,Status::CryptoFailed);
  if(!parseData(plain.bytes,length,out,nullptr,nullptr,crypto))return failure(out,out.status);
  out.private_envelope=true;out.authenticated=true;out.status=Status::Ok;return true;
}
bool receiptMatches(const Parsed& p,std::uint32_t local,std::uint32_t peer,std::uint32_t request,bool require_authenticated) {
  return p.status==Status::Ok&&p.kind==Kind::Receipt&&nodeValid(local)&&nodeValid(peer)&&local!=peer&&request&&
      p.header.to==local&&p.header.from==peer&&p.request_id==request&&p.header.id&&
      (!require_authenticated||p.authenticated);
}
} }
