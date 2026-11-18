#include <Arduino.h>
#include <ArduinoJson.h>
#include <iostream>
#include <map>
namespace host {
bool failScratch=false,failRules=false;size_t scratchLive=0,scratchPeak=0,scratchCalls=0,heapScratchCalls=0;
struct ScratchAllocator {
  void* allocate(size_t bytes){++heapScratchCalls;++scratchCalls;if(failScratch)return nullptr;void* p=std::malloc(bytes);if(p){scratchLive+=bytes;scratchPeak=std::max(scratchPeak,scratchLive);}return p;}
  void deallocate(void* pointer){if(pointer)scratchLive-=16384;std::free(pointer);}
  void* reallocate(void*,size_t){return nullptr;}
};
}
void* operator new[](std::size_t bytes,const std::nothrow_t&) noexcept {return host::failRules?nullptr:std::malloc(bytes);}
void operator delete[](void* pointer) noexcept {std::free(pointer);}
void operator delete[](void* pointer,std::size_t) noexcept {std::free(pointer);}
using HostScopedJsonDocument=ArduinoJson::BasicJsonDocument<host::ScratchAllocator>;
#define DynamicJsonDocument HostScopedJsonDocument
#include "../../src/config.cpp"
#undef DynamicJsonDocument
namespace host {
uint32_t epoch=1;
unsigned openFiles=0,regularFiles=0,peakRegularFiles=0,bufferCalls=0,failBufferCall=0;
std::map<std::string,std::string> files,preferences;std::vector<std::string> directories;
std::string failWritePath,failOpenPath;bool failRename=false,failPreferences=false;
}
ConfigSD SD;
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
#include "checked_backend.h"
#endif
namespace tunnel {namespace recon {
bool parseAddress(const char* text,uint8_t result[6]) {unsigned bytes[6];if(!text||std::sscanf(text,"%02x:%02x:%02x:%02x:%02x:%02x",bytes,bytes+1,bytes+2,bytes+3,bytes+4,bytes+5)!=6)return false;for(unsigned i=0;i<6;++i)result[i]=uint8_t(bytes[i]);return true;}
}}
namespace {
unsigned checks=0;
void expect(bool value,const char* description){++checks;if(!value){std::cerr<<"FAIL "<<description<<"\n";std::exit(1);}}
const char* primary="/lora-tunnel/config.json";
const char* ruleFile="/lora-tunnel/detection_rules.json";
const char* initial=R"({"schema":1,"lora":{"region":"UNSET","selection_complete":false,"enabled":false},"credentials":{"wigle_api_name":"old-name","wigle_api_token":"old-token","wifi_ssid":"Home","wifi_password":"password"},"extension":{"preserved":"yes"}})";
void reset(){
  host::fileHooks()=host::FileHooks{};
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
  host::resetCheckedFaults();
#endif
expect(host::openFiles==0,"all file handles closed between operations");host::bufferCalls=host::failBufferCall=host::peakRegularFiles=0;host::files.clear();host::directories.clear();host::preferences.clear();host::failWritePath.clear();host::failOpenPath.clear();host::failRename=host::failPreferences=host::failScratch=false;host::scratchCalls=host::scratchPeak=host::heapScratchCalls=0;expect(host::scratchLive==0,"no document survives a prior operation");host::files[primary]=initial;host::files[ruleFile]=R"({"schema":1,"rules":[]})";}
void released(){expect(host::scratchLive==0,"configuration scratch released on return");
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
 expect(!host::leaseActive&&host::checkedHandles.empty(),"lease and all checked file handles end on return");
 expect(std::all_of(host::frameScratch,host::frameScratch+16896,[](uint8_t b){return b==0;}),"all JSON and file-buffer secret bytes are wiped on release");
#endif
}
void meshSettingsChecks(){
  using namespace tunnel;
  reset();
  // These are public synthetic fixture keys, never captured/private user data.
  host::files[primary]=R"({"schema":1,"lora":{"region":"US","enabled":true,"mode":"combined","meshtastic_preset":"LONG_FAST","meshtastic_slot":0,"meshcore_profile":"AUTO","decode_public":true,"meshtastic_keys":[{"name":"LongFast","key_hex":"d4f1bb3a20290759f0bcffabcf4e6901","future_key_metadata":"keep"}],"meshcore_keys":[{"name":"Fixture sixteen","key_hex":"000102030405060708090a0b0c0d0e0f"},{"name":"Fixture thirtytwo","key_hex":"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"}],"future_radio_setting":{"preserved":true}},"credentials":{"wifi_ssid":"Fixture","wifi_password":"fixture-password"},"extension":{"preserved":"yes"}})";
  expect(loadConfig(),"mesh settings fixture loads");released();
  expect(config.mesh_key_count==1&&config.meshcore_key_count==2&&config.meshcore_keys[1].length==32,"both protocol key lists load");
  expect(saveMeshtasticPreset("LONG_TURBO"),"LongTurbo preset saves");released();
  expect(!std::strcmp(config.meshtastic_preset,"LONG_TURBO")&&config.frequency==908.75f&&config.bandwidth==500&&config.sf==11&&config.cr==8,"saved LongTurbo updates modulation and default frequency together");
  expect(saveMeshtasticSlot(3),"explicit Meshtastic slot saves");released();
  expect(config.meshtastic_slot==3&&config.frequency==903.25f,"explicit slot immediately updates receive frequency");
  expect(saveLoRaDwell(120000),"mesh dwell saves");released();
  expect(savePublicDecode(false),"public key preference saves");released();
  expect(saveMeshCoreProfile("US-NARROW"),"explicit MeshCore profile saves");released();
  expect(saveLoRaMode(1),"MeshCore-only mode saves");released();
  expect(config.lora_mode==1&&config.lora_dwell_ms==120000&&!config.decode_public&&config.lora_enabled&&regionHardwareCompatible()&&regionSelectionMade(),"complete live mesh state matches committed settings");
  expect(loadConfig(),"committed mesh settings reload");released();
  expect(!std::strcmp(config.meshtastic_preset,"LONG_TURBO")&&config.meshtastic_slot==3&&config.frequency==903.25f&&config.bandwidth==500&&config.lora_mode==1&&config.lora_dwell_ms==120000&&!config.decode_public,"preset slot dwell mode and public preference survive restart");
  expect(config.mesh_key_count==1&&config.meshcore_key_count==2&&config.mesh_keys[0].bytes[0]==0xd4&&config.meshcore_keys[0].length==16&&config.meshcore_keys[1].length==32&&config.meshcore_keys[1].bytes[31]==31,"explicit keys remain usable with public defaults disabled");
  const auto assertPreserved=[](){
    ArduinoJson::StaticJsonDocument<4096> document;
    expect(!deserializeJson(document,host::files[primary]),"saved mesh document parses");
    expect(document["extension"]["preserved"]=="yes"&&document["lora"]["future_radio_setting"]["preserved"]==true&&document["lora"]["meshtastic_keys"][0]["future_key_metadata"]=="keep","mesh saves preserve unknown root radio and key fields");
    expect(document["lora"]["meshtastic_keys"][0]["key_hex"]=="d4f1bb3a20290759f0bcffabcf4e6901"&&document["lora"]["meshcore_keys"][0]["name"]=="Fixture sixteen"&&document["lora"]["meshcore_keys"][1]["key_hex"]=="000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f","mesh saves preserve exact named key documents");
    expect(document["credentials"]["wifi_password"]=="fixture-password","mesh saves preserve unrelated credentials");
  };
  assertPreserved();
  const auto before=host::files[primary];
  uint8_t live[sizeof(config)];std::memcpy(live,&config,sizeof(config));
  const bool selected=regionSelectionMade(),compatible=regionHardwareCompatible();
  host::failWritePath="config.tmp";
  for(unsigned operation=0;operation!=6;++operation){
    bool result=false;
    switch(operation){
      case 0:result=saveMeshtasticPreset("MEDIUM_FAST");break;
      case 1:result=saveMeshtasticSlot(4);break;
      case 2:result=saveMeshCoreProfile("AUTO");break;
      case 3:result=saveLoRaDwell(60000);break;
      case 4:result=savePublicDecode(true);break;
      case 5:result=saveLoRaMode(0);break;
    }
    expect(!result,"mesh setting reports temporary-write failure");released();
    expect(host::files[primary]==before&&!host::files.count("/lora-tunnel/config.tmp"),"failed mesh save preserves primary and removes temporary file");
    expect(!std::memcmp(live,&config,sizeof(config))&&regionSelectionMade()==selected&&regionHardwareCompatible()==compatible,"failed mesh save leaves all live settings and compatibility flags unchanged");
  }
  host::failWritePath.clear();
  // A successful write followed by an old but valid readback must not report
  // success, replace the primary, or restore old live settings.
  host::fileHooks().afterFlush=[](const std::string& file){
    if(file=="/lora-tunnel/config.tmp")host::files[file]=host::files[primary];
  };
  for(unsigned operation=0;operation!=6;++operation){
    bool result=false;
    switch(operation){
      case 0:result=saveMeshtasticPreset("MEDIUM_FAST");break;
      case 1:result=saveMeshtasticSlot(4);break;
      case 2:result=saveMeshCoreProfile("AUTO");break;
      case 3:result=saveLoRaDwell(60000);break;
      case 4:result=savePublicDecode(true);break;
      case 5:result=saveLoRaMode(0);break;
    }
    expect(!result,"different valid readback rejects a mesh save");released();
    expect(host::files[primary]==before&&!host::files.count("/lora-tunnel/config.tmp"),"stale readback preserves primary and removes temp");
    expect(!std::memcmp(live,&config,sizeof(config)),"stale readback leaves live mesh configuration unchanged");
  }
  host::fileHooks().afterFlush=nullptr;
  host::files["/lora-tunnel/config.bak"]=before;host::files[primary]="{bad";
  expect(loadConfig()&&configLoadState==ConfigLoadState::Backup,"mesh configuration recovers from valid backup");released();
  expect(saveMeshtasticSlot(4)&&configLoadState==ConfigLoadState::Primary,"mesh save promotes recovered backup with chosen slot");released();assertPreserved();
  const auto recoverable=host::files[primary];
  for(unsigned corrupt=0;corrupt!=2;++corrupt){
    if(corrupt){host::files[primary]="{bad primary";host::files["/lora-tunnel/config.bak"]="{bad backup";}
    else{host::files.erase(primary);host::files.erase("/lora-tunnel/config.bak");}
    const auto untouched=host::files;
    std::memcpy(live,&config,sizeof(config));
    expect(!savePublicDecode(true),"missing or corrupt key source cannot be replaced by a seed without named keys");released();
    expect(host::files==untouched&&!std::memcmp(live,&config,sizeof(config))&&config.mesh_key_count==1&&config.meshcore_key_count==2,"refused fallback preserves both configured key lists and every surviving source byte");
    host::files[primary]=recoverable;
    expect(saveLoRaDwell(60000),"save resumes after original named-key document is restored");released();assertPreserved();
  }
  // A recovered backup can contain different channel keys and public-decode
  // policy. A mesh save must apply the exact committed source before restarting
  // reception, rather than keep the newer RAM-only key list until reboot.
  {
    ArduinoJson::StaticJsonDocument<4096> document;
    expect(!deserializeJson(document,host::files[primary]),"backup-key regression baseline parses");
    auto radio=document["lora"];
    radio["decode_public"]=true;
    auto meshtastic=radio["meshtastic_keys"].to<JsonArray>();
    auto first=meshtastic.createNestedObject();first["name"]="Backup one";first["key_hex"]="000102030405060708090a0b0c0d0e0f";
    auto second=meshtastic.createNestedObject();second["name"]="Backup two";second["key_hex"]="101112131415161718191a1b1c1d1e1f";
    auto meshcore=radio["meshcore_keys"].to<JsonArray>();
    auto group=meshcore.createNestedObject();group["name"]="Backup group";group["key_hex"]="202122232425262728292a2b2c2d2e2f";
    std::string alternate;serializeJson(document,alternate);
    host::files["/lora-tunnel/config.bak"]=alternate;host::files[primary]="{bad";
    expect(!config.decode_public&&config.mesh_key_count==1&&config.meshcore_key_count==2,"live keys and public setting differ from recovered source before save");
    expect(saveMeshtasticSlot(5),"mesh save recovers alternative channel-key backup");released();
    expect(config.decode_public&&config.mesh_key_count==2&&config.meshcore_key_count==1&&config.mesh_keys[0].bytes[0]==0&&config.mesh_keys[1].bytes[0]==0x10&&config.meshcore_keys[0].bytes[0]==0x20,"committed backup public preference and both key lists immediately replace live decoder configuration");
    expect(loadConfig()&&config.decode_public&&config.mesh_key_count==2&&config.meshcore_key_count==1&&config.meshcore_keys[0].bytes[0]==0x20&&config.meshtastic_slot==5,"recovered decoder configuration matches after restart");released();
  }
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
  // A valid MeshCore-only import may retain inactive Meshtastic settings above
  // the U214's 923 MHz ceiling. Activating them must disable LoRa immediately.
  reset();host::files[primary]=R"({"schema":1,"lora":{"region":"US","enabled":true,"mode":"meshcore","meshtastic_preset":"LONG_TURBO","meshtastic_slot":52,"meshcore_profile":"US-NARROW"}})";
  expect(loadConfig()&&config.lora_enabled&&regionHardwareCompatible()&&config.frequency==927.75f,"inactive out-of-band Meshtastic settings do not prevent valid MeshCore-only reception");released();
  expect(saveLoRaMode(0),"switch from MeshCore-only to unavailable Meshtastic persists explicit choice");released();
  expect(config.lora_mode==0&&!config.lora_enabled&&!regionHardwareCompatible()&&!regionSelectionMade(),"activating out-of-band profile immediately synchronizes disabled compatibility state");
  expect(saveMeshtasticSlot(14),"compatible slot repairs imported out-of-band profile");released();
  expect(config.lora_enabled&&regionHardwareCompatible()&&regionSelectionMade()&&config.frequency==908.75f,"compatible slot immediately restores enabled state and selection flags");
  expect(loadConfig()&&config.lora_enabled&&regionHardwareCompatible()&&config.meshtastic_slot==14,"repaired profile remains enabled after restart");released();
  reset();host::files[primary]=R"({"schema":1,"lora":{"region":"US","enabled":true,"mode":"combined","meshtastic_preset":"LONG_FAST","meshcore_profile":"US-SOCAL"}})";
  expect(loadConfig()&&!config.lora_enabled&&!regionHardwareCompatible(),"unavailable imported MeshCore profile disables combined reception");released();
  expect(saveMeshCoreProfile("US-NARROW")&&config.lora_enabled&&regionHardwareCompatible()&&regionSelectionMade(),"compatible MeshCore profile restores all live compatibility flags");released();
#endif
}
void messagingSettingsChecks(){
  using namespace tunnel;
  // Public synthetic keys exercise serialization; no private/device files are read.
  const char* key16="000102030405060708090a0b0c0d0e0f";
  const char* key32="202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f";
  reset();expect(loadConfig(),"legacy config gains safe messaging defaults");released();
  expect(messaging::sameSettings(config.messages,messaging::Settings{}),"missing messaging section is public defaults without persistent TX state");
  {
    ArduinoJson::StaticJsonDocument<4096> document;
    expect(!deserializeJson(document,host::files[primary]),"messaging baseline parses");
    document["messaging"]["future_metadata"]["preserved"]=true;
    host::files[primary].clear();serializeJson(document,host::files[primary]);
  }
  const std::string maximumName(31,'N'),maximumChannel(39,'C');
  const char* values[]={maximumName.c_str(),maximumChannel.c_str(),key16,key32,"7"};
  for(int field=0;field<5;++field){expect(saveMessagingSetting(field,values[field]),"each messaging setting saves at its supported boundary");released();}
  const auto configured=config.messages;
  expect(!std::strcmp(configured.name,maximumName.c_str())&&!std::strcmp(configured.meshtastic_channel,maximumChannel.c_str())&&configured.hop_limit==7,"name channel and hop settings apply immediately");
  expect(configured.meshtastic_key_length==16&&configured.meshcore_key_length==32&&configured.meshtastic_key[15]==15&&configured.meshcore_key[31]==63,"both different key buffers retain their own bytes");
  expect(loadConfig()&&messaging::sameSettings(config.messages,configured),"all messaging settings survive reload");released();
  const auto assertPreserved=[&](){
    ArduinoJson::StaticJsonDocument<4096> document;
    expect(!deserializeJson(document,host::files[primary]),"saved messaging document parses");
    expect(document["messaging"]["meshtastic_key_hex"]==key16&&document["messaging"]["meshcore_key_hex"]==key32,"stack hex buffer copies remain distinct in saved JSON");
    expect(document["messaging"]["future_metadata"]["preserved"]==true&&document["extension"]["preserved"]=="yes","messaging saves preserve unknown root and messaging fields");
    expect(document["credentials"]["wigle_api_token"]=="old-token"&&document["credentials"]["wifi_password"]=="password","messaging saves preserve unrelated credentials");
  };
  assertPreserved();
  expect(saveLoRaRegion("US",true).sd_saved,"region settings save alongside messaging keys");released();
  expect(saveMeshtasticPreset("LONG_TURBO"),"radio settings save alongside messaging keys");released();
  expect(saveAutoUpload(0,true),"upload preferences save alongside messaging keys");released();
  expect(messaging::sameSettings(config.messages,configured),"unrelated settings retain exact live messaging configuration");assertPreserved();
  const auto before=host::files[primary];
  struct Invalid {int field;const char* value;};
  const std::string tooLongName(32,'N'),tooLongChannel(40,'C');
  const Invalid invalid[]={
    {-1,"x"},{5,"x"},{0,nullptr},{0,""},{0,"A:B"},{0,"A\n"},{0,tooLongName.c_str()},
    {1,tooLongChannel.c_str()},{1,"A\tB"},{2,"AQ=="},{2,"0"},{2,"gggggggggggggggggggggggggggggggg"},
    {3,"abc"},{3,"000102030405060708090a0b0c0d0e0f\n"},{4,"8"},{4,"-1"},{4,"03"},{4,"3 "},{4,""}
  };
  for(const auto& value:invalid){
    expect(!saveMessagingSetting(value.field,value.value),"invalid messaging editor value is rejected");released();
    expect(host::files[primary]==before&&messaging::sameSettings(config.messages,configured),"invalid messaging edit changes neither disk nor live settings");
  }
  const char* alternate[]={"Changed name","Changed channel",key32,key16,"0"};
  for(unsigned fault=0;fault<2;++fault){
    if(fault==0)host::failWritePath="config.tmp";
    else host::fileHooks().afterFlush=[](const std::string& file){if(file=="/lora-tunnel/config.tmp")host::files[file]=host::files[primary];};
    for(int field=0;field<5;++field){
      expect(!saveMessagingSetting(field,alternate[field]),"failed write or stale valid readback rejects every messaging setting");released();
      expect(host::files[primary]==before&&!host::files.count("/lora-tunnel/config.tmp")&&messaging::sameSettings(config.messages,configured),"failed messaging save preserves source and live keys and removes temporary file");
    }
    host::failWritePath.clear();host::fileHooks().afterFlush=nullptr;
  }
  for(unsigned corrupt=0;corrupt<2;++corrupt){
    if(corrupt){host::files[primary]="{bad";host::files["/lora-tunnel/config.bak"]="{bad";}
    else{host::files.erase(primary);host::files.erase("/lora-tunnel/config.bak");}
    const auto untouched=host::files;
    expect(!saveMessagingSetting(0,"Changed name"),"missing key source cannot be replaced by messaging defaults");released();
    expect(host::files==untouched&&messaging::sameSettings(config.messages,configured),"refused fallback preserves configured private-key bytes");
    host::files[primary]=before;
  }
  expect(saveMessagingSetting(2,"")&&saveMessagingSetting(3,"")&&saveMessagingSetting(1,"")&&saveMessagingSetting(4,"0"),"explicit blank saves restore public keys and AUTO channel");released();
  expect(config.messages.meshtastic_key_length==0&&config.messages.meshcore_key_length==0&&!config.messages.meshtastic_channel[0]&&config.messages.hop_limit==0,"blank public reset and zero hops apply");
  expect(std::all_of(config.messages.meshtastic_key,config.messages.meshtastic_key+32,[](uint8_t b){return b==0;})&&std::all_of(config.messages.meshcore_key,config.messages.meshcore_key+32,[](uint8_t b){return b==0;}),"public reset clears complete prior key buffers");
  const auto resetSettings=config.messages;
  expect(loadConfig()&&messaging::sameSettings(config.messages,resetSettings),"public reset survives restart");released();
  // These are complete JSON sections, including embedded-NUL and invalid-type
  // cases that a C-string-only editor cannot produce.
  const char* invalidSections[]={
    "null","[]","\"bad\"",R"({"name":""})",R"({"name":"A:B"})",R"({"name":"A\u0000B"})",
    R"({"meshtastic_channel":"A\u0000B"})",R"({"meshtastic_key_hex":null})",R"({"meshtastic_key_hex":"AQ=="})",
    R"({"meshtastic_key_hex":"000102030405060708090a0b0c0d0e0f\u0000"})",R"({"meshcore_key_hex":false})",
    R"({"meshcore_key_hex":"gggggggggggggggggggggggggggggggg"})",R"({"hop_limit":8})",R"({"hop_limit":-1})",R"({"hop_limit":1.5})",R"({"hop_limit":true})",R"({"hop_limit":"3"})"
  };
  for(const auto* section:invalidSections){
    reset();host::files[primary]=std::string(initial).substr(0,std::strlen(initial)-1)+",\"messaging\":"+section+"}";
    expect(!loadConfig()&&configLoadState==ConfigLoadState::Invalid&&!config.lora_enabled,"malformed messaging import rejects configuration instead of silently choosing public defaults");released();
    host::files["/lora-tunnel/config.bak"]=before;
    expect(loadConfig()&&configLoadState==ConfigLoadState::Backup&&messaging::sameSettings(config.messages,configured),"valid backup recovers exact messaging keys from malformed primary");released();
  }
  reset();host::files[primary]=std::string(initial).substr(0,std::strlen(initial)-1)+R"(,"messaging":{"enabled":true,"tx_enabled":true}})";
  expect(loadConfig()&&messaging::sameSettings(config.messages,messaging::Settings{}),"imported enable flags grant no persistent messaging permission or setting");released();
}
}
int main(){using namespace tunnel;
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
  storage::setOperationsForTest(&host::checkedOperations);
#endif
  reset();expect(loadConfig(),"load valid settings");released();expect(rules==nullptr&&ruleCount==0,"empty rules allocate no persistent slab");expect(!configAllocationFailed&&!rulesLoadFailed,"successful load has clear failure flags");
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
  expect(host::scratchPeak==16896,"16 KiB JSON and512-byte I/O share the existing framebuffer lease");
  {ScopedConfigDocument operation;expect(operation.document.capacity()==16384,"full accepted JSON arena capacity is retained");}
  released();
#else
  expect(host::scratchPeak==16384,"Heltec retains full heap document capacity");
#endif
  expect(saveCredential(1,"replacement-token"),"save credential");released();expect(!std::strcmp(config.wigle_token,"replacement-token"),"runtime credential updated after verified save");expect(host::files[primary].find("\"preserved\":\"yes\"")!=std::string::npos,"unknown document fields preserved");expect(host::files.count("/lora-tunnel/config.bak")>0,"atomic backup retained");
  expect(saveAutoUpload(1,true),"save service toggle");released();expect(config.auto_wardrift,"runtime service toggle applied");
  const auto region=saveLoRaRegion("US",true);released();expect(region.applied&&region.sd_saved&&region.nvs_saved,"SD-first region persistence unchanged");expect(host::preferences["lt-region:code"]=="US","NVS code readback stored");
  host::failScratch=true;const auto saved=host::files[primary];const std::string token=config.wigle_token;
  expect(!saveCredential(1,"other"),"credential allocation failure reported");released();expect(configAllocationFailed&&host::files[primary]==saved&&config.wigle_token==token,"failed allocation changes neither SD nor active credential");
  expect(!saveAutoUpload(0,true),"toggle allocation failure reported");released();expect(!config.auto_wigle,"failed toggle preserves runtime");
  const auto failed=saveLoRaRegion("EU_868",true);released();expect(!failed.applied&&!failed.sd_saved&&!failed.nvs_saved,"SD allocation failure does not fall through into NVS region change");expect(host::preferences["lt-region:code"]=="US","failed SD save preserves NVS");
  const size_t before=host::scratchCalls;const auto nvs=saveLoRaRegion("EU_868",false);expect(nvs.applied&&!nvs.sd_saved&&nvs.nvs_saved,"NVS-only region works without scratch");expect(host::scratchCalls==before,"NVS-only region allocates no JSON arena");
  expect(!loadConfig(),"load allocation failure reported");released();expect(configAllocationFailed&&!config.lora_enabled&&configLoadState==ConfigLoadState::Invalid,"failed startup remains LoRa off");
  host::failScratch=false;expect(loadConfig(),"load recovers after allocation availability");released();
  host::failWritePath="config.tmp";const auto beforeWrite=host::files[primary];expect(!saveCredential(1,"write-fails"),"temporary write failure reported");released();expect(host::files[primary]==beforeWrite&&!host::files.count("/lora-tunnel/config.tmp"),"failed temp write preserves primary and cleans temporary file");host::failWritePath.clear();
  std::string ruleText="{\"schema\":1,\"rules\":[";for(unsigned i=0;i<65;++i){if(i)ruleText+=',';ruleText+="{\"type\":\"name\",\"match\":\"Example\",\"label\":\"Demo\"}";}ruleText+="]}";host::files[ruleFile]=ruleText;
  expect(loadConfig(),"load a populated custom rule document");released();expect(rules!=nullptr&&ruleCount==64,"64-rule maximum preserved");Rule* previous=rules;
  host::failRules=true;expect(!loadConfig()&&configAllocationFailed&&rulesLoadFailed,"rule-slab allocation failure reported");released();expect(rules==previous&&ruleCount==64,"failed rule allocation preserves complete prior set");host::failRules=false;
  host::failOpenPath=ruleFile;expect(!loadConfig()&&rulesLoadFailed,"existing but unopenable rules report failure");released();expect(rules==previous&&ruleCount==64,"existing rule open failure preserves complete prior set");host::failOpenPath.clear();
  host::files[ruleFile]="{broken";expect(!loadConfig()&&rulesLoadFailed,"invalid rules are visibly rejected");released();expect(rules==previous&&ruleCount==64,"invalid replacement preserves prior complete rule set");
  host::files.erase(ruleFile);expect(loadConfig(),"missing custom rules accepted as empty");released();expect(rules==nullptr&&ruleCount==0,"missing rules release old slab");
  reset();expect(loadConfig(),"baseline for existing configuration open failure");released();
  const auto sourceBefore=host::files[primary];const std::string activeBefore=config.wigle_token;
  host::preferences["lt-region:code"]="EU_868";host::failOpenPath=primary;
  expect(!saveCredential(1,"must-not-replace"),"unopenable existing primary rejects credential save");released();
  expect(host::files[primary]==sourceBefore && config.wigle_token==activeBefore && !host::files.count("/lora-tunnel/config.tmp"),"unopenable source cannot be seeded or replaced");
  expect(!saveAutoUpload(0,true) && !config.auto_wigle,"unopenable source cannot change service preference");released();
  const auto unreadableRegion=saveLoRaRegion("US",true);
  expect(!unreadableRegion.applied && !unreadableRegion.sd_saved && !unreadableRegion.nvs_saved && host::preferences["lt-region:code"]=="EU_868","unopenable source cannot fall through into NVS region change");released();
  host::files["/lora-tunnel/config.bak"]=sourceBefore;
  expect(!loadConfig() && configLoadState==ConfigLoadState::Invalid && !config.lora_enabled,"existing source open failure does not fall back to backup or NVS radio settings");released();
  host::failOpenPath.clear();host::files[primary]="{bad";host::failOpenPath="/lora-tunnel/config.bak";
  expect(!saveCredential(1,"must-not-replace") && host::files[primary]=="{bad" && host::files["/lora-tunnel/config.bak"]==sourceBefore,"unopenable existing backup is preserved after invalid primary");released();
  host::failOpenPath.clear();
  reset();host::files["/lora-tunnel/config.bak"]=host::files[primary];host::files[primary]="{bad";expect(loadConfig()&&configLoadState==ConfigLoadState::Backup,"backup recovery preserved");released();
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
  reset();expect(loadConfig(),"Cardputer baseline for file buffer faults");released();
  const std::string original=host::files[primary],activeToken=config.wigle_token;
  for(unsigned fault=1;fault<=3;++fault) {
    host::bufferCalls=0;host::failBufferCall=fault;
    expect(!saveCredential(1,"must-not-save"),"source/temp/readback file buffer failure rejects credential save");released();
    expect(configAllocationFailed && host::files[primary]==original && config.wigle_token==activeToken,"failed buffer preserves original document and live token");
    expect(!host::files.count("/lora-tunnel/config.tmp") && host::regularFiles==0,"failed buffer closes handle and removes temporary output");
  }
  host::bufferCalls=0;host::failBufferCall=1;
  const auto rejectedRegion=saveLoRaRegion("US",true);
  expect(!rejectedRegion.applied && !rejectedRegion.sd_saved && !rejectedRegion.nvs_saved,"file buffer failure cannot commit NVS region");released();
  host::bufferCalls=0;host::failBufferCall=1;
  expect(!loadConfig() && configAllocationFailed && configLoadState==ConfigLoadState::Invalid && !config.lora_enabled,"startup file buffer failure remains visibly invalid and LoRa off");released();
  host::bufferCalls=0;host::failBufferCall=2;
  expect(!loadConfig() && configAllocationFailed && rulesLoadFailed && host::regularFiles==0,"rule file buffer failure closes file and reports rule failure");released();
  host::failBufferCall=0;expect(loadConfig(),"load recovers after file buffer failure");released();
  expect(host::peakRegularFiles<=1,"configuration uses at most one regular file handle");
#endif

  // A large accepted extension must survive every setting operation, including
  // credentials at their maximum supported length and nested unknown values.
  reset();
  const std::string large(12000,'Z');
  host::files[primary]=std::string(initial).substr(0,std::strlen(initial)-1)+",\"large\":\""+large+"\",\"extra\":[null,true,17,{\"keep\":\"quoted \\\" and slash \\\\\"}]}";
  expect(loadConfig(),"large unknown fields remain accepted at full arena capacity");released();
  const std::string maxToken(127,'T');
  expect(saveCredential(1,maxToken.c_str()),"maximum credential saves beside large unknown fields");released();
  expect(saveAutoUpload(2,true),"large document service preference saves");released();
  expect(saveLoRaRegion("US",true).sd_saved,"large document region saves");released();
  ArduinoJson::StaticJsonDocument<16384> parsed;
  expect(!deserializeJson(parsed,host::files[primary]),"large saved document parses intact");
  expect(parsed["large"].as<std::string>()==large&&parsed["credentials"]["wigle_api_token"].as<std::string>()==maxToken&&parsed["extension"]["preserved"]=="yes","large and legacy unknown fields plus credential preserved");
  expect(parsed["extra"][0].isNull()&&parsed["extra"][1]==true&&parsed["extra"][2]==17&&parsed["extra"][3]["keep"].is<const char*>(),"nested unknown values and escapes survive verified save");
  // File bytes can fit while a dense JSON array needs more than16 KiB of slots.
  // NoMemory is not permission to seed over that original or change NVS.
  reset();std::string dense=std::string(initial).substr(0,std::strlen(initial)-1)+",\"dense\":[";
  for(unsigned i=0;i<1200;++i){if(i)dense+=',';dense+="{}";}dense+="]}";
  expect(dense.size()<16384,"adversarial dense input is within the unchanged file limit");host::files[primary]=dense;
  host::preferences["lt-region:code"]="EU_868";
  const auto denseResult=saveLoRaRegion("US",true);released();
  expect(!denseResult.applied&&configAllocationFailed&&host::files[primary]==dense&&host::preferences["lt-region:code"]=="EU_868","arena exhaustion preserves original and NVS without fallback seeding");
  expect(!loadConfig()&&configAllocationFailed&&configLoadState==ConfigLoadState::Invalid,"dense import fails visibly without heap fallback");released();
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
  struct Fault {std::string* path;const char* file;const char* name;};
  const Fault faults[]={
    {&host::failReadPath,primary,"source read"},
    {&host::failClosePath,primary,"source close"},
    {&host::failStatPath,primary,"source stat"},
    {&host::failFlushPath,"/lora-tunnel/config.tmp","temporary flush"},
    {&host::failSyncPath,"/lora-tunnel/config.tmp","temporary fsync"},
    {&host::failClosePath,"/lora-tunnel/config.tmp","temporary close"},
    {&host::failReadPath,"/lora-tunnel/config.tmp","readback read"},
    {&host::failStatPath,"/lora-tunnel/config.bak","backup stat"}
  };
  for(const auto& fault:faults){
    reset();expect(loadConfig(),"fault baseline loads");released();
    const auto preserved=host::files[primary];const std::string oldToken=config.wigle_token;
    host::preferences["lt-region:code"]="EU_868";*fault.path=fault.file;
    expect(!saveCredential(1,"must-not-commit"),fault.name);released();
    expect(host::files[primary]==preserved&&config.wigle_token==oldToken&&!host::files.count("/lora-tunnel/config.tmp"),"I/O failure preserves primary/live credential and removes temp");
    expect(!saveLoRaRegion("US",true).applied&&host::preferences["lt-region:code"]=="EU_868","I/O failure cannot fall through into NVS");released();
    fault.path->clear();expect(saveCredential(1,"recovered"),"next save recovers after I/O fault");released();
    expect(host::heapScratchCalls==0&&host::scratchPeak==16896,"successful and failed saves never allocate a JSON heap arena");
  }
  reset();expect(loadConfig(),"mkdir fault baseline loads");released();const auto untouched=host::files[primary];host::failMkdir=true;
  expect(!saveCredential(1,"reject")&&host::files[primary]==untouched,"directory failure rejects save before any source mutation");released();
  host::failMkdir=false;expect(saveCredential(1,"after-mkdir"),"save recovers after directory failure");released();
  // Even an explicitly denied lease leaves the UI buffer and on-disk file intact.
  const auto safe=host::files[primary];host::failScratch=true;const auto heldCalls=host::bufferCalls;
  expect(!saveAutoUpload(0,true)&&host::files[primary]==safe&&host::bufferCalls==heldCalls,"unavailable framebuffer lease performs no SD I/O or heap fallback");released();host::failScratch=false;
#endif
  meshSettingsChecks();
  messagingSettingsChecks();
  std::cout<<"Config memory host: "<<checks<<" checks passed; full16 KiB arena, scoped lease/heap, exact rule storage and mesh/messaging-setting persistence verified.\n";
}
