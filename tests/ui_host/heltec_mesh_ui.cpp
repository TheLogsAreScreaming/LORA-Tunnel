#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include <cstdlib>
#include <cstdint>
std::uint32_t hostMillis=2000;
#include "../../src/ui.cpp"

// Unused startup/evidence dependencies still need symbols on MinGW. These
// placeholders are never drawn or treated as logo/Recon validation.
const uint8_t logoStart[24]={},logoEnd[1]={},vtsStart[24]={},vtsEnd[1]={};
namespace tunnel {namespace recon {const char* categoryName(Category){return "HOST FIXTURE";}}}

namespace {
unsigned assertions=0;
struct Sent {ui::Action action;int value;std::string text;};
std::vector<Sent> sent;
void callback(ui::Action action,int value,const char* text) {sent.push_back({action,value,text});}
void expect(bool ok,const char* message) {++assertions;if(!ok){std::cerr<<"FAIL: "<<message<<"\n";std::exit(1);}}
std::string quote(const std::string& text) {std::string out="\"";for(char c:text){if(c=='\\'||c=='\"')out+='\\';out+=c;}return out+'\"';}
void paint(const ui::Model& model) {
  gfx().commands.clear();fullClearNeeded=true;
  if(page==Page::Settings)settings(model);
  else if(page==Page::MeshSettings)meshSettings(model);
  else meshChoices(model);
  drawFocus(model);
}
void capture(const char* directory,const char* name,const ui::Model& model) {
  paint(model);std::ofstream out(std::string(directory)+"/"+name+".json",std::ios::binary);out<<"[";bool first=true;
  for(const auto& c:gfx().commands){if(!first)out<<",";first=false;
    out<<"{\"kind\":"<<quote(c.kind)<<",\"text\":"<<quote(c.text)<<",\"x\":"<<c.x<<",\"y\":"<<c.y<<",\"w\":"<<c.w<<",\"h\":"<<c.h<<",\"r\":"<<c.r<<",\"color\":"<<c.color<<",\"scale\":"<<c.scale<<"}";}
  out<<"]\n";expect(bool(out),"preview commands written");
}
bool screenHas(const char* text) {for(const auto& c:gfx().commands)if(c.text.find(text)!=std::string::npos)return true;return false;}
void tap(int x,int y,const ui::Model& m) {touchAction(uint16_t(x),uint16_t(y),m);paint(m);}
void press(uint8_t key,const ui::Model& m) {ui::navigation(key,m);paint(m);}
}
int main(int argc,char** argv) {
  expect(argc==2,"output directory supplied");const char* output=argv[1];
  ui::Model model;model.sd=model.region_configured=model.region_selection_made=true;
  std::strcpy(model.region,"US");std::strcpy(model.profile,"US LongFast / 906.875 MHz");model.meshtastic_slots=104;
  // Use the production page and event handlers; no display allocation, radio,
  // live storage, startup logos, or unrelated capture callbacks are simulated.
  onAction=callback;buffered=true;splashShown=true;bootAt=0;
  setPage(Page::Settings);tap(100,218,model);
  expect(page==Page::MeshSettings && sent.empty(),"Settings touch opens mesh configuration without a mode change");capture(output,"mesh-settings",model);
  tap(100,77,model);expect(page==Page::MeshChoice && meshField==ui::mesh_settings::Protocol,"protocol chooser reachable by touch");
  tap(100,155,model);expect(meshChoice==2 && sent.empty(),"touch selects combined preview without saving");capture(output,"mesh-protocol",model);
  tap(175,296,model);expect(page==Page::MeshSettings && sent.size()==1 && sent.back().action==ui::Action::SaveLoRaMode && sent.back().value==2,"explicit Save emits exactly one combined-mode action");
  model.lora_mode=2;tap(100,107,model);tap(100,116,model);
  expect(meshChoice==1 && screenHas("908.750 MHz / 500 kHz"),"LongTurbo touch preview uses preset default slot and bandwidth");capture(output,"mesh-long-turbo",model);
  tap(175,296,model);expect(sent.back().action==ui::Action::SaveMeshtasticPreset && sent.back().text=="LONG_TURBO","LongTurbo save emits stable preset code");
  std::strcpy(model.meshtastic_preset,"LONG_TURBO");std::strcpy(model.profile,"US LongTurbo / 908.750 MHz");model.meshtastic_slots=52;
  tap(100,137,model);tap(205,164,model);for(int i=0;i<4;++i)tap(145,164,model);
  expect(meshChoice==14 && screenHas("908.750 MHz / slot 14"),"slot touch editor provides increments of ten and one");capture(output,"mesh-slot",model);
  tap(175,296,model);expect(sent.back().action==ui::Action::SaveMeshtasticSlot && sent.back().value==14,"slot saved explicitly");model.meshtastic_slot=14;
  const size_t beforeCancel=sent.size();tap(100,137,model);tap(145,164,model);tap(60,296,model);
  expect(page==Page::MeshSettings && sent.size()==beforeCancel && model.meshtastic_slot==14,"Cancel discards preview and preserves existing slot");
  tap(100,167,model);expect(ui::mesh_settings::count(meshField,model)==3,"Heltec exposes both compatible US MeshCore profiles plus AUTO");
  tap(100,155,model);capture(output,"mesh-meshcore",model);tap(175,296,model);
  expect(sent.back().action==ui::Action::SaveMeshCoreProfile && sent.back().text=="US-SOCAL","Heltec saves region-specific MeshCore selection");
  // Actual two-button navigation: next to the dwell row, select, next-page,
  // select its sole option, then explicitly focus and activate Save.
  setPage(Page::MeshSettings);focusIndex=-1;
  for(int i=0;i<5;++i)press(hw::Next,model);press(hw::Select,model);
  expect(page==Page::MeshChoice && meshField==ui::mesh_settings::Dwell,"physical buttons reach dwell chooser");
  for(int i=0;i<5;++i)press(hw::Next,model);press(hw::Select,model);
  expect(meshChoice==4 && screenHas("600 seconds"),"physical buttons reach second choice page");capture(output,"mesh-dwell",model);
  for(int i=0;i<4;++i)press(hw::Next,model);press(hw::Select,model);
  expect(sent.back().action==ui::Action::SaveLoRaDwell && sent.back().value==600000,"physical buttons activate explicit dwell save");
  tap(100,227,model);tap(100,78,model);capture(output,"mesh-public-decoding",model);tap(175,296,model);
  expect(sent.back().action==ui::Action::SavePublicDecode && sent.back().value==0,"public decoding toggle is independent of protocol");
  tap(100,107,model);tap(205,252,model);expect(meshChoice==4,"preset next page selects first local preview only");
  const size_t beforeBack=sent.size();press(hw::Back,model);
  expect(page==Page::MeshSettings && focusIndex==1 && sent.size()==beforeBack,"physical Back cancels and restores row focus");press(hw::Back,model);
  expect(page==Page::Settings && focusIndex==3,"physical Back returns to original Settings entry");
  std::strcpy(model.region,"EU_868");model.meshtastic_slot=0;model.meshtastic_slots=1;setPage(Page::MeshChoice);meshField=ui::mesh_settings::Preset;meshChoice=1;
  const size_t rejected=sent.size();tap(175,296,model);
  expect(sent.size()==rejected && screenHas("Does not fit region"),"EU868 cannot save LongTurbo's 500 kHz bandwidth");capture(output,"mesh-incompatible-region",model);
  std::strcpy(model.region,"US");model.meshtastic_slots=52;
  for(unsigned guard=0;guard<4;++guard) {
    model.running=guard==0;model.upload_busy=guard==1;model.sd=guard!=2;model.region_configured=guard!=3;
    setPage(Page::MeshChoice);meshField=ui::mesh_settings::Protocol;meshChoice=1;const size_t old=sent.size();tap(175,296,model);
    expect(sent.size()==old && page==Page::MeshChoice && screenHas(ui::mesh_settings::blockedReason(model)),"busy capture/upload, missing storage and unset region block save visibly");
  }
  model.running=model.upload_busy=false;model.sd=model.region_configured=true;
  std::strcpy(model.meshtastic_preset,"CUSTOM");model.meshtastic_slots=0;setPage(Page::MeshSettings);paint(model);
  expect(screenHas("Custom / SD"),"custom numeric SD settings remain visibly custom");capture(output,"mesh-custom",model);
  for(Page guarded:{Page::MeshSettings,Page::MeshChoice}) {setPage(guarded);expect(!ui::allowsBackgroundUpload()&&!ui::allowsUploadJobPolling(),"staged mesh settings suppress automatic upload work");}
  std::strcpy(model.meshtastic_preset,"LONG_TURBO");model.meshtastic_slots=52;
  std::memset(model.profile,'P',sizeof(model.profile)-1);
  for(const char* region:{"US","EU_868","ANZ","JP","UNSET"}) {
    std::strcpy(model.region,region);setPage(Page::MeshSettings);paint(model);
    for(meshField=0;meshField<ui::mesh_settings::FieldCount;++meshField) {
      setPage(Page::MeshChoice);
      for(meshChoice=0;meshChoice<ui::mesh_settings::count(meshField,model);++meshChoice) {
        Rect targets[MAX_TARGETS];const size_t count=focusTargets(model,targets);
        for(size_t i=0;i<count;++i) {focusVisible=true;focusIndex=int(i);paint(model);++assertions;}
      }
    }
  }
  expect(!hostAllocationCount,"mesh page preview/actions require no new framebuffer allocation");
  std::cout<<"Heltec mesh UI: "<<assertions<<" checks passed; all draw and button-focus bounds checked. Synthetic previews only.\n";
}
