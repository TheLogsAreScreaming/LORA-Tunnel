// Actual production Preferences adapter, with a fault-injectable host backend.
#include "messaging.h"
#include <Preferences.h>
#include <cstdio>
namespace nvs_fixture {
std::map<std::string,std::vector<std::uint8_t>> values;
bool failOpen=false,shortWrite=false,discardWrite=false,corruptRead=false,shortRead=false,wrongLength=false;
unsigned opens=0,closes=0;
}
static unsigned checks=0,failures=0;
#define CHECK(x) do{++checks;if(!(x)){++failures;std::fprintf(stderr,"storage adapter FAIL %d: %s\n",__LINE__,#x);}}while(0)
int main(){
  using namespace nvs_fixture;using tunnel::messaging::Load;
  const auto& s=tunnel::messaging::platformStorage();std::uint8_t value[84]{},copy[84]{};for(unsigned i=0;i<84;++i)value[i]=std::uint8_t(i+1);
  CHECK(s.load("identity-v1",copy,sizeof(copy))==Load::Missing);CHECK(s.save("identity-v1",value,sizeof(value)));CHECK(s.load("identity-v1",copy,sizeof(copy))==Load::Ok);CHECK(!std::memcmp(value,copy,sizeof(value)));
  failOpen=true;CHECK(s.load("identity-v1",copy,sizeof(copy))==Load::Invalid);CHECK(!s.save("identity-v1",value,sizeof(value)));failOpen=false;
  shortWrite=true;CHECK(!s.save("identity-v1",value,sizeof(value)));shortWrite=false;
  discardWrite=true;value[0]^=1;CHECK(!s.save("identity-v1",value,sizeof(value)));discardWrite=false;
  corruptRead=true;CHECK(!s.save("identity-v1",value,sizeof(value)));corruptRead=false;
  shortRead=true;CHECK(s.load("identity-v1",copy,sizeof(copy))==Load::Invalid);CHECK(!s.save("identity-v1",value,sizeof(value)));shortRead=false;
  wrongLength=true;CHECK(s.load("identity-v1",copy,sizeof(copy))==Load::Invalid);CHECK(!s.save("identity-v1",value,sizeof(value)));wrongLength=false;
  CHECK(!s.save("too-large",value,1025));CHECK(values.count("too-large")==0);CHECK(s.random()==0x12345678);void* memory=s.allocate(3464);CHECK(memory!=nullptr);s.release(memory);
  CHECK(opens==closes+2); // The two failed begin() calls do not require end().
  std::printf("Messaging production storage adapter: %u checks, %u failures\n",checks,failures);return failures?1:0;
}
