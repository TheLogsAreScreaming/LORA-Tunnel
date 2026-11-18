#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include <vector>
#include "app_types.h"

// These are the pinned SX126x raw IRQ bits and PhysicalLayer bit indexes.
// Production keeps normalized masks at startReceive and raw masks on reads.
constexpr unsigned RADIOLIB_SX126X_IRQ_RX_DONE=2;
constexpr unsigned RADIOLIB_SX126X_IRQ_PREAMBLE_DETECTED=4;
constexpr unsigned RADIOLIB_SX126X_IRQ_HEADER_VALID=16;
constexpr unsigned RADIOLIB_SX126X_RX_TIMEOUT_INF=0xffffff;
constexpr unsigned RADIOLIB_IRQ_PREAMBLE_DETECTED=2;
constexpr unsigned RADIOLIB_IRQ_RX_DEFAULT_FLAGS=2|16|32|64|512;
constexpr unsigned RADIOLIB_IRQ_RX_DEFAULT_MASK=2;
constexpr int RADIOLIB_ERR_NONE=0,pdTRUE=1;
using TickType_t=unsigned;
#define pdMS_TO_TICKS(x) (x)
unsigned nowMs=0;
unsigned millis(){return nowMs;}
std::size_t strlcpy(char* destination,const char* source,std::size_t size){
  const auto length=std::strlen(source);
  if(size){const auto count=std::min(length,size-1);std::memcpy(destination,source,count);destination[count]=0;}
  return length;
}
bool busAvailable=true,busHeld=false;
int xSemaphoreTake(SemaphoreHandle_t,unsigned){if(!busAvailable || busHeld)return 0;busHeld=true;return pdTRUE;}
void xSemaphoreGive(SemaphoreHandle_t){busHeld=false;}
namespace board {
constexpr bool LORA_SHARED_WITH_SD=true,LORA_USE_LDO=false;
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
constexpr float LORA_TCXO_VOLTS=3.0f;
#else
constexpr float LORA_TCXO_VOLTS=1.8f;
#endif
}
namespace hw {
bool frontend=false,present=true;
void setLoRaFrontend(bool value,bool=false){frontend=value;}
bool loraFrontendPresent(){return present;}
}
struct FakeRadio {
  unsigned flags=0,armCount=0,tunes=0,standbys=0,readCount=0,irqEnable=0,irqDio=0,begins=0;
  std::vector<char> calls;
  bool raceDone=false,racePreamble=false,failTune=false,failArm=false,badCrc=false;
  float frequency=906.875,bandwidth=250;
  unsigned sf=11,cr=5,sync=0x2b,preamble=16;
  std::uint8_t packet[255]{};
  std::size_t length=20;
  int standby(){calls.push_back('S');++standbys;if(raceDone){flags=2;raceDone=false;}else if(racePreamble){flags=4;racePreamble=false;}return 0;}
  int begin(float f,float bw,unsigned s,unsigned c,unsigned sw,int,unsigned pre,float,bool){calls.push_back('B');++begins;frequency=f;bandwidth=bw;sf=s;cr=c;sync=sw;preamble=pre;return 0;}
  int setFrequency(float value){calls.push_back('F');++tunes;if(failTune)return -1;frequency=value;return 0;}
  int setBandwidth(float value){bandwidth=value;return 0;}
  int setSpreadingFactor(unsigned value){sf=value;return 0;}
  int setCodingRate(unsigned value){cr=value;return 0;}
  int setSyncWord(unsigned value){sync=value;return 0;}
  int setPreambleLength(unsigned value){preamble=value;return 0;}
  int explicitHeader(){return 0;}int setCRC(unsigned value){return value==2?0:-1;}
  int invertIQ(bool value){return value?-1:0;}int setDio2AsRfSwitch(bool value){return value?0:-1;}
  void setDio1Action(void(*)()){}
  unsigned getTimeOnAir(unsigned){return 1000000;}
  unsigned getIrqFlags(){return flags;}
  int startReceive(unsigned,unsigned enable,unsigned dio){calls.push_back('A');++armCount;irqEnable=enable;irqDio=dio;flags=0;return failArm?-1:0;}
  std::size_t getPacketLength(){return length;}
  int readData(std::uint8_t* output,std::size_t count){calls.push_back('R');++readCount;std::memcpy(output,packet,count);flags=0;return badCrc?-1:0;}
  float getRSSI(){return -73;}float getSNR(){return 6.5;}
};
namespace tunnel {
Counters counters;
SemaphoreHandle_t busMutex=nullptr;
std::atomic<bool> capturing{true};
std::atomic<CaptureMode> captureMode{CaptureMode::Wardriver};
std::vector<CaptureObservation> received;
void submit(CaptureObservation& event){received.push_back(event);}
namespace {
FakeRadio radio;
struct TestConfig {
  bool lna=true,lora_enabled=true;
  std::uint32_t lora_dwell_ms=30000;
  std::uint8_t lora_mode=2,sf=11,cr=5;
  std::uint16_t preamble=16;
  float frequency=906.875f,bandwidth=250;
  char region[12]="US",profile[40]="US LongFast",meshcore_profile[32]="AUTO";
} config;
std::atomic<bool> radioIRQ{false};
std::atomic<bool> quietLatched{false};
bool radioInitAttempted=false,hardwareCompatible=true;
bool regionHardwareCompatible(){return hardwareCompatible;}
void onRadio(){radioIRQ=true;}
bool radioOK=true,radioInitialized=true,radioListening=true,hopDeferred=false;
std::uint32_t radioListenAt=0,maximumPacketMs=4000;
std::uint8_t radioSlot=0;
constexpr std::size_t LORA_CAPTURE_MAX=255;
lora_scan::Snapshot radioProfiles[2];
lora_scan::Status radioStatus;
lora_scan::Dwell radioDwell;
enum class RadioTransition {None,Receive,Standby};
RadioTransition radioPending=RadioTransition::None;
// SCANNER_IMPLEMENTATION
}
}
unsigned checks=0;
void expect(bool value,const char* reason){++checks;if(!value){std::fprintf(stderr,"FAIL: %s\n",reason);std::exit(1);}}
void reset(){
  using namespace tunnel;
  nowMs=0;busAvailable=true;busHeld=false;hw::present=true;hw::frontend=true;
  config=TestConfig{};quietLatched=false;radioInitAttempted=false;hardwareCompatible=true;
  radio=FakeRadio{};radioIRQ=false;radioOK=radioInitialized=radioListening=true;hopDeferred=false;
  capturing=true;captureMode=CaptureMode::Wardriver;radioPending=RadioTransition::None;
  radioListenAt=0;radioSlot=0;maximumPacketMs=4000;received.clear();
  counters.radio_errors=0;counters.malformed=0;
  radioProfiles[0]=lora_scan::Snapshot{};auto& p=radioProfiles[0];
  p.frequency_mhz=906.875;p.bandwidth_khz=250;p.sf=11;p.cr=5;p.sync_word=0x2b;p.protocol=1;p.preamble_symbols=16;
  std::strcpy(p.name,"US LongFast");
  radioProfiles[1]=lora_scan::snapshot(*lora_scan::meshCoreProfile("US"));
  radioStatus=lora_scan::Status{};radioStatus.active=p;radioStatus.combined=true;radioStatus.meshcore_available=true;
  radioDwell.reset(nowMs,30000);
  for(unsigned i=0;i<255;++i)radio.packet[i]=static_cast<std::uint8_t>(i+1);
}
void choosePreset(const char* name,std::uint16_t slot=0){
  using namespace tunnel;lora_profiles::Profile profile{};
  expect(lora_profiles::makeProfile(config.region,name,slot,profile) && lora_profiles::selectable(profile),"fixture preset is region and board compatible");
  config.frequency=float(profile.frequency_mhz);config.bandwidth=float(profile.bandwidth_khz);
  config.sf=profile.sf;config.cr=profile.cr;config.preamble=profile.preamble;
  std::snprintf(config.profile,sizeof(config.profile),"%s %s",config.region,lora_profiles::findModemPreset(name)->name);
}
int main(){using namespace tunnel;
  reset();nowMs=29999;serviceRadioHop();expect(radioSlot==0 && radio.tunes==0,"no retune before dwell expires");
  nowMs=30000;busAvailable=false;serviceRadioHop();expect(radioSlot==0 && radio.tunes==0,"SD contention defers retune");
  busAvailable=true;serviceRadioHop();expect(radioSlot==1 && radioStatus.switches==1,"due idle profile advances to MeshCore");
  expect(radio.sync==0x12 && radio.bandwidth==62.5f && radio.sf==7 && radio.preamble==32,"complete MeshCore PHY settings applied");
  expect(radioStatus.listen_ms[0]==30000 && radioStatus.listen_ms[1]==0,"retune accounts old listening interval to Meshtastic");
  expect((radio.irqEnable&4) && radio.irqDio==2,"preamble status enabled but DIO remains completion-only");
  nowMs=60000;serviceRadioHop();expect(radioSlot==0 && radioStatus.listen_ms[1]==30000,"second dwell returns to Meshtastic with separate listening time");
  expect(!busHeld,"SPI bus released after retune");

  reset();nowMs=30000;radio.flags=RADIOLIB_SX126X_IRQ_PREAMBLE_DETECTED;serviceRadioHop();
  expect(radioSlot==0 && radioStatus.hop_deferrals==1,"preamble extends dwell");
  nowMs=33999;serviceRadioHop();expect(radio.tunes==0 && radioStatus.hop_deferrals==1,"in-flight extension is counted once");
  nowMs=34000;serviceRadioHop();expect(radioSlot==1 && radioStatus.hop_timeouts==1,"stuck preamble cannot pin receiver indefinitely");

  reset();nowMs=30000;radio.flags=RADIOLIB_SX126X_IRQ_RX_DONE;serviceRadioHop();
  expect(radioIRQ && radio.tunes==0,"complete FIFO takes priority even before ISR flag arrives");
  serviceLoRa();serviceRadioHop();
  expect(received.size()==1 && radioSlot==1,"completed packet logged before profile advance");
  expect(received[0].radio.protocol==1 && received[0].radio.frequency_mhz==906.875f &&
      received[0].radio.sync_word==0x2b,"packet retains old profile after retune");
  expect(received[0].raw[0]==1 && received[0].raw[19]==20 && received[0].rssi==-73 && received[0].snr==6.5f,"packet raw bytes and radio measurements preserved");
  expect(radioStatus.received[0]==1 && radioStatus.received[1]==0,"capture counted against receiving protocol");

  reset();nowMs=30000;radio.raceDone=true;serviceRadioHop();
  expect(received.size()==1 && radioSlot==1 && received[0].radio.protocol==1,"completion racing standby is read before new settings");
  expect(radio.armCount==1,"race FIFO read does not briefly rearm old profile");
  reset();nowMs=30000;radio.racePreamble=true;serviceRadioHop();
  expect(radioSlot==1 && radioStatus.hop_interruptions==1,"new preamble racing standby is explicitly counted");
  reset();nowMs=30000;radio.failTune=true;serviceRadioHop();
  expect(!radioOK && !radioListening && !hw::frontend && counters.radio_errors==1,"retune failure disables RX and records error");
  reset();nowMs=30000;radio.failArm=true;serviceRadioHop();
  expect(!radioOK && !radioListening && !hw::frontend && counters.radio_errors==1,"rearm failure cannot be reported as active listening");
  reset();nowMs=30000;radio.flags=2;radioIRQ=true;radio.badCrc=true;serviceLoRa();
  expect(received.empty() && counters.radio_errors==1 && radioListening,"CRC failure counted without accepted packet, receive rearmed");

  reset();radioStatus.combined=false;radioSlot=1;radioStatus.active=radioProfiles[1];
  nowMs=123;radio.flags=2;radioIRQ=true;serviceLoRa();
  expect(received.size()==1 && radioStatus.received[1]==1 && radioStatus.listen_ms[1]==123,"MeshCore-only counts and metadata use slot one");
  expect(received[0].radio.protocol==2 && received[0].radio.sync_word==0x12,"MeshCore-only packets use their captured protocol");
  nowMs=60000;serviceRadioHop();expect(radio.tunes==0,"locked profile never hops");
  radioPending=RadioTransition::Standby;serviceRadioTransition();
  expect(!radioListening && !hw::frontend,"stop transition ceases listening and frontend");
  expect(!busHeld,"all exercised paths release SPI ownership");

  // Rejected occupied bands never begin, tune, or mutate the current radio.
  for(bool initialize:{false,true}) {
    reset();auto invalid=radioProfiles[0];
    invalid.frequency_mhz=902.05f; // Center is valid; lower occupied edge is not.
    expect(!applyRadioProfile(invalid,initialize) && radio.calls.empty(),"region occupied-band rejection occurs before all driver access");
    invalid.frequency_mhz=float(lora_profiles::hardwareMaximum-0.1);invalid.bandwidth_khz=500;
    expect(!applyRadioProfile(invalid,initialize) && radio.calls.empty(),"board occupied-band rejection occurs before all driver access");
    std::strcpy(config.region,"UNSET");
    expect(!applyRadioProfile(radioProfiles[0],initialize) && radio.calls.empty(),"unset region cannot initialize or retune a receive profile");
    std::strcpy(config.region,"CN");invalid.frequency_mhz=478.875f;invalid.bandwidth_khz=250;
    expect(!applyRadioProfile(invalid,initialize) && radio.calls.empty(),"unsupported low-band region cannot reach the high-band radio driver");
    expect(radio.frequency==906.875f && radio.bandwidth==250 && radio.cr==5,"rejected profile never silently changes previous PHY settings");
  }
  reset();radioProfiles[1].frequency_mhz=902.05f;radioProfiles[1].bandwidth_khz=250;nowMs=30000;serviceRadioHop();
  expect(!radioOK && !radioListening && !hw::frontend && counters.radio_errors==1,"invalid hop target disables RX and records exactly one error");
  expect(radio.tunes==0 && radio.armCount==0 && radioSlot==0 && radioStatus.switches==0,"rejected hop neither tunes, rearms, advances slot nor reports a successful switch");
  expect(radioStatus.active.frequency_mhz==906.875f && !busHeld,"failed retune preserves last active metadata and releases the shared bus");

  // Snapshots use float MHz. Both valid edge presets round slightly upward;
  // tolerate representation noise while rejecting a real 1 kHz band overrun.
  for(const char* region:{"EU_868","RU"}) {
    for(bool initialize:{false,true}) {
      reset();std::strcpy(config.region,region);choosePreset("LONG_FAST");
      auto edge=radioProfiles[0];edge.frequency_mhz=config.frequency;edge.bandwidth_khz=config.bandwidth;
      expect(applyRadioProfile(edge,initialize),"EU868 and RU LongFast edge profiles survive float snapshot rounding");
      expect(radio.frequency==config.frequency && radio.bandwidth==250,"accepted edge profile retains exact configured float center and bandwidth");
      radio.calls.clear();edge.frequency_mhz=config.frequency+0.001f;
      expect(!applyRadioProfile(edge,initialize) && radio.calls.empty(),"float tolerance never admits a genuine upper occupied-band violation");
      const auto* selectedRegion=lora_profiles::find(region);
      edge.frequency_mhz=float(selectedRegion->minimum_mhz+edge.bandwidth_khz/2000.0-0.001);
      expect(!applyRadioProfile(edge,initialize) && radio.calls.empty(),"float tolerance never admits a genuine lower occupied-band violation");
    }
  }

  // Capture must stop before a named preset reconfiguration. Existing saved
  // observations keep their own LongFast snapshot throughout this operation.
  reset();nowMs=100;radio.flags=2;radioIRQ=true;serviceLoRa();
  expect(received.size()==1 && received[0].radio.bandwidth_khz==250 && received[0].radio.cr==5,"baseline LongFast packet carries its original PHY snapshot");
  choosePreset("LONG_TURBO");radio.calls.clear();
  expect(!scannersConfigureLoRa() && radio.calls.empty() && radioProfiles[0].bandwidth_khz==250,"active capture rejects preset reconfiguration before changing snapshot or hardware");
  capturing=false;radioPending=RadioTransition::Standby;serviceRadioTransition();radio.calls.clear();
  quietLatched=true;expect(!scannersConfigureLoRa() && radio.calls.empty(),"quiet state rejects reconfiguration without driver access");quietLatched=false;
  expect(scannersConfigureLoRa(),"stopped receiver accepts LongFast to LongTurbo reconfiguration");
  expect(radio.calls.size()==2 && radio.calls[0]=='S' && radio.calls[1]=='B',"reconfiguration puts initialized radio in standby before applying the new modem");
  expect(radio.frequency==908.75f && radio.bandwidth==500 && radio.sf==11 && radio.cr==8 && radio.sync==0x2b && radio.preamble==16,"LongTurbo initialization applies frequency, bandwidth, spreading, coding, sync and preamble together");
  expect(!radioListening && !hw::frontend && radioStatus.active.frequency_mhz==908.75f && radioStatus.active.bandwidth_khz==500,"configuration updates active metadata while leaving capture stopped");
  expect(received[0].radio.frequency_mhz==906.875f && received[0].radio.bandwidth_khz==250 && received[0].radio.cr==5 && !std::strcmp(received[0].radio.name,"US LongFast"),"queued LongFast observation is not relabeled after LongTurbo selection");
  capturing=true;radioPending=RadioTransition::Receive;serviceRadioTransition();
  expect(radioListening && hw::frontend && radio.calls.back()=='A',"explicit capture restart arms the configured LongTurbo receiver");
  nowMs=200;radio.flags=2;radioIRQ=true;serviceLoRa();
  expect(received.size()==2 && received[1].radio.protocol==1 && received[1].radio.frequency_mhz==908.75f && received[1].radio.bandwidth_khz==500 && received[1].radio.sf==11 && received[1].radio.cr==8 && received[1].radio.preamble_symbols==16 && received[1].radio.sync_word==0x2b,"LongTurbo packet preserves every modulation attribute needed for decoding and export");
  expect(!std::strcmp(received[1].radio.name,"US LongTurbo") && received[1].raw[0]==1 && received[1].raw[19]==20,"LongTurbo packet keeps its preset label and unchanged raw payload");
  nowMs=30100;radio.raceDone=true;radio.calls.clear();serviceRadioHop();
  const auto read=std::find(radio.calls.begin(),radio.calls.end(),'R'),tune=std::find(radio.calls.begin(),radio.calls.end(),'F'),arm=std::find(radio.calls.begin(),radio.calls.end(),'A');
  expect(read!=radio.calls.end() && tune!=radio.calls.end() && arm!=radio.calls.end() && read<tune && tune<arm,"racing LongTurbo completion is read before MeshCore tuning and RX rearm");
  expect(received.size()==3 && received[2].radio.bandwidth_khz==500 && received[2].radio.cr==8 && received[2].radio.sync_word==0x2b && radioSlot==1 && radio.sync==0x12,"completion racing the hop retains LongTurbo rather than the following MeshCore profile");
  nowMs=60100;serviceRadioHop();
  expect(radioSlot==0 && radio.frequency==908.75f && radio.bandwidth==500 && radio.cr==8 && radio.sync==0x2b,"combined rotation returns to selected LongTurbo rather than legacy LongFast");
  expect(!busHeld,"new guard and reconfiguration paths release shared bus ownership");
  std::printf("%u actual radio transition checks passed; synthetic driver only, no RF acceptance claim.\n",checks);
}
