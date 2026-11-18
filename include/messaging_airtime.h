#pragma once
#include <cstdint>
#include <cstring>
#include <initializer_list>
namespace tunnel { namespace messaging {
// Conservative fixed-channel limits derived from the pinned Meshtastic region
// table. Unknown regions and RU (requires additional LBT rules) stay RX-only.
inline unsigned dutyPercent(const char* region) {
  if(!region)return 0;
  if(!std::strcmp(region,"EU_868")||!std::strcmp(region,"TH"))return 10;
  if(!std::strcmp(region,"UA_868")||!std::strcmp(region,"MY_919"))return 1;
  for(const auto* code:{"US","ANZ","JP","KR","TW","IN","NZ_865","SG_923","PH_868","PH_915","KZ_863","NP_865","BR_902"})
    if(!std::strcmp(region,code))return 100;
  return 0;
}
inline std::uint32_t airtimeSpacing(std::uint32_t airtimeMs,unsigned duty) {
  if(!duty||duty>100)return UINT32_MAX;
  const std::uint64_t spacing=(std::uint64_t(airtimeMs)*100+duty-1)/duty;
  return spacing>0x7fffffffU?0x7fffffffU:std::uint32_t(spacing);
}
} }
