# Combined Meshtastic and MeshCore observation

LORA Tunnel provides a shared LoRa capture path with separate Meshtastic and MeshCore decoders. Version 0.6.0 extends the earlier 0.5.0 implementation with selectable Meshtastic modem presets, including Long Turbo, and receive-only MeshCore group-text decoding. Separate [Messages mode](MESSAGING.md) supports channel/private conversations addressed to this device; this page describes passive Wardriver decoding. Wardriver sessions can stay on one protocol or alternate between one selected profile for each protocol. The device saves received radio bytes and radio settings before attempting to decode them, so later software can revisit incomplete or unsupported results.

This document describes the source implementation. It does not certify a successful hardware capture, flash, drive, or service upload. The validation checklist below separates host checks from physical acceptance. The supported subset is listed explicitly; this is not a claim of complete Kismet decoder parity.

[Earlier 0.5.0 validation](COMBINED_MESH_VALIDATION.md) remains a historical record. The [0.6.0 release record](RELEASE_0_6_0.md) separates owner acceptance from the instrumented observations and controlled peer checks that remain independently unverified; earlier results do not certify the final 0.6.0 binaries.

## Choose a mode

Select the correct region first. While the session is stopped, open **Settings → Mesh radio / decode settings**. The dedicated page offers the mode (**Meshtastic**, **MeshCore** or **Both / slow scan**), Meshtastic preset and slot, MeshCore profile, dwell and public decoding. Open a field, choose a value and save; cancel leaves its current value unchanged. Settings save to the SD configuration. Changes require capture and saving to finish, uploads to be idle and SD to be available. A mode requiring MeshCore is rejected when the selected region has no supported MeshCore receive profile. Recon mode retains its Wi-Fi/BLE detection behavior; this LoRa feature belongs to Wardriver mode.

The LoRa view shows the active profile, decoded/other totals, and the time until the next profile change when combined scanning is active. Received nodes retain protocol-specific identities. Display summaries can combine later sightings of a node, while the observation log retains each received packet.

For a USB bench check, `python tools/bench_serial.py --port YOUR_PORT --command status --seconds 60` also shows a numeric `LT RADIO` record on 0.5.0 and newer builds. Mode 0 is Meshtastic, 1 is MeshCore and 2 is combined; active protocol 1 is Meshtastic and 2 is MeshCore. Frequency is in kHz and bandwidth in Hz. Per-protocol listen times, receive counts and switch/deferral counters let you check scheduling separately from packet decoding. These are firmware-reported settings and counters, not independent RF measurements. The helper retains only allowlisted numeric radio fields and does not print payloads, keys or locations. A radio record alone cannot acknowledge a command; a complete, fresh `LT STATUS` record remains required.

One SX1262 can listen to one frequency, bandwidth, spreading factor and sync word at a time. Meshtastic uses sync word `0x2B`; MeshCore uses `0x12`. Even when two communities use the same center frequency, those receive settings remain distinct. An opposite-profile transmission can be missed while the receiver listens elsewhere. Software cannot recover a packet that the radio never demodulated. [Kismet LoRaPipe receive and hopping documentation](https://www.kismetwireless.net/docs/readme/datasources/lora-lorapipe/)

Combined mode uses a configurable dwell of **30–600 seconds per profile**. The default is 30 seconds. Pending receive work is serviced before a change, and an observed in-progress packet can defer it within a bounded grace period. This avoids an unlimited stall caused by noise or an incomplete preamble. Longer dwell increases listening time on the selected profile but also increases the gap on the other profile. Sparse node announcements can require much longer observation; a quiet interval does not prove that no nodes are present. Profile locking is useful when comparing against a known transmitter.

## Receive profiles

Choose the Meshtastic modem preset and slot while capture is stopped. A region selection starts from LongFast. Selecting another preset changes bandwidth, spreading factor, coding rate and its default channel-name-derived frequency; changing only the displayed name would not tune the radio correctly. The slot selector uses `0` for the preset's default channel slot and positive, one-based slots for a specific community. Match the transmitter's modem and frequency settings; an encryption key cannot compensate for the wrong receive settings.

| Meshtastic setting | Default channel name | Bandwidth kHz | SF | Configured CR | US default slot | US frequency MHz |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| `LONG_FAST` | LongFast | 250 | 11 | 4/5 | 20 | 906.875 |
| `LONG_TURBO` | LongTurbo | 500 | 11 | 4/8 | 14 | 908.750 |
| `LONG_MODERATE` | LongMod | 125 | 11 | 4/8 | 6 | 902.6875 |
| `LONG_SLOW` | LongSlow | 125 | 12 | 4/8 | 27 | 905.3125 |
| `MEDIUM_FAST` | MediumFast | 250 | 9 | 4/5 | 45 | 913.125 |
| `MEDIUM_SLOW` | MediumSlow | 250 | 10 | 4/5 | 52 | 914.875 |
| `SHORT_FAST` | ShortFast | 250 | 7 | 4/5 | 68 | 918.875 |
| `SHORT_SLOW` | ShortSlow | 250 | 8 | 4/5 | 75 | 920.625 |
| `SHORT_TURBO` | ShortTurbo | 500 | 7 | 4/5 | 50 | 926.750 |

All listed Meshtastic presets use a 16-symbol preamble and sync word `0x2B`. In ANZ, LongTurbo defaults to slot 14 at **921.750 MHz**. Europe 868's 869.4–869.65 MHz region is too narrow for either 500 kHz Turbo preset; selection is rejected without falling back to LongFast. [Inspected modem parameters](https://github.com/meshtastic/firmware/blob/6d41e279f1f51bd59f687b9d441c1bf47b1594fc/src/mesh/MeshRadio.h), [frequency-slot calculation](https://github.com/meshtastic/firmware/blob/6d41e279f1f51bd59f687b9d441c1bf47b1594fc/src/mesh/RadioInterface.cpp).

The entire occupied bandwidth must fit both the region and the board. The Heltec supports US LongTurbo slots 1–52 and ANZ slots 1–26; the narrower U214 supports US slots 1–42 and ANZ slots 1–16. US ShortTurbo's default frequency fits the Heltec but exceeds the U214 maximum of 923 MHz. A compatible custom slot may still be used. Invalid slot numbers are rejected rather than wrapped. Existing SD files with custom raw radio fields and no named preset retain those exact settings and appear as `CUSTOM`.

The following MeshCore selections are included. `AUTO` chooses the first listed profile for that region; it does not detect a community's settings automatically.

| Region | MeshCore selection | Frequency MHz | Bandwidth kHz | SF | Configured CR |
| --- | --- | ---: | ---: | ---: | --- |
| US / Canada | `US-NARROW` (`AUTO`) | 910.525 | 62.5 | 7 | 4/5 |
| US / Canada | `US-SOCAL` | 927.875 | 62.5 | 7 | 4/5 |
| Europe 868 | `EU_868-NARROW` (`AUTO`) | 869.618 | 62.5 | 8 | 4/8 |
| Europe 868 | `EU_868-SF7` | 869.618 | 62.5 | 7 | 4/5 |
| Europe 868 | `EU_868-LEGACY` | 869.525 | 250 | 11 | 4/5 |
| Australia / NZ 915 | `ANZ-DEFAULT` (`AUTO`) | 915.800 | 250 | 10 | 4/5 |
| Australia / NZ 915 | `ANZ-NARROW` | 916.575 | 62.5 | 7 | 4/7 |
| Australia / NZ 915 | `ANZ-MID` | 915.075 | 125 | 9 | 4/5 |
| Australia / NZ 915 | `ANZ-NZ_NARROW` | 917.375 | 62.5 | 7 | 4/5 |

These are receive presets derived from the [MeshCore FAQ](https://github.com/meshcore-dev/MeshCore/blob/81dbae592ffad40b4212bc0b37e82b38da08f4bc/docs/faq.md) and [Kismet channel reference](https://www.kismetwireless.net/docs/readme/datasources/lora-lorapipe/#channel-reference). Selection is checked against the target's supported band. The Cardputer U214 target is limited to 868–923 MHz; it cannot select `US-SOCAL`. Importing a valid Heltec configuration that requests an incompatible Cardputer frequency disables LoRa and preserves the rest of the configuration. Changing regions resets the MeshCore selection to `AUTO`; regions without an included MeshCore preset revert to Meshtastic mode.

## Meshtastic decoding

The local parser supports ordinary AES-CTR channel payloads with the published default AES-128 key, configured AES-128/AES-256 keys, and explicitly configured plaintext channels. It reads the bounded protobuf wire format directly; it does not embed Meshtastic's network stack or generated GPL schema files.

Supported application fields are:

- Node information: long name, short name, source ID from the radio header, and hardware/role values when those fields are present.
- Position: both advertised coordinates when present and valid, reported MSL altitude, timestamp, and available precision bits. An explicit `(0,0)` coordinate pair remains a valid pair; missing coordinates do not become zero coordinates.
- Text: ordinary text, detection-sensor text and alert text, bounded to 159 UTF-8 bytes for decoded display/log fields. Raw radio bytes retain the original content.
- Device telemetry: reported battery level and voltage, with optional message timestamp. Battery value `101` means external power, not 101 percent. Other telemetry variants remain unsupported.

Node names, positions and telemetry arrive in separate broadcasts. A packet does not imply that every field is available. The receiver does not query nodes, join channels, send acknowledgments or relay packets.

AES-CTR does not authenticate the sender. A valid protobuf result, matching channel hash or successful radio read is not proof of identity. Current XEdDSA signatures are reported as present and unverified. Optional authenticated AES-CCM channel mode, private-key-encrypted direct messages, compressed text and other application payloads are outside this decoder's current scope. Retained raw packets remain available. [Meshtastic encryption documentation](https://meshtastic.org/docs/overview/encryption/), [inspected message definitions](https://github.com/meshtastic/protobufs/tree/85f3f4357946a52daa5310285476d2dffb137c7b/meshtastic)

## MeshCore decoding

Public MeshCore node advertisements contain a public identity key, timestamp, signature and optional application fields. LORA Tunnel parses the available name, reported role and advertised position, and verifies the Ed25519 advert signature when the firmware crypto adapter is present. The signed data excludes mutable routing/path fields. A verified signature establishes that the advert was signed for that key; it does not establish the truth of its location, ownership, proximity or freshness.

The parser validates current one-, two- and three-byte path-hash layouts, transport-header lengths and payload bounds. It records packet type, path count and hash width. Supported acknowledgment shape is recognized without inventing a node identity. Compatible group-text packets can be decrypted with the published Public group key or up to four explicitly configured group keys. Group decoding checks the two-byte channel MAC before decrypting and reports `channel_mac_valid` separately from sender authentication. A short shared-key MAC and a self-asserted sender name do not authenticate a particular node. Group text therefore does not create an advertised node identity or position.

Ordinary group text includes its reported timestamp and bounded text, with an optional name parsed from the conventional `name: text` prefix. The original raw packet is retained. Group data, non-text subtypes, direct-message decryption and other application-specific payload decoding remain unsupported; unknown encrypted payloads stay classified as such. No messages, acknowledgments or advertisements are sent. [MeshCore packet format](https://github.com/meshcore-dev/MeshCore/blob/75b04ef06def54b348400cb1b138afb6749ffd4f/docs/packet_format.md), [MeshCore payload format](https://github.com/meshcore-dev/MeshCore/blob/75b04ef06def54b348400cb1b138afb6749ffd4f/docs/payloads.md).

## SD configuration

Start from [config.example.json](../sdcard/lora-tunnel/config.example.json), save the private working copy as `/lora-tunnel/config.json`, and choose your region on the device. New optional fields inside `lora` are:

```json
{
  "mode": "combined",
  "meshtastic_preset": "LONG_TURBO",
  "meshtastic_slot": 0,
  "dwell_ms": 30000,
  "meshcore_profile": "AUTO",
  "decode_public": true,
  "meshtastic_keys": [],
  "meshcore_keys": []
}
```

This fragment is not a complete configuration. It illustrates a US or ANZ LongTurbo selection, not a valid selection for every region. Merge it into the existing `lora` object and preserve unrelated settings. When changing a named preset, remove the old `frequency_mhz`, `bandwidth_khz`, `spreading_factor`, `coding_rate_denominator` and `preamble_symbols` fields so they derive from the new preset, or replace all five with consistent values. Conflicting raw and named settings are rejected. Using the on-device selectors saves consistent values automatically. Existing files without a mode remain Meshtastic-only; existing custom raw configurations are preserved.

Use `meshtastic_preset: "CUSTOM"` with `meshtastic_slot: 0` for literal raw radio settings. A custom channel name is independent of the modem preset and may select a different frequency slot on its transmitting nodes. Enter that actual slot; the receiver does not infer it from the private-key label. Save mode, presets, slots, dwell and keys on a working SD card. NVS recovery currently retains only the region choice and reconstructs its LongFast starting profile; it does not back up these additional settings or private keys. Keep a private SD configuration backup if exact recovery is required.

`decode_public` attempts the published Meshtastic default key and MeshCore Public group key. It also works with a renamed ordinary Meshtastic channel using that key, subject to supported framing. Setting it to false does not disable public MeshCore advert parsing or remove explicitly supplied keys for either protocol.

`meshtastic_keys` accepts at most four objects, each containing:

- `name`: the exact, case-sensitive channel name, 1–39 UTF-8 bytes. The channel name can differ from the modem preset name.
- `key_hex`: the expanded AES key as exactly 32 or 64 hexadecimal characters. An empty string explicitly configures plaintext for that channel. Base64 shortcuts such as `AQ==` are not accepted in this field; the published default is already covered by `decode_public`.

`meshcore_keys` independently accepts at most four objects. Each has a local descriptive `name` of 1–39 UTF-8 bytes and a `key_hex` containing exactly 32 or 64 hexadecimal characters. Empty/plaintext keys and Base64 shortcuts are not accepted. MeshCore derives its group hash from the first byte of SHA256 of the original 16-byte or 32-byte key; the local label is not part of the hash. The first 16 bytes supply AES-128, while the channel MAC uses the full key, zero-padded to 32 bytes when necessary.

Private channel keys are separate from WiGLE or WDGWars API credentials. Keys are read from the private SD configuration and are not included in observations, status output or examples. Configure these protocol keys through the SD file; the existing connection-key keyboard is for upload/network credentials. The firmware tries matching entries within a fixed bound. For Meshtastic, the eight-bit channel hash depends on both the exact name and key. Neither protocol's short channel hash establishes identity or successful decryption.

## Logs and trust

The session schema remains version 1 with optional decoder fields. Each LoRa observation retains the **receive-time** profile snapshot: frequency, bandwidth, SF, configured coding rate, sync word, preamble and LNA setting. A later profile change cannot relabel a queued packet. Configured coding rate is not an independently measured received coding rate.

`lora.raw_hex`, RSSI/SNR, packet length and candidate header fields remain available. New fields include `lora.protocol`, `lora.decoder_version`, `lora.payload_status`, and `lora.decoded`. The decoded object carries authentication/signature status and only available fields. Text replacement or truncation is explicit. See [the observation schema](../schemas/observation-v1.schema.json).

Receiver location remains in `gps`. A node's broadcast location is in `lora.decoded.advertised_position`. Do not substitute one for the other. A received relay does not place the original sender near the receiver. An invalid signature does not erase the raw observation, but the firmware does not promote it to a trusted node summary.

These additions do not by themselves establish WiGLE LoRa support or a WDGWars mesh upload contract. Exporters and live-service acceptance remain separate work; original logs must be retained.

## Capability and validation ledger

| Capability | This implementation |
| --- | --- |
| Standalone Wi-Fi/BLE/LoRa logging | Existing Wardriver capture path retained |
| Raw LoRa bytes and receive-time settings | Preserved for both protocols |
| Meshtastic names, positions, ordinary text and device metrics | Supported with compatible plaintext/default/configured-key AES-CTR payloads |
| MeshCore public adverts | Parsed, with Ed25519 signature result reported separately |
| One selected profile for each protocol in one session | Supported through slow automatic rotation |
| Meshtastic LongTurbo and eight other named presets | Implemented with default/explicit slot selection, occupied-band validation and legacy CUSTOM preservation; physical acceptance pending |
| Arbitrary hopping lists / all Kismet regions | Not implemented; combined mode rotates only the selected Meshtastic and MeshCore profiles |
| MeshCore encrypted group text | Implemented for Public or configured compatible keys; MAC result separate from sender authentication; physical acceptance pending |
| Meshtastic optional AEAD and XEdDSA verification | Not yet implemented |
| Private PKI direct-message decryption | Not available to a passive observer without endpoint secrets |
| Kismet server, datasource protocol or PCAP-NG compatibility | Not supplied by these changes; local capture remains JSONL |
| Continuous reception of two differing radio profiles | Requires separate receiver hardware |

Host tests exercise malformed/truncated packets, bounded lengths, missing fields, signed-coordinate encoding, default-key/nonce handling, explicit key configuration, wrong-key results, MeshCore path formats, signature verification, configuration recovery semantics and the scheduler. Added preset/configuration tests cover LongTurbo US/ANZ defaults, region and board bounds, invalid types and slots, conflicting raw fields, legacy CUSTOM retention and preservation of unrelated settings. Group fixtures exercise Public and configured keys, channel-MAC failure, padding and unsupported subtypes. Synthetic fixtures use invented node data and public/test keys. Firmware builds validate the pinned Heltec and Cardputer targets; compilation does not establish radio performance.

Before release acceptance, use a known transmitter for each protocol and compare its configured settings, name and advertised location against both raw and decoded records. Test LongFast and LongTurbo with their actual slots, public and configured-key messages, locked MeshCore reception and group text, then combined mode, including a packet spanning a scheduled change. Verify that each queued record retains the profile that received it, observe counters and UI responsiveness during SD writes, repeat stop/start and region/mode/preset changes, and verify SD persistence after reboot. Measure packet coverage and memory/stack headroom on both targets. These physical checks are pending; no new physical results should be claimed until those checks have evidence.
