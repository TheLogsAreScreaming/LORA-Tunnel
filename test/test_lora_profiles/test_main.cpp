#include <unity.h>
#include <cmath>
#include <initializer_list>
#include "lora_profiles.h"
using namespace tunnel::lora_profiles;
void setUp() {}
void tearDown() {}
void test_default_frequency_slots_match_longfast_name() {
  std::uint32_t hash=5381;
  for(const char* p="LongFast";*p;++p) hash=hash*33+static_cast<unsigned char>(*p);
  TEST_ASSERT_EQUAL_UINT32(130429955,hash);
  TEST_ASSERT_EQUAL_UINT32(25,profileCount);
  for(const auto& p:profiles) {
    const unsigned slots=static_cast<unsigned>(std::floor((p.maximum_mhz-p.minimum_mhz+0.000001)/0.25));
    TEST_ASSERT_TRUE(slots>0);
    TEST_ASSERT_EQUAL_UINT16(1+hash%slots,p.frequency_slot);
    const double center=p.minimum_mhz+.125+(hash%slots)*.25;
    TEST_ASSERT_TRUE(std::fabs(center-p.frequency_mhz)<0.000001);
    TEST_ASSERT_TRUE(p.frequency_mhz-.125>=p.minimum_mhz-.000001);
    TEST_ASSERT_TRUE(p.frequency_mhz+.125<=p.maximum_mhz+.000001);
    TEST_ASSERT_EQUAL_UINT8(11,p.sf);
    TEST_ASSERT_EQUAL_UINT8(5,p.cr);
    TEST_ASSERT_EQUAL_UINT16(16,p.preamble);
    TEST_ASSERT_TRUE(p.bandwidth_khz==250);
  }
}
void test_high_band_compatibility_and_unique_region_codes() {
  unsigned compatible=0;
  for(size_t i=0;i<profileCount;++i) {
    const auto& p=profiles[i];
    TEST_ASSERT_TRUE(find(p.code)==&p);
    TEST_ASSERT_EQUAL(p.minimum_mhz>=863 && p.maximum_mhz<=928,selectable(p));
    if(selectable(p)) ++compatible;
    for(size_t j=i+1;j<profileCount;++j) TEST_ASSERT_TRUE(std::strcmp(p.code,profiles[j].code)!=0);
  }
  TEST_ASSERT_EQUAL_UINT32(18,compatible);
  TEST_ASSERT_FALSE(selectable(*find("EU_433")));
  TEST_ASSERT_FALSE(selectable(*find("CN")));
  TEST_ASSERT_TRUE(selectable(*find("EU_868")));
  TEST_ASSERT_NULL(find("UNSET")); TEST_ASSERT_NULL(find("LORA_24"));
  TEST_ASSERT_NULL(find("us")); TEST_ASSERT_NULL(find(nullptr));
  TEST_ASSERT_TRUE(isUnset("UNSET")); TEST_ASSERT_FALSE(isUnset(nullptr));
}
void test_named_modem_interoperability_vectors() {
  struct Expected {const char* code;const char* name;double bw;unsigned sf,cr,slot;double frequency;};
  const Expected expected[]={
    {"LONG_FAST","LongFast",250,11,5,20,906.875},
    {"LONG_TURBO","LongTurbo",500,11,8,14,908.750},
    {"LONG_MODERATE","LongMod",125,11,8,6,902.6875},
    {"LONG_SLOW","LongSlow",125,12,8,27,905.3125},
    {"MEDIUM_FAST","MediumFast",250,9,5,45,913.125},
    {"MEDIUM_SLOW","MediumSlow",250,10,5,52,914.875},
    {"SHORT_FAST","ShortFast",250,7,5,68,918.875},
    {"SHORT_SLOW","ShortSlow",250,8,5,75,920.625},
    {"SHORT_TURBO","ShortTurbo",500,7,5,50,926.750}
  };
  TEST_ASSERT_EQUAL_UINT32(sizeof(expected)/sizeof(expected[0]),modemPresetCount);
  for(const auto& e:expected) {
    const auto* modem=findModemPreset(e.code);TEST_ASSERT_NOT_NULL(modem);
    TEST_ASSERT_EQUAL_STRING(e.name,modem->name);
    Profile result{};TEST_ASSERT_TRUE(makeProfile("US",e.code,0,result));
    TEST_ASSERT_TRUE(std::fabs(e.frequency-result.frequency_mhz)<0.000001);
    TEST_ASSERT_TRUE(result.bandwidth_khz==e.bw);
    TEST_ASSERT_EQUAL_UINT8(e.sf,result.sf);TEST_ASSERT_EQUAL_UINT8(e.cr,result.cr);
    TEST_ASSERT_EQUAL_UINT16(16,result.preamble);
    TEST_ASSERT_EQUAL_UINT16(e.slot,result.frequency_slot);
  }
}
void test_long_turbo_default_and_explicit_slots() {
  Profile result{};
  TEST_ASSERT_EQUAL_UINT32(26541281,channelNameHash("LongTurbo"));
  TEST_ASSERT_TRUE(makeProfile("ANZ","LONG_TURBO",0,result));
  TEST_ASSERT_EQUAL_UINT16(14,result.frequency_slot);
  TEST_ASSERT_TRUE(result.frequency_mhz==921.750);
  TEST_ASSERT_EQUAL_UINT16(26,slotCount(*find("ANZ"),*findModemPreset("LONG_TURBO")));
  TEST_ASSERT_TRUE(makeProfile("US","LONG_TURBO",1,result));
  TEST_ASSERT_TRUE(result.frequency_mhz==902.250);
  TEST_ASSERT_TRUE(makeProfile("US","LONG_TURBO",52,result));
  TEST_ASSERT_TRUE(result.frequency_mhz==927.750);
  TEST_ASSERT_TRUE(selectable(result));
  TEST_ASSERT_FALSE(makeProfile("US","LONG_TURBO",53,result));
  TEST_ASSERT_FALSE(makeProfile("ANZ","LONG_TURBO",27,result));
  TEST_ASSERT_FALSE(makeProfile("US","LONG_TURBO",65535,result));
}
void test_narrow_regions_reject_turbo_without_retuning() {
  Profile result=*find("US");
  TEST_ASSERT_EQUAL_UINT16(0,slotCount(*find("EU_868"),*findModemPreset("LONG_TURBO")));
  TEST_ASSERT_FALSE(makeProfile("EU_868","LONG_TURBO",0,result));
  TEST_ASSERT_FALSE(makeProfile("EU_868","SHORT_TURBO",0,result));
  TEST_ASSERT_EQUAL_STRING("US",result.code);TEST_ASSERT_TRUE(result.frequency_mhz==906.875);
  TEST_ASSERT_TRUE(makeProfile("EU_868","LONG_MODERATE",0,result));
  TEST_ASSERT_TRUE(std::fabs(result.frequency_mhz-869.5875)<0.000001);
  TEST_ASSERT_TRUE(makeProfile("EU_868","LONG_SLOW",0,result));
  TEST_ASSERT_TRUE(std::fabs(result.frequency_mhz-869.4625)<0.000001);
  TEST_ASSERT_FALSE(makeProfile("UNSET","LONG_FAST",0,result));
  TEST_ASSERT_FALSE(makeProfile("US","LongTurbo",0,result));
  TEST_ASSERT_FALSE(makeProfile("US","CUSTOM",0,result));
  TEST_ASSERT_NULL(findModemPreset(nullptr));TEST_ASSERT_NULL(findModemPreset("long_turbo"));
}
void test_cap_and_heltec_limits_cover_occupied_bandwidth() {
  Profile result{};
  for(const char* region:{"US","ANZ"}) {
    const unsigned lastCapSlot=!std::strcmp(region,"US")?42:16;
    TEST_ASSERT_TRUE(makeProfile(region,"LONG_TURBO",lastCapSlot,result));
    TEST_ASSERT_TRUE(result.frequency_mhz==922.750);
    TEST_ASSERT_TRUE(fitsHardware(result.frequency_mhz,result.bandwidth_khz,868,923));
    TEST_ASSERT_TRUE(makeProfile(region,"LONG_TURBO",lastCapSlot+1,result));
    TEST_ASSERT_FALSE(fitsHardware(result.frequency_mhz,result.bandwidth_khz,868,923));
    TEST_ASSERT_TRUE(fitsHardware(result.frequency_mhz,result.bandwidth_khz,863,928));
  }
  TEST_ASSERT_FALSE(fitsHardware(923.0,500,868,923));
  TEST_ASSERT_FALSE(fitsHardware(868.0,500,868,923));
  TEST_ASSERT_TRUE(makeProfile("US","SHORT_TURBO",0,result));
  TEST_ASSERT_FALSE(fitsHardware(result.frequency_mhz,result.bandwidth_khz,868,923));
  TEST_ASSERT_TRUE(selectable(result));
}
int main(int,char**) {
  UNITY_BEGIN();
  RUN_TEST(test_default_frequency_slots_match_longfast_name);
  RUN_TEST(test_high_band_compatibility_and_unique_region_codes);
  RUN_TEST(test_named_modem_interoperability_vectors);
  RUN_TEST(test_long_turbo_default_and_explicit_slots);
  RUN_TEST(test_narrow_regions_reject_turbo_without_retuning);
  RUN_TEST(test_cap_and_heltec_limits_cover_occupied_bandwidth);
  return UNITY_END();
}
