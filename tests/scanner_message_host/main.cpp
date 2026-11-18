// SPDX-License-Identifier: MIT
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "lora_scan.h"
#include "mesh_decode.h"
#include "messaging_airtime.h"

constexpr unsigned RADIOLIB_SX126X_IRQ_TX_DONE=1,RADIOLIB_SX126X_IRQ_RX_DONE=2;
constexpr unsigned RADIOLIB_SX126X_IRQ_PREAMBLE_DETECTED=4,RADIOLIB_SX126X_IRQ_HEADER_VALID=16;
constexpr unsigned RADIOLIB_SX126X_IRQ_CAD_DONE=128,RADIOLIB_SX126X_IRQ_CAD_DETECTED=256;
constexpr unsigned RADIOLIB_SX126X_RX_TIMEOUT_INF=0xffffff,RADIOLIB_IRQ_PREAMBLE_DETECTED=2;
constexpr unsigned RADIOLIB_IRQ_RX_DEFAULT_FLAGS=2|16|32|64|512,RADIOLIB_IRQ_RX_DEFAULT_MASK=2;
constexpr int RADIOLIB_ERR_NONE=0,RADIOLIB_CHANNEL_FREE=-15,RADIOLIB_LORA_DETECTED=-16,pdTRUE=1;
constexpr unsigned HIGH=1,LOW=0,RADIOLIB_NC=0xffffffffU;
using TickType_t=unsigned;
#define pdMS_TO_TICKS(x) (x)
unsigned nowMs=0;
unsigned millis(){return nowMs;}
unsigned esp_random(){return 11;}
std::size_t strlcpy(char* d,const char* s,std::size_t n){const auto length=std::strlen(s);if(n){const auto copied=std::min(length,n-1);std::memcpy(d,s,copied);d[copied]=0;}return length;}
bool busAvailable=true,busHeld=false;
using SemaphoreHandle_t=void*;
int xSemaphoreTake(SemaphoreHandle_t,unsigned){if(!busAvailable||busHeld)return 0;busHeld=true;return pdTRUE;}
void xSemaphoreGive(SemaphoreHandle_t){assert(busHeld);busHeld=false;}
namespace board {
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
constexpr bool LORA_SHARED_WITH_SD=true;
constexpr float LORA_TCXO_VOLTS=3.0f;
#else
constexpr bool LORA_SHARED_WITH_SD=false;
constexpr float LORA_TCXO_VOLTS=1.8f;
#endif
constexpr bool LORA_USE_LDO=false;
constexpr unsigned FEM_CTX=5,FEM_ENABLE=2;
}
namespace hw {
bool frontend=false,present=true;unsigned ctx=HIGH,csd=LOW;
void setLoRaFrontend(bool on,bool lna=false){frontend=on;csd=on?HIGH:LOW;ctx=on&&lna?LOW:HIGH;}
bool loraFrontendPresent(){return present;}
}
struct Module {
  enum Mode {MODE_IDLE=0,MODE_RX=1,MODE_TX=2};
  struct RfSwitchMode_t {unsigned mode;unsigned values[5];};
};
#define END_OF_MODE_TABLE {255,{0,0,0,0,0}}
struct FakeRadio {
  unsigned flags=0,arms=0,tunes=0,standbys=0,reads=0,cads=0,transmits=0,finishes=0,tableInstalls=0;
  unsigned irqEnable=0,irqDio=0;
  int beginState=0,standbyState=0,armState=0,cadState=0,txState=0,finishState=0,powerState=0,readState=0,tuneState=0;
  int scanResult=RADIOLIB_CHANNEL_FREE,drive=100;
  bool raceDone=false,racePreamble=false;
  float frequency=906.875f,bandwidth=250;unsigned sf=11,cr=5,sync=0x2b,preamble=16;
  std::uint32_t airtimeUs=1000000;
  std::uint8_t packet[255]{};std::size_t length=20;
  std::vector<std::uint8_t> transmitted;
  std::vector<char> calls;
  const Module::RfSwitchMode_t* switchTable=nullptr;
  unsigned pins[5]{};
  void lockCheck(){assert(!board::LORA_SHARED_WITH_SD||busHeld);}
  void switchMode(unsigned mode){if(switchTable){for(unsigned i=0;switchTable[i].mode!=255;++i)if(switchTable[i].mode==mode){hw::ctx=switchTable[i].values[0];hw::csd=switchTable[i].values[1];break;}}}
  int standby(){lockCheck();calls.push_back('S');++standbys;switchMode(Module::MODE_IDLE);if(raceDone){flags=2;raceDone=false;}if(racePreamble){flags=4;racePreamble=false;}return standbyState;}
  int begin(float f,float bw,unsigned s,unsigned c,unsigned sw,int,unsigned pre,float,bool){lockCheck();calls.push_back('B');frequency=f;bandwidth=bw;sf=s;cr=c;sync=sw;preamble=pre;return beginState;}
  int setFrequency(float v){lockCheck();calls.push_back('F');++tunes;frequency=v;return tuneState;}
  int setBandwidth(float v){bandwidth=v;return 0;}int setSpreadingFactor(unsigned v){sf=v;return 0;}
  int setCodingRate(unsigned v){cr=v;return 0;}int setSyncWord(unsigned v){sync=v;return 0;}
  int setPreambleLength(unsigned v){preamble=v;return 0;}int explicitHeader(){return 0;}
  int setCRC(unsigned v){return v==2?0:-1;}int invertIQ(bool v){return v?-1:0;}int setDio2AsRfSwitch(bool v){return v?0:-1;}
  void setDio1Action(void(*)()){}
  void setRfSwitchTable(const unsigned* p,Module::RfSwitchMode_t* table){lockCheck();std::copy(p,p+5,pins);switchTable=table;++tableInstalls;}
  unsigned getTimeOnAir(std::size_t){lockCheck();return airtimeUs;}
  unsigned getIrqFlags(){lockCheck();return flags;}
  int startReceive(unsigned,unsigned enable,unsigned dio){lockCheck();calls.push_back('R');++arms;irqEnable=enable;irqDio=dio;flags=0;switchMode(Module::MODE_RX);return armState;}
  int startChannelScan(){lockCheck();calls.push_back('C');++cads;flags=0;switchMode(Module::MODE_RX);return cadState;}
  int getChannelScanResult(){lockCheck();return scanResult;}
  int setOutputPower(int value){lockCheck();drive=value;return powerState;}
  int startTransmit(const std::uint8_t* bytes,std::size_t size){lockCheck();calls.push_back('T');++transmits;transmitted.assign(bytes,bytes+size);flags=0;switchMode(Module::MODE_TX);return txState;}
  int finishTransmit(){lockCheck();calls.push_back('E');++finishes;flags=0;switchMode(Module::MODE_IDLE);return finishState;}
  std::size_t getPacketLength(){lockCheck();return length;}
  int readData(std::uint8_t* output,std::size_t size){lockCheck();calls.push_back('D');++reads;assert(size<=255);std::memcpy(output,packet,size);flags=0;return readState;}
};
namespace tunnel {
enum class CaptureMode {Wardriver,Recon};
struct {unsigned radio_errors=0;} counters;
SemaphoreHandle_t busMutex=nullptr;
std::atomic<bool> capturing{false};std::atomic<CaptureMode> captureMode{CaptureMode::Wardriver};
struct Fix {std::uint32_t utc_age_ms=0;char utc[24]="2026-11-17T00:00:00Z";};
Fix currentFix(){assert(!busHeld);return Fix{};}
std::uint32_t utcSeconds(const char*){return 1794873600;}
namespace messaging {
bool enabled=true,queued=false,inflight=false;
bool txAllowed=true;
unsigned fetches=0,completions=0,receives=0,ticks=0,failures=0;bool lastSuccess=false;
std::uint8_t packet[32]{};std::size_t length=32;
std::vector<std::uint8_t> received;
bool active(){return enabled;}
bool transmitAllowed(){return enabled&&txAllowed;}
bool nextFrame(std::uint32_t,const std::uint8_t*& bytes,std::size_t& size){++fetches;if(!queued||inflight||!transmitAllowed())return false;inflight=true;bytes=packet;size=length;return true;}
void transmitted(bool success,std::uint32_t){assert(!busHeld);assert(inflight);++completions;lastSuccess=success;queued=inflight=false;}
void radioFailure(const char*){assert(!busHeld);++failures;queued=inflight=false;}
void receive(const std::uint8_t* bytes,std::size_t size,std::uint32_t,std::uint32_t){assert(!busHeld);++receives;received.assign(bytes,bytes+size);}
void tick(std::uint32_t){assert(!busHeld);++ticks;}
}
namespace {
FakeRadio radio;
struct TestConfig {
  bool lna=true,lora_enabled=true;
  std::uint32_t lora_dwell_ms=30000;
  std::uint8_t lora_mode=2,sf=11,cr=5;
  std::uint16_t preamble=16;
  std::uint16_t meshtastic_slot=0;
  float frequency=906.875f,bandwidth=250;
  char region[12]="US",profile[40]="US LongFast",meshcore_profile[32]="AUTO",meshtastic_preset[20]="LONG_FAST";
  struct {char meshtastic_channel[40]{};} messages;
} config;
bool hardwareCompatible=true;
bool regionHardwareCompatible(){return hardwareCompatible;}
std::atomic<bool> radioIRQ{false},quietLatched{false};
bool radioOK=true,radioInitialized=true,radioInitAttempted=true,radioListening=false,hopDeferred=false;
std::uint32_t radioListenAt=0,maximumPacketMs=60000;
std::uint8_t radioSlot=0;
lora_scan::Snapshot radioProfiles[2];lora_scan::Status radioStatus;lora_scan::Dwell radioDwell;
enum class RadioTransition {None,Receive,Standby};RadioTransition radioPending=RadioTransition::None;
enum class ChatPhase {Off,Receive,Cad,Transmit};ChatPhase chatPhase=ChatPhase::Off;
const std::uint8_t* chatFrame=nullptr;std::size_t chatFrameLength=0;
std::uint32_t chatDeadline=0,chatRetryAt=0,chatRequestedAt=0,chatNextTxAt=0,chatAirtimeMs=0,chatBudgetAt=0,chatBudgetDuration=0;
bool chatBudgetArmed=false;
void onRadio(){radioIRQ=true;}
bool scannersConfigureLoRa();
// SCANNER_IMPLEMENTATION
}
}
unsigned checks=0;
void expect(bool value,const char* why){++checks;if(!value){std::fprintf(stderr,"FAIL: %s\n",why);std::exit(1);}}
void reset(){using namespace tunnel;
  nowMs=0;busAvailable=true;busHeld=false;hw::frontend=false;hw::present=true;hw::ctx=HIGH;hw::csd=LOW;
  radio=FakeRadio{};config=TestConfig{};radioIRQ=false;quietLatched=false;capturing=false;hardwareCompatible=true;
  radioOK=radioInitialized=radioInitAttempted=true;radioListening=hopDeferred=false;radioListenAt=0;radioSlot=0;
  radioStatus=lora_scan::Status{};radioDwell=lora_scan::Dwell{};radioPending=RadioTransition::None;
  chatPhase=ChatPhase::Off;chatFrame=nullptr;chatFrameLength=0;chatDeadline=chatRetryAt=chatRequestedAt=chatNextTxAt=chatAirtimeMs=0;chatBudgetArmed=false;
  chatBudgetAt=chatBudgetDuration=0;
  counters.radio_errors=0;
  messaging::enabled=messaging::txAllowed=true;messaging::queued=messaging::inflight=false;
  messaging::fetches=messaging::completions=messaging::receives=messaging::ticks=messaging::failures=0;messaging::lastSuccess=false;messaging::received.clear();
  for(unsigned i=0;i<255;++i)radio.packet[i]=std::uint8_t(i);
  for(unsigned i=0;i<32;++i)messaging::packet[i]=std::uint8_t(i+17);
  expect(scannersConfigureLoRa(),"fixture passive configuration succeeds");radio.calls.clear();
}
void begin(tunnel::mesh::Protocol p=tunnel::mesh::Protocol::Meshtastic){using namespace tunnel;
  expect(scannersMessagesBegin(p),"Messages obtains selected radio");expect(chatPhase==ChatPhase::Receive&&radioListening&&!radioStatus.combined,"Messages receives one locked profile");}
void queue(){using namespace tunnel;messaging::queued=true;serviceMessages();expect(chatPhase==ChatPhase::Cad&&messaging::inflight&&chatFrame,"queued frame waits in nonblocking CAD");}
void txStart(){using namespace tunnel;queue();radio.flags=RADIOLIB_SX126X_IRQ_CAD_DONE;serviceMessages();expect(chatPhase==ChatPhase::Transmit&&radio.transmits==1,"clear CAD starts nonblocking TX");}
int main(){using namespace tunnel;
  reset();begin();expect(radio.frequency==906.875f&&radio.sync==0x2b,"Meshtastic messaging uses configured frequency/sync");
  expect((radio.irqEnable&4)&&radio.irqDio==2,"RX enables preamble status while DIO remains completion-only");
  expect(!scannersMessagesBegin(mesh::Protocol::MeshCore),"second owner cannot enter Messages");
  txStart();expect(!radioListening&&messaging::completions==0&&radio.drive==0,"TX waits for completion with conservative drive");
  expect(radio.transmitted==std::vector<std::uint8_t>(messaging::packet,messaging::packet+32),"driver receives unchanged stable frame bytes");
#if !defined(LORA_TUNNEL_CARDPUTER_ADV)
  expect(radio.pins[0]==5&&radio.pins[1]==2&&hw::ctx==HIGH&&hw::csd==HIGH,"Heltec TX drives CTX high and enables FEM despite RX LNA");
#endif
  serviceMessages();expect(messaging::completions==0&&chatPhase==ChatPhase::Transmit,"no false delivery before TX_DONE");
  nowMs=100;radio.flags=RADIOLIB_SX126X_IRQ_TX_DONE;serviceMessages();
  expect(chatPhase==ChatPhase::Receive&&radioListening&&messaging::lastSuccess&&messaging::completions==1,"TX_DONE completes once and restores RX");
#if !defined(LORA_TUNNEL_CARDPUTER_ADV)
  expect(hw::ctx==LOW&&hw::csd==HIGH,"Heltec receive restores configured LNA CTX low");
#endif
  expect(!busHeld,"main callbacks execute after SPI unlock");
  serviceMessages();expect(messaging::completions==1,"old TX_DONE cannot complete a second time");

  reset();begin();txStart();nowMs=chatDeadline;serviceMessages();
  expect(messaging::completions==1&&!messaging::lastSuccess&&radio.finishes==1&&radioListening,"TX timeout aborts once and restores RX");
  reset();begin();txStart();radio.flags=1;radio.finishState=-1;serviceMessages();
  expect(messaging::completions==1&&!messaging::lastSuccess&&radio.finishes==1&&radioListening,"finishTransmit failure is cleaned once and RX is restored");
  reset();begin();queue();radio.flags=128;radio.txState=-1;serviceMessages();
  expect(messaging::completions==1&&!messaging::lastSuccess&&radioListening&&chatFrame==nullptr,"startTransmit failure releases pending frame and restores RX");
  reset();begin();queue();radio.flags=128;radio.powerState=-1;serviceMessages();
  expect(radio.transmits==0&&messaging::completions==1&&!messaging::lastSuccess&&radioListening,"power setup failure cannot transmit");
  reset();begin();queue();radio.flags=128;radio.airtimeUs=0;serviceMessages();
  expect(radio.transmits==0&&messaging::completions==1&&!messaging::lastSuccess&&radioListening&&!chatBudgetArmed,"zero-airtime driver result fails closed before TX");
  reset();begin();messaging::queued=true;messaging::txAllowed=false;serviceMessages();
  expect(radio.cads==0&&chatFrame==nullptr&&!messaging::inflight,"disabled transmission cannot acquire queued frame");
  reset();begin();queue();radio.flags=128;messaging::txAllowed=false;serviceMessages();
  expect(radio.transmits==0&&messaging::completions==1&&!messaging::lastSuccess&&chatFrame==nullptr&&radioListening,"permission revoked during CAD is checked again before TX");
  reset();begin();queue();radio.flags=128|256;radio.scanResult=RADIOLIB_LORA_DETECTED;serviceMessages();
  expect(chatFrame&&chatPhase==ChatPhase::Receive,"busy-channel fixture retains request in receive");messaging::txAllowed=false;serviceMessages();
  expect(chatFrame==nullptr&&radio.cads==1&&radio.transmits==0&&messaging::completions==1,"permission revoked during backoff releases frame without another CAD/TX");
  reset();begin();txStart();messaging::txAllowed=false;serviceMessages();
  expect(radio.finishes==1&&chatFrame==nullptr&&radioListening&&messaging::completions==1&&!messaging::lastSuccess,"permission revoked during TX aborts and restores receive");
  reset();begin();txStart();radio.flags=1;radio.armState=-1;serviceMessages();
  expect(!radioOK&&!hw::frontend&&!radioListening&&messaging::failures==1,"RX restoration failure disables radio and reports failure");

  reset();begin();queue();const auto* stable=chatFrame;radio.flags=128|256;radio.scanResult=RADIOLIB_LORA_DETECTED;serviceMessages();
  expect(chatPhase==ChatPhase::Receive&&chatFrame==stable&&messaging::completions==0&&radio.transmits==0,"busy CAD keeps frame queued and restores receive");
  const auto scans=radio.cads;nowMs=chatRetryAt-1;serviceMessages();expect(radio.cads==scans,"CAD busy backoff is honored");
  nowMs=chatRetryAt;serviceMessages();expect(chatPhase==ChatPhase::Cad&&chatFrame==stable,"backoff retries same pending frame");
  nowMs=chatDeadline;serviceMessages();expect(chatPhase==ChatPhase::Receive&&radio.transmits==0,"missing CAD_DONE times out without transmitting");
  nowMs=chatRequestedAt+20001;serviceMessages();expect(messaging::completions==1&&!messaging::lastSuccess&&chatFrame==nullptr,"repeated channel busy cannot hold inflight request forever");
  reset();begin();messaging::queued=true;radio.cadState=-1;serviceMessages();
  expect(messaging::completions==1&&!messaging::lastSuccess&&radioListening,"CAD start failure restores RX and releases request");

  reset();begin();messaging::queued=true;radio.flags=4;serviceMessages();
  expect(radio.cads==0&&messaging::fetches==0&&radioListening,"detected preamble outranks pending send");
  radio.flags=16;serviceMessages();expect(radio.cads==0,"valid receive header outranks pending send");
  radio.flags=2;serviceMessages();expect(messaging::receives==1&&radio.reads==1&&radio.cads==0,"RX_DONE is consumed before starting a send");
  expect(messaging::received.size()==20&&messaging::received[19]==19,"valid receive bytes delivered outside bus lock");
  serviceMessages();expect(chatPhase==ChatPhase::Cad,"send may proceed on next idle receive tick");
  reset();begin();radio.flags=2;radio.readState=-7;serviceMessages();
  expect(messaging::receives==0&&counters.radio_errors==1&&radioListening,"CRC/read failure is counted but never delivered to decoder");
  reset();begin();radio.flags=2;radio.length=256;serviceMessages();
  expect(messaging::receives==0&&radio.reads==0&&counters.radio_errors==1,"oversized FIFO cannot overflow stack receive buffer");
  reset();begin();messaging::queued=true;radio.raceDone=true;serviceMessages();
  expect(messaging::receives==1&&radio.reads==1&&radio.cads==0&&radioListening&&chatFrame,"packet completion racing standby is read before CAD and pending frame preserved");
  expect(radioStatus.received[0]==1&&radioStatus.received[1]==0,"race receive remains attributed to original protocol");
  const auto readAt=std::find(radio.calls.begin(),radio.calls.end(),'D');
  expect(readAt!=radio.calls.end()&&std::find(readAt,radio.calls.end(),'R')!=radio.calls.end(),"race packet is read before RX rearm");
  reset();begin();messaging::queued=true;radio.racePreamble=true;serviceMessages();
  expect(radio.cads==0&&radioListening&&chatFrame&&chatRetryAt>nowMs,"preamble racing standby backs off without starting transmit");
  reset();begin();queue();expect(scannersMessagesCancelTx()&&chatPhase==ChatPhase::Receive&&chatFrame==nullptr&&radioListening,"cancel during CAD clears scanner pointer and restores RX");

  reset();begin();txStart();const auto next=chatNextTxAt;expect(scannersMessagesCancelTx(),"cancel during TX returns to RX");
  expect(chatFrame==nullptr&&chatPhase==ChatPhase::Receive&&radioListening&&radio.finishes==1,"cancel drops scanner reference only after stopping TX");
  expect(chatNextTxAt==next,"cancel does not reset regulatory spacing");
  messaging::queued=messaging::inflight=false;expect(scannersMessagesEnd(),"Messages end restores passive configuration");
  expect(chatPhase==ChatPhase::Off&&!radioListening&&radioStatus.combined&&radioSlot==0&&radio.sync==0x2b,"end leaves configured passive profile in standby");
  expect(chatNextTxAt==next,"mode exit preserves regulatory spacing");
  begin(mesh::Protocol::MeshCore);expect(radioSlot==1&&radio.sync==0x12&&radio.bandwidth==62.5f&&radio.sf==7,"MeshCore selects its complete configured PHY");
  messaging::queued=true;serviceMessages();expect(radio.cads==1&&chatFrame==nullptr,"mode change cannot bypass preceding TX airtime spacing");
  nowMs=next;serviceMessages();expect(chatPhase==ChatPhase::Cad,"send becomes eligible once conserved spacing expires");
  messaging::queued=messaging::inflight=false;expect(scannersMessagesEnd(),"end aborts CAD and restores passive profile");
  expect(radioStatus.combined&&radioSlot==0&&radio.sync==0x2b,"ending MeshCore messaging restores previous combined Meshtastic-first capture");
  capturing=true;radioPending=RadioTransition::Receive;serviceRadioTransition();
  expect(radioListening&&radioStatus.combined&&radioSlot==0&&radio.sync==0x2b,"normal passive capture can restart after leaving Messages");

  reset();radio.tuneState=-1;expect(!scannersMessagesBegin(mesh::Protocol::MeshCore),"partial retune failure rejects Messages entry");
  expect(!radioOK&&!hw::frontend&&chatPhase==ChatPhase::Off&&!radioListening,"failed message retune fails closed without false ready status");
  radio.tuneState=0;expect(scannersConfigureLoRa()&&radioOK&&radioStatus.combined&&radioSlot==0,"explicit recovery restores configured passive profile after begin failure");
  reset();radio.armState=-1;expect(!scannersMessagesBegin(mesh::Protocol::MeshCore),"message RX rearm failure rejects entry");
  expect(!radioOK&&!hw::frontend&&!radioListening&&chatPhase==ChatPhase::Off,"failed entry RX leaves radio disabled rather than half-configured ready");
  reset();begin();txStart();radio.standbyState=-1;expect(!scannersMessagesEnd(),"failed standby refuses to declare messaging ended");
  expect(chatPhase!=ChatPhase::Off&&chatFrame!=nullptr,"stop failure retains frame ownership until a successful retry");
  radio.standbyState=0;expect(scannersMessagesEnd()&&chatPhase==ChatPhase::Off&&chatFrame==nullptr,"successful stop retry releases radio and frame reference");

  reset();nowMs=UINT32_MAX-10;begin();txStart();const auto wrapDeadline=chatDeadline;
  nowMs=5;serviceMessages();expect(chatPhase==ChatPhase::Transmit&&messaging::completions==0,"millis wrap does not prematurely expire TX");
  nowMs=wrapDeadline;serviceMessages();expect(chatPhase==ChatPhase::Receive&&messaging::completions==1&&!messaging::lastSuccess,"TX timeout remains bounded across millis wrap");
  reset();nowMs=0x80000020U;begin();txStart();expect(chatPhase==ChatPhase::Transmit,"unarmed spacing sentinel cannot block first TX after long uptime");
  reset();chatBudgetArmed=true;chatBudgetAt=10;chatBudgetDuration=1000;chatNextTxAt=1010;nowMs=0x80000020U;begin();txStart();
  expect(chatPhase==ChatPhase::Transmit&&chatBudgetAt==nowMs,"unsigned elapsed expires old debt after more than signed half-range of idle time");
  expect(messaging::dutyPercent("RU")==0&&messaging::dutyPercent("UNSET")==0&&messaging::dutyPercent(nullptr)==0,"unimplemented and unset region policies remain receive-only");
  expect(messaging::dutyPercent("EU_868")==10&&messaging::dutyPercent("TH")==10&&messaging::dutyPercent("UA_868")==1&&messaging::dutyPercent("MY_919")==1,"conservative regional duty percentages use supported fixed-channel policy");
  expect(messaging::airtimeSpacing(1001,10)==10010&&messaging::airtimeSpacing(1001,1)==100100,"airtime spacing includes complete packet occupation");
  expect(messaging::airtimeSpacing(UINT32_MAX,1)==0x7fffffffU&&messaging::airtimeSpacing(100,0)==UINT32_MAX,"airtime arithmetic saturates and rejects disabled policy");
  reset();begin();std::strcpy(config.region,"RU");messaging::queued=true;serviceMessages();
  expect(radio.cads==0&&radio.transmits==0&&messaging::completions==1&&!messaging::lastSuccess,"scanner independently rejects TX in receive-only region");

  reset();std::strcpy(config.messages.meshtastic_channel,"Test Mesh");begin();
  expect(radio.frequency==918.625f&&radioStatus.active.frequency_mhz==918.625f,"custom LongFast AUTO name independently maps to US slot67 /918.625MHz");
  expect(radioProfiles[0].frequency_mhz==906.875f&&config.frequency==906.875f,"custom message AUTO frequency never overwrites passive snapshot or saved configuration");
  expect(scannersMessagesEnd()&&radio.frequency==906.875f&&radioStatus.combined,"leaving custom channel restores original passive LongFast frequency");
  reset();std::strcpy(config.messages.meshtastic_channel,"Test Mesh");std::strcpy(config.meshtastic_preset,"LONG_TURBO");
  config.frequency=908.75f;config.bandwidth=500;config.sf=11;config.cr=8;std::strcpy(config.profile,"US LongTurbo");
  expect(scannersConfigureLoRa(),"LongTurbo fixture profile accepted");begin();
  expect(radio.frequency==909.25f&&radio.bandwidth==500&&radio.sf==11&&radio.cr==8,"custom LongTurbo AUTO name maps to slot15 while preserving all preset PHY fields");
  expect(scannersMessagesEnd()&&radio.frequency==908.75f&&radio.bandwidth==500&&radio.cr==8,"LongTurbo passive configuration survives custom chat AUTO tuning");
  reset();config.meshtastic_slot=7;config.frequency=903.625f;std::strcpy(config.messages.meshtastic_channel,"Test Mesh");
  expect(scannersConfigureLoRa(),"explicit-slot fixture accepted");begin();
  expect(radio.frequency==903.625f,"explicit frequency slot overrides custom-name AUTO hash");
  reset();config.frequency=906.123f;config.bandwidth=62.5f;config.sf=7;std::strcpy(config.meshtastic_preset,"CUSTOM");std::strcpy(config.messages.meshtastic_channel,"Test Mesh");
  expect(scannersConfigureLoRa(),"raw PHY fixture accepted");begin();
  expect(radio.frequency==906.123f&&radio.bandwidth==62.5f&&radio.sf==7,"raw custom PHY is not silently replaced by a named-preset AUTO frequency");
  reset();std::strcpy(config.messages.meshtastic_channel,"Edge923");
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
  expect(!scannersMessagesBegin(mesh::Protocol::Meshtastic)&&!radioOK&&radio.tunes==0&&!hw::frontend,"custom AUTO occupied band outside U214 hardware range rejects before tuning");
#else
  begin();expect(radio.frequency==926.125f,"Heltec high-band model accepts same US custom AUTO frequency within its range");
#endif
  reset();std::strcpy(config.region,"EU_868");config.frequency=869.525f;config.bandwidth=250;std::strcpy(config.meshtastic_preset,"LONG_TURBO");
  std::strcpy(config.messages.meshtastic_channel,"Test Mesh");expect(scannersConfigureLoRa(),"passive EU profile remains valid");radio.calls.clear();
  expect(!scannersMessagesBegin(mesh::Protocol::Meshtastic)&&radio.tunes==0&&radio.calls.empty(),"custom AUTO cannot place 500kHz preset inside 250kHz region band");
  reset();radioProfiles[0].frequency_mhz=902.05f;radioProfiles[0].bandwidth_khz=250;
  expect(!scannersMessagesBegin(mesh::Protocol::Meshtastic)&&!radioOK&&radio.tunes==0,"complete occupied bandwidth is validated even when center alone is legal");

  reset();capturing=true;expect(!scannersMessagesBegin(mesh::Protocol::Meshtastic),"active capture cannot lose its radio to Messages");
  capturing=false;quietLatched=true;expect(!scannersMessagesBegin(mesh::Protocol::Meshtastic),"quiet latch forbids messaging start");
  quietLatched=false;messaging::enabled=false;expect(!scannersMessagesBegin(mesh::Protocol::Meshtastic),"messaging state must exist before hardware starts");
  messaging::enabled=true;expect(!scannersMessagesBegin(mesh::Protocol::Unknown),"unknown protocol cannot select a radio slot");
  expect(!busHeld,"all completed operations release SPI lock");

#if defined(LORA_TUNNEL_CARDPUTER_ADV)
  reset();busAvailable=false;expect(!scannersMessagesBegin(mesh::Protocol::Meshtastic)&&radio.calls.empty(),"shared-bus contention defers begin without touching radio");
  busAvailable=true;begin();messaging::queued=true;const auto calls=radio.calls.size();busAvailable=false;serviceMessages();
  expect(radio.calls.size()==calls&&!messaging::inflight&&!chatFrame,"SD contention leaves queued frame untouched");
  busAvailable=true;txStart();radio.flags=1;busAvailable=false;serviceMessages();expect(messaging::completions==0,"TX_DONE remains pending while SD owns bus");
  expect(!scannersMessagesCancelTx()&&!scannersMessagesEnd()&&chatPhase==ChatPhase::Transmit,"cancel/end cannot claim success without radio bus");
  busAvailable=true;serviceMessages();expect(messaging::completions==1&&radioListening,"deferred TX_DONE handled when bus is free");
#endif
  std::printf("%u actual messaging radio checks passed; simulated IRQ/bus/FEM only, no over-air acceptance claim.\n",checks);
}
