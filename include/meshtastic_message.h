#pragma once
// Copyright (c) 2026 Valleytech Solutions. SPDX-License-Identifier: MIT
// Bounded Meshtastic wire codec. No radio, storage, trust database or replay cache.
#include "mesh_header.h"
#include <cstddef>
#include <cstdint>

namespace tunnel { namespace meshtastic {
constexpr std::size_t TextBytes=120, NameBytes=31;
constexpr std::uint32_t Broadcast=0xffffffffU;
using Header=lt::MeshHeader;
struct Frame { std::uint8_t bytes[255]{}; std::size_t length=0; };
struct Channel { std::uint8_t key[32]{}; std::uint8_t key_length=0, hash=0; };
struct Identity {
  std::uint32_t node=0;
  std::uint8_t private_key[32]{}, public_key[32]{};
  char name[NameBytes+1]{}, short_name[5]{};
};
// A discovery packet is not proof of key ownership. The caller supplies a
// previously accepted/pinned peer key here and handles changes explicitly.
struct Contact { std::uint32_t node=0; std::uint8_t public_key[32]{}; bool has_public_key=false; };
struct Tx {
  std::uint32_t packet_id=0;
  std::uint8_t hop_limit=3;
  bool want_ack=false;
  // Fresh cryptographic random value for private packets, supplied by caller.
  // packet_id must also be reserved persistently before transmission/retry.
  std::uint32_t extra_nonce=0;
};
struct Crypto {
  bool (*ctr)(const std::uint8_t*,std::size_t,const std::uint8_t[16],const std::uint8_t*,std::size_t,std::uint8_t*)=nullptr;
  bool (*sharedKey)(const std::uint8_t[32],const std::uint8_t[32],std::uint8_t[32])=nullptr;
  bool (*ccmSeal)(const std::uint8_t[32],const std::uint8_t[13],const std::uint8_t*,std::size_t,std::uint8_t*,std::uint8_t[8])=nullptr;
  bool (*ccmOpen)(const std::uint8_t[32],const std::uint8_t[13],const std::uint8_t*,std::size_t,const std::uint8_t[8],std::uint8_t*)=nullptr;
  bool (*derivePublic)(const std::uint8_t[32],std::uint8_t[32])=nullptr;
  bool (*hmac)(const std::uint8_t[32],const std::uint8_t*,std::size_t,std::uint8_t[32])=nullptr;
};
enum class Kind : std::uint8_t { None, Text, NodeInfo, Receipt };
enum class Status : std::uint8_t { Malformed, Ok, WrongChannel, WrongPeer, CryptoFailed, Unsupported };
struct Parsed {
  Header header{};
  Status status=Status::Malformed;
  Kind kind=Kind::None;
  // True only for valid pairwise CCM or verified receipt proof. Channel CTR
  // and a public NodeInfo key alone never authenticate a claimed sender.
  bool authenticated=false, private_envelope=false, request_response=false;
  bool has_public_key=false, has_receipt_proof=false, receipt_proof_valid=false, sanitized=false;
  std::uint32_t request_id=0, reply_id=0, routing_error=0;
  std::uint8_t public_key[32]{};
  char text[TextBytes+1]{}, name[NameBytes+1]{}, short_name[5]{};
};

const Crypto& platformCrypto();
bool peekHeader(const std::uint8_t*,std::size_t,Header&);
bool encodeChannelText(const Channel&,const Identity&,const Tx&,const char*,Frame&,const Crypto&);
bool encodePrivateText(const Identity&,const Contact&,const Tx&,const char*,Frame&,const Crypto&);
bool encodeNodeInfo(const Channel&,const Identity&,const Tx&,Frame&,const Crypto&,bool request_response=false,
                    std::uint32_t to=Broadcast);
// Routing requests refer to the original packet through Data.request_id.
// Receipt sends never request a receipt themselves. ack_peer adds the current
// protocol's pairwise HMAC proof to a normal channel-encrypted ACK/NAK.
bool encodeReceipt(const Channel&,const Identity&,std::uint32_t to,const Tx&,std::uint32_t request_id,
                   std::uint32_t error,Frame&,const Crypto&,const Contact* ack_peer=nullptr);
bool encodePrivateReceipt(const Identity&,const Contact&,const Tx&,std::uint32_t request_id,
                          std::uint32_t error,Frame&,const Crypto&);
bool decodeChannel(const std::uint8_t*,std::size_t,const Channel&,Parsed&,const Crypto&,
                   const Identity* local=nullptr,const Contact* ack_peer=nullptr);
// Fail closed: do not fall back to channel decoding after an attempted private
// packet fails authentication. Header destination/sender must match inputs.
bool decodePrivate(const std::uint8_t*,std::size_t,const Identity&,const Contact&,Parsed&,const Crypto&);
// Correlation only, not replay storage. Caller must additionally require an
// outstanding request and consume it once; packet IDs must not be reused.
bool receiptMatches(const Parsed&,std::uint32_t local,std::uint32_t expected_peer,
                    std::uint32_t original_packet_id,bool require_authenticated=true);
} }
