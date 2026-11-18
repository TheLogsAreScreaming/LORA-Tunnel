#pragma once
#include <cstdint>
#include <cstddef>
#include "keyboard_input.h"
#include "messaging_ui.h"

namespace ui {
struct Model {
  tunnel::messaging::View messages{};
  bool messages_transitioning=false;
  bool running = false, recon = false, sd = false, gps = false, lora_ready = false;
  uint32_t wifi = 0, ble = 0, lora = 0, drops = 0, errors = 0, nmea_chars = 0;
  bool buttons_enabled = true, recon_alerts = true;
  bool region_configured = false, region_selection_made = false, shutting_down = false;
  char region[12]{};
  char shutdown_error[48]{};
  uint32_t recon_total = 0;
  float battery = 0;
  char utc[24]{}, profile[40]{}, phase[20]{}, notice[64]{};
  char recent[3][4][48]{};
  char gps_detail[48]{};
  uint8_t lora_mode=0;
  char meshtastic_preset[20]="LONG_FAST", meshcore_profile[32]="AUTO";
  uint16_t meshtastic_slot=0, meshtastic_slots=0;
  uint32_t lora_dwell_ms=30000;
  bool decode_public=true;
  uint32_t mesh_decoded=0, mesh_unknown=0;
  char lora_detail[48]{}, mesh_recent_detail[4][64]{};
  // Latest matched summaries only; Category/Confidence use tunnel::recon enums.
  char recon_recent[8][48]{}, recon_evidence[8][64]{};
  uint8_t recon_categories[8]{}, recon_confidence[8]{};
  bool upload_busy = false, auto_wigle = false, auto_wardrift = false, auto_wdgwars = false;
  char upload_status[64]{};
};
enum class Action { ToggleSession, ToggleMode, SaveCredential, RetryStorage, ToggleAlerts, SaveRegion, Shutdown, ToggleAutoUpload, UploadNow, CancelUpload, SaveLoRaMode,
  SaveMeshtasticPreset, SaveMeshtasticSlot, SaveMeshCoreProfile, SaveLoRaDwell, SavePublicDecode,
  StartMessages, StopMessages, ToggleMessageTx, SendMessage, AnnounceIdentity,
  TrustContact, ForgetContact, SaveMessagingSetting };
// Messaging fields: StartMessages=1 Meshtastic/2 MeshCore; ToggleMessageTx=0/1;
// SendMessage=-1 channel or 0..7 contact, at most 120 text bytes. Trust/Forget
// include the displayed 64-hex public key so the handler can reject a stale slot.
// SaveMessagingSetting=0 name/1 MT channel/2 MT key/3 MC key/4 MT hops.
// Handler executes synchronously, sometimes while UI owns SPI. Copy text to a
// bounded action queue immediately; do not access SD, radio, or draw here.
using Handler = void (*)(Action, int, const char*);
void begin(Handler handler);
// Cardputer-only temporary use of the existing RGB332 pixels, never a second
// framebuffer or heap fallback. The main task installs an authoritative idle
// guard before configuration operations. A lease suppresses drawing/input until
// release, which wipes scratch and forces a complete redraw. Heltec returns null.
using ConfigScratchGuard = bool (*)();
void setConfigScratchGuard(ConfigScratchGuard guard);
void* acquireConfigScratch(size_t bytes);
void releaseConfigScratch(void* memory);
// No display/SPI access. Call from the same task as tick(), outside the bus lock.
// Bitmask follows hw::Next=1, Select=2, Back=4. Disabled input is discarded.
void navigation(uint8_t events, const Model& model);
// Native keyboard input is always available on keyboard-only targets. No I/O.
void keyboard(const input::KeyEvent& event, const Model& model);
// Bounded 64-sample input-receipt-to-completed-draw window; max since boot.
uint32_t inputLatencyP95Ms();
uint32_t inputLatencyMaxMs();
uint32_t inputLatencySamples();
bool allowsBackgroundUpload();
bool allowsUploadJobPolling();
void tick(const Model& model);
}
