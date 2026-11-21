// Host driver for tools/check_recon_parity.py: runs the firmware Recon
// classifier (lib/recon) on cases read from stdin, one per line.
//   W <mac> <ssid-hex|->            AP by BSSID and SSID
//   F <frame-hex>                   raw 802.11 frame without FCS
//   B <mac|-> <type> <ad-hex> <adv-length>
// Output per line: category|confidence|evidence|vendor|payload_valid|rid|beacon
#include <TunnelRecon.h>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using namespace tunnel::recon;
static std::vector<uint8_t> unhex(const std::string& s) {
  std::vector<uint8_t> out;
  if (s == "-") return out;
  for (size_t i = 0; i + 1 < s.size(); i += 2) out.push_back(uint8_t(std::stoul(s.substr(i, 2), nullptr, 16)));
  return out;
}
static void print(const Result& r) {
  std::printf("%d|%d|%s|%s|%d|", int(r.category), int(r.confidence), r.evidence, r.vendor, r.payload_valid ? 1 : 0);
  const auto& d = r.remote_id;
  if (d.decoded) {
    std::printf("%d,%d,%d,%s,%.6f,%.6f,%d,%.6f,%.6f,%d,%.1f,%d,%.2f,%d,%d,%d", d.has_id, d.has_location, d.has_operator,
                d.id, d.has_location ? d.latitude : 0.0, d.has_location ? d.longitude : 0.0, d.has_operator,
                d.has_operator ? d.operator_latitude : 0.0, d.has_operator ? d.operator_longitude : 0.0,
                d.has_altitude, d.has_altitude ? d.altitude_m : 0.0f, d.has_speed, d.has_speed ? d.speed_mps : 0.0f,
                d.id_type, d.aircraft_type, d.operator_location_type);
  }
  std::printf("|");
  if (r.beacon.valid) {
    for (auto b : r.beacon.uuid) std::printf("%02x", b);
    std::printf(",%u,%u,%d", r.beacon.major, r.beacon.minor, r.beacon.measured_power);
  }
  std::printf("\n");
}
int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream in(line);
    std::string kind;
    in >> kind;
    if (kind == "W") {
      std::string mac, ssid;
      in >> mac >> ssid;
      auto raw = unhex(ssid);
      std::string text(raw.begin(), raw.end());
      print(classifyWifi(mac.c_str(), text.c_str()));
    } else if (kind == "F") {
      std::string hex;
      in >> hex;
      auto frame = unhex(hex);
      static const uint8_t none[6] = {};
      print(classifyWifi(none, nullptr, frame.data(), frame.size()));
    } else if (kind == "B") {
      std::string mac, adhex;
      unsigned type = 0, advLength = 0;
      in >> mac >> type >> adhex >> advLength;
      auto ad = unhex(adhex);
      if (mac == "-") print(classifyBle(static_cast<const uint8_t*>(nullptr), uint8_t(type), ad.data(), ad.size(), advLength));
      else print(classifyBle(mac.c_str(), uint8_t(type), ad.data(), ad.size(), advLength));
    }
    std::fflush(stdout);
  }
}
