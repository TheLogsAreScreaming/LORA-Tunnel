#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cmath>

namespace tunnel { namespace lora_profiles {
// Original receive-profile data derived from Meshtastic's region definitions,
// LongFast parameters and default-name frequency calculation, inspected 2026-11-01:
// https://github.com/meshtastic/firmware/blob/6d41e279f1f51bd59f687b9d441c1bf47b1594fc/src/mesh/RadioInterface.cpp
// https://github.com/meshtastic/firmware/blob/6d41e279f1f51bd59f687b9d441c1bf47b1594fc/src/mesh/MeshRadio.h
// Slot = uint32 DJB2("LongFast") % floor((end-start)/0.250); center = start+.125+slot*.250.
// No upstream implementation is included. A renamed/custom mesh channel may use another slot.
// The target is Heltec's 863-928 MHz variant; 433 and 470-510 MHz are separate products:
// https://heltec.org/project/v4-r8-ex/ . No transmit settings or paths are introduced.
struct Profile {
  const char* code;
  const char* label;
  double frequency_mhz, bandwidth_khz, minimum_mhz, maximum_mhz;
  std::uint8_t sf, cr;
  std::uint16_t preamble, frequency_slot;
  bool high_band_compatible;
};
constexpr Profile profiles[] = {
  {"US", "US / Canada", 906.875,250,902,928,11,5,16,20,true},
  {"EU_868", "Europe 868",869.525,250,869.4,869.65,11,5,16,1,true},
  {"ANZ", "Australia / NZ 915",919.875,250,915,928,11,5,16,20,true},
  {"CN", "China 470",478.875,250,470,510,11,5,16,36,false},
  {"JP", "Japan",923.375,250,920.5,923.5,11,5,16,12,true},
  {"KR", "Korea",922.875,250,920,923,11,5,16,12,true},
  {"TW", "Taiwan",923.875,250,920,925,11,5,16,16,true},
  {"RU", "Russia",869.075,250,868.7,869.2,11,5,16,2,true},
  {"IN", "India",865.875,250,865,867,11,5,16,4,true},
  {"NZ_865", "New Zealand 865",864.875,250,864,868,11,5,16,4,true},
  {"TH", "Thailand",923.875,250,920,925,11,5,16,16,true},
  {"UA_868", "Ukraine 868",868.375,250,868,868.6,11,5,16,2,true},
  {"MY_919", "Malaysia 919",922.875,250,919,924,11,5,16,16,true},
  {"SG_923", "Singapore 923",917.875,250,917,925,11,5,16,4,true},
  {"PH_868", "Philippines 868",868.125,250,868,869.4,11,5,16,1,true},
  {"PH_915", "Philippines 915",917.875,250,915,918,11,5,16,12,true},
  {"KZ_863", "Kazakhstan 863",866.875,250,863,868,11,5,16,16,true},
  {"NP_865", "Nepal 865",867.875,250,865,868,11,5,16,12,true},
  {"BR_902", "Brazil 902",903.875,250,902,907.5,11,5,16,8,true},
  {"EU_433", "Europe 433",433.875,250,433,434,11,5,16,4,false},
  {"ANZ_433", "Australia / NZ 433",434.425,250,433.05,434.79,11,5,16,6,false},
  {"UA_433", "Ukraine 433",434.375,250,433,434.7,11,5,16,6,false},
  {"MY_433", "Malaysia 433",433.875,250,433,435,11,5,16,4,false},
  {"PH_433", "Philippines 433",434.375,250,433,434.7,11,5,16,6,false},
  {"KZ_433", "Kazakhstan 433",434.450,250,433.075,434.775,11,5,16,6,false}
};
constexpr std::size_t profileCount=sizeof(profiles)/sizeof(profiles[0]);
inline const Profile* find(const char* code) {
  if(code) for(const auto& profile:profiles) if(!std::strcmp(code,profile.code)) return &profile;
  return nullptr;
}
inline bool fitsHardware(double frequency, double bandwidth,
                         double minimum, double maximum,double tolerance=0.000001) {
  const double halfWidth=bandwidth/2000.0;
  return frequency-halfWidth>=minimum-tolerance && frequency+halfWidth<=maximum+tolerance;
}
#if defined(LORA_TUNNEL_CARDPUTER_ADV)
constexpr double hardwareMinimum=868.0, hardwareMaximum=923.0;
#else
constexpr double hardwareMinimum=863.0, hardwareMaximum=928.0;
#endif
inline bool selectable(const Profile& profile) {
  return profile.high_band_compatible &&
      fitsHardware(profile.frequency_mhz,profile.bandwidth_khz,hardwareMinimum,hardwareMaximum);
}
inline bool isUnset(const char* code) { return code && !std::strcmp(code,"UNSET"); }

// Numeric interoperability data, not upstream implementation. Meshtastic
// 6d41e279f1f51bd59f687b9d441c1bf47b1594fc: MeshRadio.h and DisplayFormatters.cpp.
// A preset changes modulation AND the default-name-derived frequency slot.
struct ModemPreset {
  const char* code;
  const char* name;
  double bandwidth_khz;
  std::uint8_t sf, cr;
  std::uint16_t preamble;
};
constexpr ModemPreset modemPresets[] = {
  {"LONG_FAST", "LongFast", 250, 11, 5, 16},
  {"LONG_TURBO", "LongTurbo", 500, 11, 8, 16},
  {"LONG_MODERATE", "LongMod", 125, 11, 8, 16},
  {"LONG_SLOW", "LongSlow", 125, 12, 8, 16},
  {"MEDIUM_FAST", "MediumFast", 250, 9, 5, 16},
  {"MEDIUM_SLOW", "MediumSlow", 250, 10, 5, 16},
  {"SHORT_FAST", "ShortFast", 250, 7, 5, 16},
  {"SHORT_SLOW", "ShortSlow", 250, 8, 5, 16},
  {"SHORT_TURBO", "ShortTurbo", 500, 7, 5, 16}
};
constexpr std::size_t modemPresetCount=sizeof(modemPresets)/sizeof(modemPresets[0]);
inline const ModemPreset* findModemPreset(const char* code) {
  if(code)for(const auto& p:modemPresets)if(!std::strcmp(p.code,code))return &p;
  return nullptr;
}
inline std::uint16_t slotCount(const Profile& region,const ModemPreset& modem) {
  return static_cast<std::uint16_t>(std::floor(
      (region.maximum_mhz-region.minimum_mhz+0.0000001)/(modem.bandwidth_khz/1000.0)));
}
inline std::uint32_t channelNameHash(const char* name) {
  std::uint32_t hash=5381;
  for(;name && *name;++name)hash=hash*33+static_cast<unsigned char>(*name);
  return hash;
}
// Slot 0 selects the preset's default channel name. Reject an unavailable
// preset/slot rather than silently clamping bandwidth or wrapping the slot.
// Board-specific occupied-band validation remains selectable(output).
inline bool makeProfile(const char* regionCode,const char* presetCode,
                        std::uint16_t slot,Profile& output) {
  const auto* region=find(regionCode);
  const auto* modem=findModemPreset(presetCode);
  if(!region || !modem)return false;
  const auto slots=slotCount(*region,*modem);
  if(!slots || slot>slots)return false;
  const auto selected=slot?slot:std::uint16_t(1+channelNameHash(modem->name)%slots);
  Profile candidate=*region;
  candidate.bandwidth_khz=modem->bandwidth_khz;
  candidate.sf=modem->sf;candidate.cr=modem->cr;candidate.preamble=modem->preamble;
  candidate.frequency_slot=selected;
  candidate.frequency_mhz=region->minimum_mhz+(selected-0.5)*modem->bandwidth_khz/1000.0;
  if(!fitsHardware(candidate.frequency_mhz,candidate.bandwidth_khz,
                   region->minimum_mhz,region->maximum_mhz))return false;
  output=candidate;
  return true;
}
} }
