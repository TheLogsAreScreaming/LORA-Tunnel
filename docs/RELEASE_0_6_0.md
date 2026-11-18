# LORA Tunnel 0.6.0

Version 0.6.0 adds configurable Meshtastic modem presets, including **LongTurbo**, MeshCore group-text decoding, and separate **Meshtastic/MeshCore channel and private messaging** to Heltec Expansion Kit V2 / V4-R8 and Cardputer ADV + U214. Wi-Fi/BLE wardriving, Recon, GNSS logging, SD sessions and idle-only uploads remain available.

The owner reported satisfactory operation and authorized publication on **2026-11-18**. That acceptance is separate from the instrumented results and remaining checks below. The release promotes the functional code from `0.6.0-dev.chat5`; rebuilding with the release version produces different binary hashes. Earlier 0.5.0 artifacts and their [validation record](RELEASE_0_5_0.md) remain historical downloads.

## Receive profiles and passive decoding

- **Settings → Mesh radio / decode settings** selects Meshtastic, MeshCore or Both / slow scan; the Meshtastic preset and frequency slot; MeshCore profile; dwell; and public decoding. Changes save to the SD configuration, including unchanged-value saves.
- Meshtastic presets include LongFast, LongTurbo, LongModerate, LongSlow, MediumFast, MediumSlow, ShortFast, ShortSlow and ShortTurbo. AUTO uses the preset's default slot; explicit slots match a community's actual frequency. Region and board bandwidth checks reject incompatible selections instead of silently substituting another preset.
- US LongTurbo's default is **908.750 MHz / 500 kHz / SF11 / CR4/8**, slot 14. Channel names and keys remain separate from modem settings. A custom channel name on a peer can change its automatic slot.
- Passive decoding retains supported Meshtastic node information, positions, text and battery/voltage telemetry, signed MeshCore public adverts, and supported MeshCore group text with Public or configured keys. The raw packet and receive-time radio settings remain available when a payload is unknown or unsupported.

Both / slow scan uses one selected profile per protocol, with a 30–600 second dwell. The single SX1262 cannot receive both configurations simultaneously. Passive Wardriver does not send messages or decrypt other users' private conversations. [Profile tables and decoder scope](COMBINED_MESH.md).

## Messages and controls

Stop and save capture, then open **Home → Messages**. Choose one protocol, match the peer's modem/channel settings, and explicitly enable transmission before composing or announcing. TX starts OFF at boot and at each new messaging session; configuration imports cannot enable it.

- Meshtastic and MeshCore support channel text and private text addressed to trusted contacts. Compare the full public key before trusting a contact. Trust confirmation is bound to the key actually reviewed; changing or moving that contact invalidates a stale review.
- Identity and trust records persist in the application's `lt-chat` NVS namespace. The six-record inbox and unsent drafts are RAM-only; leaving Messages clears them. Private messages have bounded retries and distinguish local transmission, authenticated receipt, unverified receipt and failure.
- Heltec touch handling recovers from zero-contact and empty reports; one touch does not carry through into a newly opened action. Command feedback reflects current messaging state and explains rejected or inactive actions. Cardputer uses physical text entry, modifiers and Backspace; Heltec uses its touchscreen keyboard.
- MeshCore group duplicate filtering uses validated packet content. Different messages sharing a sender name and timestamp remain distinct. Repeater copies and successful local echoes are suppressed within the bounded cache; a claimed group sender name remains unverified.

Messages owns the LoRa radio and stops Wi-Fi/BLE capture until the user leaves that mode. This is a messaging endpoint, not a complete upstream Meshtastic or MeshCore routing stack. [Controls, configuration and receipts](MESSAGING.md).

## Storage failure handling

If storage fails during Wardriver or Recon, capture now stops, drains its queues and reports an **incomplete log**. It does not continue accumulating unsavable observations or label the session successfully saved. Recovery requires a deliberate storage check/remount and a new capture start.

Numeric diagnostics retain the first failure reason, checked-file operation and errno until reboot, including across a remount. Cleanup cannot overwrite the original write/flush/sync failure. Diagnostic output excludes paths, session contents, credentials and private identity keys.

## Downloads and installation

| Image | Intended use |
| --- | --- |
| `LORA-Tunnel-0.6.0-Heltec-V4-R8-TFT-HIGH-BAND-FACTORY-0x0.bin` | Heltec Expansion Kit V2 / V4-R8, 863–928 MHz; standalone USB/web installation at `0x0` |
| `LORA-Tunnel-0.6.0-Heltec-V4-R8-TFT-HIGH-BAND-LAUNCHER-APP.bin` | Heltec application installed through Bmorcelli Launcher's SD menu |
| `LORA-Tunnel-0.6.0-Cardputer-ADV-LoRa1262-FACTORY-0x0.bin` | Cardputer ADV + U214; standalone USB/web/M5Burner installation at `0x0` |
| `LORA-Tunnel-0.6.0-Cardputer-ADV-LoRa1262-LAUNCHER-APP.bin` | Cardputer application installed through Bmorcelli Launcher's SD menu |

Each board's Launcher image is the application from its matching factory build. Launcher chooses the destination partition; **never flash an application-only image at `0x0`**. Factory installation replaces the existing boot environment, including Launcher. Preserve a private recovery copy and the working SD configuration. The original Cardputer, U201 cap, Heltec V1 and low-band kits are different hardware.

Release materials include buildable source, a matching dependency/relinking archive for each target, empty-credential SD setup, previews and SHA-256 checksums. Use the release checksum file for the final binaries; candidate hashes do not identify the rebuilt 0.6.0 images. [GitHub downloads](https://github.com/valleytechsolutions/LORA-Tunnel/releases/tag/v0.6.0) · [Web flasher](https://valleytech-lora-tunnel.pages.dev/) · [Cardputer setup](CARDPUTER_ADV.md) · [Heltec recovery](RECOVERY.md) · [Rebuilding and licenses](RELINKING.md).

## Validation evidence and remaining limits

The preceding chat5 package records both firmware builds, 189 native checks, 135 Python checks with no skips, seven Node checks, three schemas and nine examples. Focused checks include 483 MeshCore protocol checks, 688 messaging-engine checks, 18 storage-adapter checks, radio lifecycle fixtures for both boards, touch/keyboard/UI fixtures, and real checked-file/logger fault injection. The messaging workspace is 3,424 bytes. These are source/build results, not measurements of peer reception or RF output.

The hardware observations below come from chat5 source commit `b113b9e4230553bcf909a75018a5578209bf20a4`, its `CANDIDATE.json` and `HARDWARE-CHECKS` records dated 2026-11-18:

| Check | Recorded result |
| --- | --- |
| Heltec installation | Application updated inside its existing Launcher messaging slot; application readback and preserved bootloader, partition table, prior applications and filesystem ranges verified. This was not a fresh Launcher-menu installation test. |
| Mode lifecycle | Six start/stop cycles, three per protocol, completed with TX off. |
| Capture/storage | A batch write returned I/O error `5` after approximately ten minutes. Capture automatically stopped and drained. Storage-error count remained 1 and reported drops remained 10 afterward. The physical storage cause is unidentified. |
| Continued messaging | Messages remained available after the storage fault. One planned ten-minute Meshtastic monitor ended after 393 valid samples, approximately 404 seconds, because a required USB status line was malformed. That test remains incomplete. A bounded follow-up, including three minutes of MeshCore receive-only operation, completed. |
| Resources | Minimum free internal heap 98,144 bytes; minimum largest internal block 57,332 bytes; loop/writer stack margins 4,124 / 5,164 bytes. No reset, watchdog or allocation failure was observed in the recorded checks. |
| Peer traffic and UI | No controlled peer packets arrived during the unattended observations. There was no physical UI interaction, so UI latency was not measured. |
| Cardputer | Built and packaged; no separate hardware acceptance run for this messaging build. Heltec results do not establish Cardputer behavior. |

Thirty-minute capture acceptance and independent SD readback were **not completed**. The automatic stop demonstrates failure handling, not a complete durable log or lossless capture. The owner's broader acceptance does not substitute for recorded channel/private peer exchanges, delivery receipts, final-image browser/Launcher round trips, or a full per-board persistence/power test matrix. Live upload-service receipts and WDGWars mesh ingestion are also not established by these results.

Compatibility limits:

- Meshtastic channel text and NodeInfo are **unsigned**. Peers using the 2.8.2+ `STRICT` signature policy reject them. Incoming XEdDSA signature fields are parsed but not verified; private CCM and receipt-proof authentication are separate. [Signature-policy details](MESSAGING.md#troubleshooting-and-stock-peer-compatibility).
- MeshCore sending, announcements and private reception require valid GNSS UTC. Channel reception and signed contact discovery can operate without UTC.
- The transmitter uses 0 dBm raw SX1262 drive. The Heltec's external PA output has not been independently calibrated; raw drive is not antenna-port power. Software airtime spacing is not a measured regulatory certification.
- Queues, inbox history and duplicate caches are bounded. Drops and finite-cache expiry remain possible. Unsupported payloads, arbitrary hopping lists and Kismet datasource/PCAP-NG integration remain outside this release.

Original application code remains MIT licensed. Retained dependency licenses and provenance accompany the source; SquachWatch was a feature reference and its GPL application code was not copied into this implementation.
