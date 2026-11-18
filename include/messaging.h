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
