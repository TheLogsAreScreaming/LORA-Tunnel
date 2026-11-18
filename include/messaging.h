#pragma once
#include "messaging_ui.h"
#include "messaging_config.h"

namespace tunnel { namespace messaging {
enum class Load : std::uint8_t { Missing, Ok, Invalid };
struct Storage {
  Load (*load)(const char*,void*,std::size_t)=nullptr;
  bool (*save)(const char*,const void*,std::size_t)=nullptr;
  std::uint32_t (*random)()=nullptr;
  void* (*allocate)(std::size_t)=nullptr;
  void (*release)(void*)=nullptr;
};
const Storage& platformStorage();
// Public numeric evidence for diagnosing UI/radio handoffs. These counters
// survive leaving Messages, but reset on boot; they contain no peer identifiers,
// keys or message contents. TX completion does not establish peer delivery.
struct Diagnostics {
  std::uint32_t starts=0,stops=0,tx_enable_requests=0,tx_enabled=0,tx_disable_requests=0;
  std::uint32_t send_requests=0,send_queued=0,announce_requests=0,announce_queued=0;
  std::uint32_t rx_frames=0,rx_text=0,rx_nodes=0,rx_receipts=0,tx_ok=0,tx_fail=0,radio_failures=0;
};
Diagnostics diagnostics();
// All methods run on the main loop. No callback/ISR accesses this workspace.
// Caller has stopped capture/uploads and obtained exclusive radio ownership.
bool begin(mesh::Protocol,const Settings&,const char* defaultChannel,const Storage&);
void end();
bool active();
bool busy();
bool transmitAllowed();
void view(View&);
bool setTransmit(bool);
bool updateSettings(const Settings&,const char* defaultChannel);
bool trustContact(unsigned,const std::uint8_t expectedKey[32]);
bool forgetContact(unsigned,const std::uint8_t expectedKey[32]);
bool send(int contact,const std::uint8_t expectedKey[32],const char* text,std::uint32_t now,std::uint32_t unixTime);
bool announce(std::uint32_t now,std::uint32_t unixTime);
void receive(const std::uint8_t*,std::size_t,std::uint32_t now,std::uint32_t unixTime);
// Takes a stable frame until transmitted() or end(). 'now' wraps safely.
bool nextFrame(std::uint32_t now,const std::uint8_t*& bytes,std::size_t& length);
void transmitted(bool success,std::uint32_t now);
void tick(std::uint32_t now);
void radioFailure(const char* status);
std::size_t workspaceBytes();
} }
