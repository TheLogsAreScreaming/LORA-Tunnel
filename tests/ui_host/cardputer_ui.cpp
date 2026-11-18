#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <cstdlib>
#include <cstdint>
std::uint32_t hostMillis=0;
#include "../../src/ui_cardputer.cpp"
#include "messaging_regression.h"

namespace {
unsigned assertions=0;
struct Sent {ui::Action action;int field;std::string value;};
std::vector<Sent> sent;
void callback(ui::Action action,int field,const char* value) {sent.push_back({action,field,value});}
void expect(bool ok,const char* message) {++assertions;if(!ok){std::cerr<<"FAIL: "<<message<<"\n";std::exit(1);}}
void key(input::KeyCode code,ui::Model& model,char character=0) {hostMillis+=20;ui::keyboard({code,character},model);ui::tick(model);}
void textKey(char c,ui::Model& model) {key(input::KeyCode::Text,model,c);}
std::string quote(const std::string& text) {std::string out="\"";for(char c:text){if(c=='\\'||c=='\"')out+='\\';out+=c;}return out+'\"';}
void capture(const char* directory,const char* name,ui::Model& model,bool repaint=true) {
  if(repaint) {dirty=true;hw::display().commands.clear();ui::tick(model);}
  std::ofstream out(std::string(directory)+"/"+name+".json",std::ios::binary);out<<"[";bool first=true;
  for(const auto& c:hw::display().commands){if(!first)out<<",";first=false;
    out<<"{\"kind\":"<<quote(c.kind)<<",\"text\":"<<quote(c.text)<<",\"x\":"<<c.x<<",\"y\":"<<c.y<<",\"w\":"<<c.w<<",\"h\":"<<c.h<<",\"r\":"<<c.r<<",\"color\":"<<c.color<<",\"scale\":"<<c.scale<<"}";}
  out<<"]\n";expect(bool(out),"preview command file written");
}
bool screenHas(const char* text) {for(const auto& c:hw::display().commands)if(c.text.find(text)!=std::string::npos)return true;return false;}
void messagingChecks(const char* output,ui::Model& m) {
  ui_message_regression::run(expect);
  using ui::messages::Screen;using tunnel::messaging::Delivery;using tunnel::mesh::Protocol;
  m.notice[0]=0;m.running=false;m.upload_busy=false;m.messages={};
  std::strcpy(m.profile,"US LongTurbo / 908.750 MHz");std::strcpy(m.messages.channel,"LongTurbo");std::strcpy(m.messages.name,"Example operator");
  std::strcpy(m.messages.identity,"00112233445566778899AABBCCDDEEFF00112233445566778899AABBCCDDEEFF");m.messages.identity_ready=true;
  show(Page::Home);textKey('c',m);expect(page==Page::Messages&&messageState.screen==Screen::Mode,"Home C opens separate message protocol selection");capture(output,"messages-protocol",m);
  const auto before=sent.size();key(input::KeyCode::Select,m);
  expect(sent.size()==before+1&&sent.back().action==ui::Action::StartMessages&&sent.back().field==1,"Meshtastic requires explicit start and never switches capture mode");
  m.messages.active=true;capture(output,"messages-menu",m);expect(!ui::allowsBackgroundUpload()&&!ui::allowsUploadJobPolling(),"messaging suppresses network upload scheduling");
  focus=4;const auto noTx=sent.size();key(input::KeyCode::Select,m);expect(messageState.screen==Screen::TxConfirm&&sent.size()==noTx,"TX cannot turn on from a single menu selection");capture(output,"messages-enable-tx",m);
  key(input::KeyCode::Select,m);expect(sent.size()==noTx&&!m.messages.tx_enabled,"TX confirmation defaults to Cancel");
  focus=4;key(input::KeyCode::Select,m);key(input::KeyCode::Down,m);key(input::KeyCode::Select,m);
  expect(sent.back().action==ui::Action::ToggleMessageTx&&sent.back().field==1,"explicit TX confirmation enables current session only");m.messages.tx_enabled=true;
  focus=1;key(input::KeyCode::Select,m);expect(page==Page::Edit&&messageEditor&&messageState.target==-1,"channel composer uses physical keyboard");
  const char* punctuation="Hello, Mesh! : /;`@# ";for(const char* p=punctuation;*p;++p)textKey(*p,m);
  expect(inputLength==strlen(punctuation),"compose punctuation does not become navigation");key(input::KeyCode::Backspace,m);
  for(unsigned i=0;i<140;++i)textKey('x',m);expect(inputLength==120,"message composition caps text at120 bytes");capture(output,"messages-compose",m);
  key(input::KeyCode::Select,m);expect(sent.back().action==ui::Action::SendMessage&&sent.back().field==-1&&sent.back().value.size()==120,"one Enter queues one channel message");expect(!inputLength&&!messageEditor,"sent text buffer wiped");
  tunnel::messaging::Record records[6]{};tunnel::messaging::Contact contacts[8]{};
  for(unsigned i=0;i<6;++i) {auto& r=records[i];r.protocol=Protocol::Meshtastic;r.id=100+i;r.outgoing=i>0;r.direct=i==3;r.delivery=static_cast<Delivery>(i);std::snprintf(r.name,sizeof(r.name),"Example peer %u",i);std::memset(r.text,'a'+i,120);}
  for(unsigned i=0;i<8;++i) {auto& c=contacts[i];c.protocol=Protocol::Meshtastic;c.node=0x12340000+i;std::snprintf(c.name,sizeof(c.name),"Example contact %u",i);for(unsigned j=0;j<32;++j)c.public_key[j]=uint8_t(j+1+i);}
  m.messages.history=records;m.messages.history_count=255;m.messages.contacts=contacts;m.messages.contact_count=255;
  expect(ui::messages::count(messageState,m)==6,"malformed history count remains bounded by backing capacity");capture(output,"messages-inbox",m);focus=5;capture(output,"messages-inbox-more",m);
  key(input::KeyCode::Select,m);expect(messageState.screen==Screen::Detail,"inbox selection opens full120-byte detail");capture(output,"messages-detail",m);
  records[5].delivery=Delivery::ReceiptUnverified;capture(output,"messages-unverified-receipt",m);expect(screenHas("Receipt (unverified)"),"open detail tracks receipt changes without calling an unverified receipt Delivered");records[5].delivery=Delivery::Delivered;capture(output,"messages-delivered",m);expect(screenHas("Delivered"),"verified delivery can update an open detail view");
  key(input::KeyCode::Back,m);key(input::KeyCode::Back,m);focus=2;key(input::KeyCode::Select,m);capture(output,"messages-contacts",m);focus=7;capture(output,"messages-contacts-more",m);focus=0;key(input::KeyCode::Select,m);
  capture(output,"messages-contact",m);const auto untrusted=sent.size();key(input::KeyCode::Select,m);expect(page==Page::Messages&&sent.size()==untrusted&&messageState.error[0],"untrusted contact cannot open private composer");
  focus=1;key(input::KeyCode::Select,m);expect(messageState.screen==Screen::Trust,"trust requires independent confirmation screen");capture(output,"messages-trust",m);
  key(input::KeyCode::Down,m);key(input::KeyCode::Select,m);expect(sent.back().action==ui::Action::TrustContact&&sent.back().field==0&&sent.back().value.size()==64,"trust binds selected index and displayed full key");
  contacts[0].trusted=true;capture(output,"messages-contact-trusted",m);focus=0;key(input::KeyCode::Select,m);expect(page==Page::Edit&&messageState.target==0,"trusted private target uses contact index");textKey('Q',m);const auto cancelled=sent.size();key(input::KeyCode::Back,m);expect(sent.size()==cancelled&&inputLength==0,"cancelled private draft emits nothing and wipes input");
  contacts[0].key_changed=true;capture(output,"messages-key-changed",m);focus=0;key(input::KeyCode::Select,m);expect(page==Page::Messages&&messageState.error[0],"changed key blocks private compose despite prior trust");
  contacts[0].key_changed=contacts[0].trusted=false;focus=1;key(input::KeyCode::Select,m);const auto reviewed=messageState.contact;const auto beforeReplacement=sent.size();
  contacts[0].public_key[1]^=0x40;dirty=true;ui::tick(m);
  expect(messageState.contact_stale&&!std::memcmp(messageState.contact.public_key,reviewed.public_key,32),"Cardputer redraw cannot replace the fingerprint during review");
  focus=1;key(input::KeyCode::Select,m);expect(sent.size()==beforeReplacement&&messageState.screen==Screen::Trust,"Cardputer Enter approval rejects a changed live key and requires reopening");
  messageState.screen=Screen::Settings;show(Page::Messages);focus=2;key(input::KeyCode::Select,m);expect(page==Page::Edit&&inputLength==0,"channel key editor starts blank");capture(output,"messages-key-blank",m);textKey('Q',m);const auto invalid=sent.size();key(input::KeyCode::Select,m);expect(sent.size()==invalid&&page==Page::Edit,"invalid hexadecimal key rejected");
  key(input::KeyCode::Backspace,m);for(unsigned i=0;i<32;++i)textKey('A',m);capture(output,"messages-key-masked",m);expect(!screenHas("AAAA"),"messaging key is masked in rendered commands");key(input::KeyCode::Select,m);expect(sent.back().action==ui::Action::SaveMessagingSetting&&sent.back().field==2&&sent.back().value.size()==32,"masked channel key emitted only on Save");
  messageState.screen=Screen::Settings;show(Page::Messages);capture(output,"messages-settings",m);focus=4;capture(output,"messages-settings-more",m);key(input::KeyCode::Select,m);textKey('8',m);const auto badHop=sent.size();key(input::KeyCode::Select,m);expect(sent.size()==badHop&&messageState.error[0],"hop8 rejected");key(input::KeyCode::Backspace,m);textKey('3',m);key(input::KeyCode::Select,m);expect(sent.back().field==4&&sent.back().value=="3","hop0..7 accepted");
  for(Screen screen:{Screen::Mode,Screen::Menu,Screen::Inbox,Screen::Detail,Screen::Contacts,Screen::Contact,Screen::Trust,Screen::Settings,Screen::TxConfirm,Screen::Identity}) {
    messageState.screen=screen;show(Page::Messages);const unsigned count=std::max(1U,ui::messages::count(messageState,m));
    for(unsigned i=0;i<count;++i) {focus=i;dirty=true;ui::tick(m);++assertions;}
  }
  messageState.screen=Screen::Identity;show(Page::Messages);capture(output,"messages-identity",m);
  messageState.screen=Screen::Menu;show(Page::Messages);key(input::KeyCode::Back,m);expect(page==Page::Home&&sent.back().action==ui::Action::StopMessages,"leaving message mode explicitly stops radio and returns Home");
  m.messages.active=false;show(Page::Home);textKey('c',m);focus=1;key(input::KeyCode::Select,m);expect(sent.back().action==ui::Action::StartMessages&&sent.back().field==2,"MeshCore protocol is independently selectable");
  m.messages.protocol=Protocol::MeshCore;m.messages.active=true;std::strcpy(m.messages.channel,"Public");capture(output,"messages-meshcore",m);
  messageState.screen=Screen::Menu;m.messages.tx_enabled=false;focus=1;key(input::KeyCode::Select,m);textKey('Q',m);const auto off=sent.size();key(input::KeyCode::Select,m);expect(sent.size()==off&&page==Page::Edit&&messageState.error[0],"TX-off composer cannot emit a send action");key(input::KeyCode::Back,m);
  messageState.screen=Screen::Menu;key(input::KeyCode::Back,m);m.messages={};m.running=true;textKey('c',m);key(input::KeyCode::Select,m);expect(messageState.screen==Screen::Mode&&sent.back().action==ui::Action::StartMessages,"running capture keeps protocol chooser visible for root's stop/save notice");key(input::KeyCode::Back,m);m.running=false;messageEditor=false;
}
}
int main(int argc,char** argv) {
  expect(argc==2,"output directory supplied");const char* output=argv[1];
  ui::Model model;model.sd=true;model.battery=4.04f;model.buttons_enabled=false;
  ui::begin(callback);ui::tick(model);
  capture(output,"splash",model,false);
  expect(buffered,"32.4 KB RGB332 framebuffer allocated");
  expect(hostAllocationBytes==32400,"framebuffer remains exactly 32400 bytes");
  expect(hostAllocationCount==1,"logos require no additional UI heap allocation");
  expect(ui::acquireConfigScratch(16896)==nullptr,"scratch denies access before main installs idle guard");
  ui::setConfigScratchGuard([](){return true;});
  const auto beforeWait=hw::display().dmaWaits;
  void* borrowed=ui::acquireConfigScratch(16896);
  expect(borrowed && reinterpret_cast<uintptr_t>(borrowed)%alignof(std::max_align_t)==0,"scratch is aligned inside the real existing framebuffer");
  expect(hw::display().dmaWaits==beforeWait+1&&hw::display().displayWaits>0,"scratch waits for actual display transfer before overwriting pixels");
  expect(hostAllocationCount==1&&hostAllocationBytes==32400,"scratch adds no UI heap or framebuffer allocation");
  expect(ui::acquireConfigScratch(16)==nullptr,"nested lease is rejected");
  std::memset(borrowed,0xa5,16896);const size_t oldCommands=hw::display().commands.size();
  const bool oldSplash=splashShown;splashShown=false;ui::tick(model);
  expect(!splashShown&&hw::display().commands.size()==oldCommands,"lease blocks splash drawing and presenting scratch bytes");
  splashShown=oldSplash;ui::tick(model);ui::keyboard({input::KeyCode::Select,0},model);
  expect(hw::display().commands.size()==oldCommands&&sent.empty(),"lease blocks ordinary drawing and input actions");
  expect(!ui::allowsBackgroundUpload()&&!ui::allowsUploadJobPolling(),"lease suppresses background work permissions");
  ui::releaseConfigScratch(static_cast<uint8_t*>(borrowed)+1);
  expect(scratchMemory==borrowed,"wrong pointer cannot release active lease");
  hostTaskIdentity=2;ui::releaseConfigScratch(borrowed);
  expect(scratchMemory==borrowed,"different task cannot release another task's lease");
  hostTaskIdentity=1;ui::releaseConfigScratch(borrowed);
  const auto* wiped=static_cast<const uint8_t*>(borrowed);
  expect(!scratchMemory&&dirty&&std::all_of(wiped,wiped+16896,[](uint8_t b){return b==0;}),"release wipes every borrowed byte and forces redraw");
  hostMillis=1200;model.region_selection_made=true;hw::display().commands.clear();ui::tick(model);
  expect(!hw::display().commands.empty()&&hw::display().commands.front().x==0&&hw::display().commands.front().y==0&&hw::display().commands.front().w==240&&hw::display().commands.front().h==135,"next present starts with complete framebuffer repaint");
  ui::setConfigScratchGuard([](){return false;});expect(!ui::acquireConfigScratch(16896),"main idle guard can deny a lease");
  ui::setConfigScratchGuard([](){return true;});hostTaskIdentity=2;expect(!ui::acquireConfigScratch(16896),"worker task cannot acquire UI scratch");hostTaskIdentity=1;
  buffered=false;expect(!ui::acquireConfigScratch(16896),"direct-render fallback refuses scratch without heap fallback");buffered=true;
  expect(!ui::acquireConfigScratch(32401)&&!ui::acquireConfigScratch(0),"invalid or oversized lease does not touch framebuffer");
  // Restore initial UI lifecycle for the existing navigation cases.
  hostMillis=0;model.region_selection_made=false;ui::begin(callback);ui::tick(model);
  textKey('w',model);expect(page==Page::Home,"boot splash ignores early input");
  hostMillis=1200;ui::tick(model);expect(page==Page::Regions,"first boot selects region");capture(output,"regions",model);
  key(input::KeyCode::Back,model);expect(page==Page::Home,"Esc skips onboarding");
  expect(sent.back().action==ui::Action::SaveRegion && sent.back().value=="UNSET","skip persists explicit UNSET");
  model.region_selection_made=true;capture(output,"home",model);
  textKey('w',model);expect(page==Page::Drive,"keyboard works with optional buttons disabled");
  textKey(' ',model);expect(sent.back().action==ui::Action::ToggleSession,"Space starts capture");
  model.running=true;model.wifi=324;model.ble=2014;model.lora=17;model.gps=true;strcpy(model.phase,"BLE WINDOW");
  strcpy(model.profile,"US LongFast / 906.875 MHz");
  strcpy(model.recent[0][0],"Example AP  -53 dBm  CH6");strcpy(model.recent[0][1],"Test network  -71 dBm  CH11");
  strcpy(model.recent[1][0],"Example beacon  -60 dBm");strcpy(model.recent[2][0],"?12ab34cd  -93 dBm  7.5 dB");
  capture(output,"wardriver",model);key(input::KeyCode::Left,model);expect(tab==2,"radio tabs wrap backward");
  capture(output,"lora",model);key(input::KeyCode::Back,model);expect(model.running,"Home does not stop capture");
  textKey('r',model);expect(sent.back().action==ui::Action::ToggleMode && sent.back().field==1,"Recon requests mode transition");
  model.recon=true;model.recon_total=6;
  strcpy(model.recon_recent[0],"Example Find My advertisement");strcpy(model.recon_evidence[0],"Matching broadcast format; identity is not established.");model.recon_categories[0]=8;model.recon_confidence[0]=2;
  strcpy(model.recon_recent[1],"Example Remote ID broadcast");strcpy(model.recon_evidence[1],"Unauthenticated self-reported aircraft identification.");model.recon_categories[1]=7;model.recon_confidence[1]=3;
  capture(output,"recon",model);key(input::KeyCode::Select,model);expect(page==Page::Detail,"Enter opens evidence");capture(output,"detail",model);
  key(input::KeyCode::Back,model);textKey('m',model);expect(sent.back().action==ui::Action::ToggleAlerts && sent.back().field==0,"M toggles alerts");
  key(input::KeyCode::Right,model);expect(filter==1,"Right changes category");key(input::KeyCode::Select,model);expect(page==Page::Recon,"empty filter has no fake detail");
  textKey('s',model);expect(page==Page::Settings,"S opens settings during capture");capture(output,"settings",model);
  focus=4;capture(output,"settings-more",model);focus=0;
  key(input::KeyCode::Select,model);expect(page==Page::Regions,"region settings reachable");
  const size_t before=sent.size();key(input::KeyCode::Select,model);expect(sent.size()==before,"running capture prevents region change");
  model.running=false;
  for(size_t i=0;i<tunnel::lora_profiles::profileCount;++i) {
    regionIndex=int(i);show(Page::Regions);const size_t count=sent.size();key(input::KeyCode::Select,model);
    expect((sent.size()!=count)==tunnel::lora_profiles::selectable(tunnel::lora_profiles::profiles[i]),"only board-compatible regions can save");
  }
  show(Page::Settings);key(input::KeyCode::Down,model);key(input::KeyCode::Select,model);expect(page==Page::Credentials,"credentials reachable");
  capture(output,"credentials",model);focus=4;capture(output,"credentials-more",model);focus=0;key(input::KeyCode::Down,model);key(input::KeyCode::Select,model);
  expect(page==Page::Edit && editField==1,"WiGLE token edit selected");
  const char* secret="TestToken!@#$%: /,.;`+_=";for(const char* p=secret;*p;++p)textKey(*p,model);
  expect(inputLength==strlen(secret),"punctuation and space type without navigation");
  capture(output,"keyboard",model);expect(!screenHas("TestToken"),"secret input is masked");
  key(input::KeyCode::Backspace,model);expect(inputLength==strlen(secret)-1,"Backspace deletes one character");
  key(input::KeyCode::Select,model);expect(sent.back().action==ui::Action::SaveCredential && sent.back().field==1,"Enter saves correct credential");
  expect(inputLength==0 && inputValue[0]==0,"saved input wiped");
  key(input::KeyCode::Select,model);for(int i=0;i<150;++i)textKey('A',model);expect(inputLength==127,"input capacity bounded");
  const size_t oldCount=sent.size();key(input::KeyCode::Back,model);expect(sent.size()==oldCount && inputLength==0,"cancel wipes without save");
  for(unsigned fieldIndex=0;fieldIndex<6;++fieldIndex) {
    show(Page::Credentials);focus=fieldIndex;key(input::KeyCode::Select,model);
    const char* value=fieldIndex==4?"testpass":"x";
    for(const char* p=value;*p;++p)textKey(*p,model);key(input::KeyCode::Select,model);
    expect(sent.back().field==int(fieldIndex) && sent.back().value==value,"all credential fields reachable");
  }
  show(Page::Credentials);focus=4;key(input::KeyCode::Select,model);textKey('x',model);
  expect(!ui::allowsBackgroundUpload(),"editing prevents automatic association");
  const size_t invalidCount=sent.size();key(input::KeyCode::Select,model);
  expect(page==Page::Edit && inputLength==1 && sent.size()==invalidCount,"invalid password remains editable without save");
  capture(output,"keyboard-invalid",model);
  show(Page::Settings);focus=2;key(input::KeyCode::Select,model);expect(page==Page::Uploads,"uploads reachable");capture(output,"uploads",model);
  focus=4;capture(output,"uploads-more",model);focus=0;
  key(input::KeyCode::Select,model);expect(sent.back().action==ui::Action::ToggleAutoUpload && sent.back().field==0 && sent.back().value=="1","enable service explicit");
  model.auto_wigle=true;key(input::KeyCode::Select,model);expect(sent.back().value=="0","disable service explicit");
  model.running=true;focus=3;const size_t uploadCount=sent.size();key(input::KeyCode::Select,model);expect(sent.size()==uploadCount,"manual upload blocked during capture");expect(screenHas("Stop and save before upload"),"blocked manual upload has visible explanation");
  model.running=false;key(input::KeyCode::Select,model);expect(sent.back().action==ui::Action::UploadNow && sent.back().field==0,"manual WiGLE upload requested");
  model.upload_busy=true;focus=6;key(input::KeyCode::Select,model);expect(sent.back().action==ui::Action::CancelUpload,"upload cancellation reachable");model.upload_busy=false;
  std::strcpy(model.region,"US");model.region_configured=true;model.meshtastic_slots=104;
  show(Page::Settings);focus=6;model.lora_mode=0;const size_t meshBefore=sent.size();key(input::KeyCode::Select,model);
  expect(page==Page::MeshSettings && sent.size()==meshBefore,"Mesh settings opens without changing the receive mode");
  capture(output,"mesh-settings",model);key(input::KeyCode::Select,model);
  expect(page==Page::MeshChoice && meshField==ui::mesh_settings::Protocol,"protocol chooser opens with current selection");
  key(input::KeyCode::Down,model);key(input::KeyCode::Down,model);
  expect(meshChoice==2 && sent.size()==meshBefore,"choice navigation previews without saving or retuning");
  capture(output,"mesh-protocol",model);key(input::KeyCode::Select,model);
  expect(page==Page::MeshSettings && sent.size()==meshBefore+1 && sent.back().action==ui::Action::SaveLoRaMode && sent.back().field==2,"Enter requests exactly one combined-mode save");
  model.lora_mode=2;focus=1;key(input::KeyCode::Select,model);key(input::KeyCode::Down,model);
  expect(meshChoice==1 && screenHas("908.750 MHz / 500 kHz"),"LongTurbo previews its own default slot and modem bandwidth");
  capture(output,"mesh-long-turbo",model);key(input::KeyCode::Select,model);
  expect(sent.back().action==ui::Action::SaveMeshtasticPreset && sent.back().value=="LONG_TURBO","LongTurbo saves by stable preset code");
  std::strcpy(model.meshtastic_preset,"LONG_TURBO");model.meshtastic_slots=52;
  std::strcpy(model.profile,"US LongTurbo / 908.750 MHz");
  focus=2;key(input::KeyCode::Select,model);key(input::KeyCode::Down,model);
  for(int i=0;i<4;++i)key(input::KeyCode::Right,model);
  expect(meshChoice==14 && screenHas("908.750 MHz / slot 14"),"slot keyboard offers increments of ten and one with RF preview");
  capture(output,"mesh-slot",model);key(input::KeyCode::Select,model);
  expect(sent.back().action==ui::Action::SaveMeshtasticSlot && sent.back().field==14,"manual frequency slot saves explicitly");
  model.meshtastic_slot=14;const size_t slotCount=sent.size();key(input::KeyCode::Select,model);key(input::KeyCode::Right,model);key(input::KeyCode::Back,model);
  expect(page==Page::MeshSettings && focus==2 && sent.size()==slotCount && model.meshtastic_slot==14,"Escape cancels staged slot edit without saving");
  focus=3;key(input::KeyCode::Select,model);expect(ui::mesh_settings::count(meshField,model)==2,"Cardputer filters incompatible US-SOCAL MeshCore profile");
  key(input::KeyCode::Down,model);capture(output,"mesh-meshcore",model);key(input::KeyCode::Select,model);
  expect(sent.back().action==ui::Action::SaveMeshCoreProfile && sent.back().value=="US-NARROW","regional MeshCore profile saves by name");
  focus=4;key(input::KeyCode::Select,model);for(int i=0;i<4;++i)key(input::KeyCode::Down,model);
  capture(output,"mesh-dwell",model);key(input::KeyCode::Select,model);
  expect(sent.back().action==ui::Action::SaveLoRaDwell && sent.back().field==600000,"combined dwell saves milliseconds");
  focus=5;key(input::KeyCode::Select,model);key(input::KeyCode::Up,model);capture(output,"mesh-public-decoding",model);key(input::KeyCode::Select,model);
  expect(sent.back().action==ui::Action::SavePublicDecode && sent.back().field==0,"public decoding can be disabled independently");
  key(input::KeyCode::Back,model);expect(page==Page::Settings && focus==6,"mesh Back returns to its original Settings row");
  std::strcpy(model.region,"EU_868");model.meshtastic_slot=0;model.meshtastic_slots=1;
  meshField=ui::mesh_settings::Preset;meshChoice=1;show(Page::MeshChoice);
  const size_t rejected=sent.size();key(input::KeyCode::Select,model);
  expect(sent.size()==rejected && page==Page::MeshChoice && screenHas("Does not fit region"),"EU868 LongTurbo is visibly unavailable and cannot save");capture(output,"mesh-incompatible-region",model);
  std::strcpy(model.region,"US");model.meshtastic_slots=52;meshChoice=8;
  key(input::KeyCode::Select,model);expect(sent.size()==rejected,"Cardputer rejects ShortTurbo AUTO whose complete bandwidth exceeds U214 range");
  model.meshtastic_slot=14;key(input::KeyCode::Select,model);
  expect(sent.size()==rejected+1 && sent.back().value=="SHORT_TURBO","compatible manual slot permits the same modem preset without silent retuning");
  model.meshtastic_slot=0;meshField=ui::mesh_settings::Slot;meshChoice=43;show(Page::MeshChoice);
  const size_t invalidSlot=sent.size();key(input::KeyCode::Select,model);
  expect(sent.size()==invalidSlot && screenHas("Outside radio band"),"LongTurbo slot 43 rejects occupied bandwidth above 923 MHz");
  meshChoice=0;key(input::KeyCode::Up,model);expect(meshChoice==0,"slot decrements stop at AUTO");
  meshChoice=52;key(input::KeyCode::Down,model);expect(meshChoice==52,"slot increments stop at region slot count");
  for(unsigned guard=0;guard<4;++guard) {
    model.running=guard==0;model.upload_busy=guard==1;model.sd=guard!=2;model.region_configured=guard!=3;
    show(Page::MeshChoice);meshField=ui::mesh_settings::Protocol;meshChoice=1;const size_t old=sent.size();key(input::KeyCode::Select,model);
    expect(sent.size()==old && page==Page::MeshChoice && screenHas(ui::mesh_settings::blockedReason(model)),"capture, upload, missing SD and unset region block changes with an explanation");
  }
  model.running=model.upload_busy=false;model.sd=model.region_configured=true;
  std::strcpy(model.meshtastic_preset,"CUSTOM");model.meshtastic_slots=0;show(Page::MeshSettings);focus=1;capture(output,"mesh-custom",model);
  expect(screenHas("Custom / SD"),"imported numeric radio configuration is identified as custom");
  meshField=ui::mesh_settings::Slot;meshChoice=0;show(Page::MeshChoice);const size_t customCount=sent.size();key(input::KeyCode::Select,model);
  expect(sent.size()==customCount && screenHas("Custom SD preset"),"custom numeric preset cannot receive an invalid named slot save");
  std::strcpy(model.meshtastic_preset,"LONG_TURBO");model.meshtastic_slots=52;
  show(Page::MeshSettings);focus=4;capture(output,"mesh-settings-more",model);
  show(Page::Settings);focus=5;key(input::KeyCode::Select,model);expect(page==Page::Power && focus==0,"Power defaults to Cancel");capture(output,"power",model);
  const size_t powerCount=sent.size();key(input::KeyCode::Select,model);expect(page==Page::Settings && sent.size()==powerCount,"Power Cancel emits no shutdown");
  focus=5;key(input::KeyCode::Select,model);key(input::KeyCode::Right,model);key(input::KeyCode::Select,model);expect(sent.back().action==ui::Action::Shutdown,"Power confirmation requests shutdown");
  model.shutting_down=true;const size_t shuttingCount=sent.size();key(input::KeyCode::Select,model);textKey('w',model);expect(sent.size()==shuttingCount,"shutdown ignores input");capture(output,"saving",model);
  model.shutting_down=false;show(Page::Uploads);
  std::strcpy(model.upload_status,"WDGWars: job queued; receipt pending");
  std::strcpy(model.notice,"Upload preference save failed");
  hw::display().commands.clear();dirty=true;ui::tick(model);
  expect(screenHas("WDGWars: job queued"),"Uploads retains current worker status");
  expect(screenHas("Upload preference save failed"),"Uploads also shows setting/refusal notice");
  bool statusLine=false,noticeLine=false;
  for(const auto& command:hw::display().commands){
    if(command.text.find("WDGWars: job queued")!=std::string::npos)statusLine=command.y==98;
    if(command.text.find("Upload preference save failed")!=std::string::npos)noticeLine=command.y==110;}
  expect(statusLine&&noticeLine,"status and action notice occupy distinct nonoverlapping rows");capture(output,"uploads-status-notice",model);
  expect(!ui::allowsBackgroundUpload()&&ui::allowsUploadJobPolling(),"Uploads allows existing-job polling but suppresses new automatic uploads");
  for(Page guarded:{Page::Credentials,Page::Edit,Page::Power,Page::MeshSettings,Page::MeshChoice}){show(guarded);expect(!ui::allowsBackgroundUpload()&&!ui::allowsUploadJobPolling(),"editing and Power suppress both network scheduling paths");}
  show(Page::Settings);expect(ui::allowsBackgroundUpload()&&ui::allowsUploadJobPolling(),"normal idle page allows automatic work and job continuation");
  show(Page::Uploads);focus=6;hw::display().commands.clear();dirty=true;ui::tick(model);
  expect(screenHas("Cancel upload")&&screenHas("3/3"),"Cancel remains reachable on third Uploads page");
  key(input::KeyCode::Select,model);expect(sent.back().action==ui::Action::CancelUpload,"third-page cancel action preserved");
  messagingChecks(output,model);
  // Every page/focus and long valid model string must remain within 240 x 135.
  model.shutting_down=false;memset(model.notice,'N',sizeof(model.notice)-1);memset(model.upload_status,'U',sizeof(model.upload_status)-1);
  for(Page next:{Page::Home,Page::Drive,Page::Recon,Page::Detail,Page::Settings,Page::Credentials,Page::Edit,Page::Regions,Page::Power,Page::Uploads,Page::MeshSettings}) {
    show(next);const unsigned count=std::max(1U,menuCount(model));
    for(unsigned item=0;item<count;++item){focus=item;dirty=true;ui::tick(model);++assertions;}
  }
  for(const char* region:{"US","EU_868","ANZ","JP","UNSET"}) {
    std::strcpy(model.region,region);
    for(meshField=0;meshField<ui::mesh_settings::FieldCount;++meshField) {
      show(Page::MeshChoice);
      for(meshChoice=0;meshChoice<ui::mesh_settings::count(meshField,model);++meshChoice) {dirty=true;ui::tick(model);++assertions;}
    }
  }
  expect(hostAllocationCount==1 && hostAllocationBytes==32400,"mesh screens add no persistent or temporary UI heap allocation");
  show(Page::Home);ui::keyboard({input::KeyCode::Down,0},model);hostMillis+=45;ui::tick(model);
  expect(ui::inputLatencyMaxMs()>=45,"input latency includes queued time before draw");
  expect(latencyCount==64,"latency sample storage stays bounded after many key events");
  expect(ui::inputLatencyP95Ms()<=ui::inputLatencyMaxMs(),"latency percentile bounded by maximum");
  std::cout<<"Cardputer UI: "<<assertions<<" checks passed; all draw bounds checked. Synthetic previews only.\n";
}
