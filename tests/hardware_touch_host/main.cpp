#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>

namespace board {
constexpr uint8_t TOUCH_ADDRESS=0x2e;
constexpr uint16_t DISPLAY_WIDTH=240,DISPLAY_HEIGHT=320;
}
struct FakeWire {
  std::vector<int> bytes;
  unsigned index=0,begins=0,requests=0;
  int error=0,reported=7;
  void beginTransmission(uint8_t address) {if(address!=board::TOUCH_ADDRESS)std::abort();++begins;}
  void write(uint8_t reg) {if(reg)std::abort();}
  int endTransmission(bool stop) {if(!stop)std::abort();return error;}
  int requestFrom(uint8_t address,uint8_t count,bool stop) {
    if(address!=board::TOUCH_ADDRESS||count!=7||!stop)std::abort();++requests;return reported;
  }
  unsigned available() const {return unsigned(bytes.size())-index;}
  int read() {return index<bytes.size()?bytes[index++]:-1;}
  void report(unsigned points,unsigned event,unsigned x=0,unsigned y=0) {
    bytes={0,0,int(points),int((event<<6)|((x>>8)&15)),int(x&255),int((y>>8)&15),int(y&255)};
    index=begins=requests=0;error=0;reported=7;
  }
} Wire;
bool hasTouch=true;
namespace hw {
// TOUCH_IMPLEMENTATION
}
unsigned checks=0;
void expect(bool result,const char* reason) {++checks;if(!result){std::fprintf(stderr,"FAIL: %s\n",reason);std::exit(1);}}
int main() {
  using hw::TouchState;
  uint16_t x=42,y=43;
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
  expect(hw::readTouch(x,y)==TouchState::Unavailable,"keyboard-only Cardputer has no touch report");
  expect(x==42&&y==43,"unavailable Cardputer does not change coordinates");
  expect(!hw::touch(x,y),"legacy Cardputer touch wrapper stays false");
#else
  hasTouch=false;
  expect(hw::readTouch(x,y)==TouchState::Unavailable&&Wire.begins==0,"missing controller does not perform I2C or imply release");
  hasTouch=true;Wire.report(1,0,100,150);Wire.error=4;
  expect(hw::readTouch(x,y)==TouchState::Unavailable&&Wire.requests==0,"I2C transmission error is unavailable");
  expect(x==42&&y==43,"failed report preserves coordinates");
  Wire.report(1,0,100,150);Wire.reported=3;Wire.bytes.resize(3);
  expect(hw::readTouch(x,y)==TouchState::Unavailable&&!Wire.available(),"short I2C report is drained and unavailable");
  Wire.report(1,0,100,150);Wire.bytes.resize(6);
  expect(hw::readTouch(x,y)==TouchState::Unavailable,"missing byte after claimed length is unavailable");
  for(unsigned points=3;points<8;++points) {
    Wire.report(points,0,100,150);
    expect(hw::readTouch(x,y)==TouchState::Unavailable,"invalid point count does not imply release");
  }
  for(unsigned points=1;points<3;++points) {
    Wire.report(points,3,100,150);
    expect(hw::readTouch(x,y)==TouchState::Unavailable,"reserved event does not imply release");
  }
  Wire.report(1,0,240,150);
  expect(hw::readTouch(x,y)==TouchState::Unavailable,"out-of-bounds x is unavailable");
  Wire.report(1,2,100,320);
  expect(hw::readTouch(x,y)==TouchState::Unavailable,"out-of-bounds y is unavailable");
  expect(x==42&&y==43,"invalid coordinates are never published");
  for(unsigned event=0;event<4;++event) {
    Wire.report(0,event,4095,4095);
    expect(hw::readTouch(x,y)==TouchState::Released,"zero-point report releases regardless of stale point event or coordinates");
  }
  Wire.report(0,0);
  for(unsigned i=3;i<7;++i)Wire.bytes[i]=0xff;
  expect(hw::readTouch(x,y)==TouchState::Released,"zero-point report ignores all-FF nonexistent point record");
  expect(x==42&&y==43,"zero-point report never publishes stale coordinates");
  Wire.report(1,1,4095,4095);
  expect(hw::readTouch(x,y)==TouchState::Released,"valid up report is release without requiring meaningful coordinates");
  Wire.report(1,0,100,150);
  expect(hw::readTouch(x,y)==TouchState::Pressed&&x==100&&y==150,"valid down report publishes coordinates");
  Wire.report(1,2,239,319);
  expect(hw::readTouch(x,y)==TouchState::Pressed&&x==239&&y==319,"valid contact report accepts display edge");
  Wire.report(2,2,0,0);
  expect(hw::readTouch(x,y)==TouchState::Pressed&&x==0&&y==0,"existing first-point handling accepts two-point report");
  Wire.report(1,0,30,40);
  expect(hw::touch(x,y)&&x==30&&y==40,"legacy wrapper reports only valid pressed state");
  Wire.report(0,0);
  expect(!hw::touch(x,y),"legacy wrapper reports released as false");
  Wire.report(1,0,30,40);Wire.error=4;
  expect(!hw::touch(x,y),"legacy wrapper reports unavailable as false");
#endif
  std::printf("%u actual touch-driver checks passed. I2C reports are synthetic.\n",checks);
}
