#pragma once
#include <cstddef>
#include <cstdint>
#include "mesh_decode.h"

namespace tunnel { namespace messaging {
constexpr std::size_t TextBytes=120, NameBytes=31, ContactCount=8, HistoryCount=6;
enum class Delivery : std::uint8_t { Received, Queued, Transmitting, Sent, AwaitingAck, Delivered, ReceiptUnverified, Failed, Cancelled };
struct Contact {
  mesh::Protocol protocol=mesh::Protocol::Unknown;
  std::uint32_t node=0;
  std::uint8_t public_key[32]{};
  char name[NameBytes+1]{};
  bool trusted=false, key_changed=false;
};
struct Record {
  mesh::Protocol protocol=mesh::Protocol::Unknown;
  Delivery delivery=Delivery::Received;
  std::uint32_t id=0, peer=0;
  bool outgoing=false, direct=false, authenticated=false;
  char name[NameBytes+1]{}, text[TextBytes+1]{};
};
// Main-loop-owned records: UI may read until its tick returns, never retain or
// mutate the pointers. Avoid duplicating the bounded inbox in the screen model.
struct View {
  bool active=false, tx_enabled=false, identity_ready=false;
  mesh::Protocol protocol=mesh::Protocol::Meshtastic;
  char status[64]{}, name[NameBytes+1]{}, channel[40]{}, identity[72]{};
  std::uint8_t history_count=0, contact_count=0;
  const Record* history=nullptr;
  const Contact* contacts=nullptr;
};
inline const char* deliveryName(Delivery d) {
  switch(d) {
    case Delivery::Received:return "Received";
    case Delivery::Queued:return "Queued";
    case Delivery::Transmitting:return "Sending";
    case Delivery::Sent:return "Sent (unconfirmed)";
    case Delivery::AwaitingAck:return "Waiting for receipt";
    case Delivery::Delivered:return "Delivered";
    case Delivery::ReceiptUnverified:return "Receipt (unverified)";
    case Delivery::Failed:return "Failed / no receipt";
    case Delivery::Cancelled:return "Cancelled";
  }
  return "Unknown";
}
} }
