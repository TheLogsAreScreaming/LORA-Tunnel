#pragma once
// SPDX-License-Identifier: MIT
// Bounded MeshCore chat wire endpoint. No storage, scheduler, radio, or heap.
#include <cstddef>
#include <cstdint>

namespace tunnel { namespace meshcore_message {
constexpr std::size_t MaxText=120, MaxName=31, MaxPath=64;
struct Frame { std::uint8_t bytes[255]{}; std::size_t length=0; };
struct Identity { std::uint8_t seed[32]{}, public_key[32]{}; };
struct Contact { std::uint8_t public_key[32]{}; char name[32]{}; std::uint32_t timestamp=0; };
// Adapters accept only bounded input and erase intermediate secrets. The same
// platform adapter runs in host tests using pinned rweather/Crypto 0.4.0.
struct Crypto {
  bool (*publicKey)(const std::uint8_t[32],std::uint8_t[32])=nullptr;
  bool (*sign)(const std::uint8_t[32],const std::uint8_t[32],const std::uint8_t*,std::size_t,std::uint8_t[64])=nullptr;
  bool (*verify)(const std::uint8_t[32],const std::uint8_t[64],const std::uint8_t*,std::size_t)=nullptr;
  bool (*shared)(const std::uint8_t[32],const std::uint8_t[32],std::uint8_t[32])=nullptr;
  bool (*sha256)(const std::uint8_t*,std::size_t,std::uint8_t[32])=nullptr;
  bool (*hmac)(const std::uint8_t[32],const std::uint8_t*,std::size_t,std::uint8_t[32])=nullptr;
  bool (*ecb)(bool,const std::uint8_t[16],const std::uint8_t*,std::size_t,std::uint8_t*)=nullptr;
};
enum class Kind : std::uint8_t { None, GroupText, DirectText, Advert, Receipt };
enum class ReceiptTrust : std::uint8_t { None, HashOnly, AuthenticatedPeer };
struct Message {
  Kind kind=Kind::None;
  std::uint32_t timestamp=0;
  std::uint8_t attempt=0, sender[32]{}, recipient[32]{}, ack[4]{};
  // Validated group's canonical packet digest, not an authenticated sender ID.
  // First 8 SHA-256 bytes over payload type + payload, excluding mutable paths.
  std::uint8_t group_fingerprint[8]{};
  std::uint8_t path[MaxPath]{}, path_encoding=0;
  bool flood=false;
  ReceiptTrust receipt_trust=ReceiptTrust::None;
  char name[32]{}, text[121]{};
};
// Root owns persistence and entropy; failed derivation zeros the output.
bool identity(const std::uint8_t seed[32],const Crypto&,Identity&);
bool groupText(const std::uint8_t* key,std::size_t keyLength,const char* name,const char* text,
               std::uint32_t timestamp,std::uint8_t attempt,const Crypto&,Frame&);
bool parseGroup(const std::uint8_t*,std::size_t,const std::uint8_t* key,std::size_t keyLength,const Crypto&,Message&);
bool advert(const Identity&,const char* name,std::uint32_t timestamp,const Crypto&,Frame&);
bool parseAdvert(const std::uint8_t*,std::size_t,const Crypto&,Contact&);
// Direct sends use flood. ack is the expected protocol hash for this attempt.
bool directText(const Identity&,const Contact&,const char* text,std::uint32_t timestamp,
                std::uint8_t attempt,const Crypto&,Frame&,std::uint8_t ack[4]);
// Each peer candidate is supplied by the caller; one-byte wire hashes alone
// never establish contact identity. Shared-secret MAC must also verify.
bool parseDirect(const std::uint8_t*,std::size_t,const Identity&,const Contact&,const Crypto&,Message&);
// Flood text gets encrypted PATH+ACK; direct text gets protocol bare ACK.
bool reply(const Identity&,const Contact&,const Message& received,const Crypto&,Frame&);
// expectedAck must belong to this exact outstanding peer + attempt. Bare ACKs
// contain no sender/destination and are returned as HashOnly, never authenticated.
bool parseReceipt(const std::uint8_t*,std::size_t,const Identity&,const Contact&,
                  const std::uint8_t expectedAck[4],const Crypto&,Message&);
const Crypto& platformCrypto();
const std::uint8_t* publicGroupKey(); // 16 bytes, public protocol constant
} }
