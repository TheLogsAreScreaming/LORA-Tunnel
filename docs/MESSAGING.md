# Meshtastic and MeshCore messaging candidate

This describes the local **0.6.0-dev.chat1 candidate** for Heltec V4-R8 / Expansion V2 and Cardputer ADV + U214. The new two-way messaging paths have **not passed physical peer-radio testing**. Host tests and synthetic screen previews demonstrate software behavior; they do not establish on-air interoperability, RF output power, battery behavior, or delivery reliability. The published 0.5.0 downloads and manifests remain unchanged by this work.

Messages is a separate operating mode. Stop Wardriver or Recon, wait for its session to finish saving, then open **Home → Messages** and select **Meshtastic** or **MeshCore**. On Cardputer, **C** on Home opens Messages. The one SX1262 radio listens to one protocol/profile at a time. Combined wardriving remains a receive-only alternating scan mode; it does not provide simultaneous messaging or simultaneous reception of both networks. Wi-Fi/BLE wardriving is stopped while Messages owns the radio.

## Controls and configuration

Both displays provide Inbox, Write to channel, Contacts, Messaging settings, Enable transmission, Announce my identity, My identity / radio, Change protocol, and Stop messages / Home. Heltec uses touch or KEY/USER navigation and its touchscreen keyboard. Cardputer uses directional/Fn-arrow navigation, Enter, Escape, and physical text entry with modifiers and Backspace. Compose and message details wrap up to 120 printable ASCII text bytes. Escape/Cancel wipes an unsent draft. Leaving the Messages menu for Home stops messaging; it does not automatically restart capture.

Match the peer radio's region, modulation preset and frequency slot in **Settings → Mesh radio / decode settings** before opening Messages. A channel name/key and a radio preset are different settings. **My identity / radio** shows the current channel, radio profile and local public identity; none of these screens expose private identity seeds.

The `messaging` object in `/lora-tunnel/config.json` contains:

```json
"messaging": {
  "name": "LORA Tunnel",
  "meshtastic_channel": "",
  "meshtastic_key_hex": "",
  "meshcore_key_hex": "",
  "hop_limit": 3
}
```

| Setting | Accepted value and meaning |
| --- | --- |
| `name` | 1–31 printable ASCII bytes without a colon. Display names are not authenticated identities. |
| `meshtastic_channel` | Up to 39 printable ASCII bytes, case-sensitive. Blank is AUTO: the selected preset's default channel name. |
| `meshtastic_key_hex` | Blank selects the published Meshtastic default channel key. A custom key is exactly 32 or 64 hexadecimal digits. Blank does **not** select plaintext. |
| `meshcore_key_hex` | Blank selects the published MeshCore Public group key. A custom key is exactly 32 or 64 hexadecimal digits. |
| `hop_limit` | Integer 0–7 for Meshtastic. It does not change MeshCore routing. |

These are independent from the receive-only decoder's `lora.meshtastic_keys` and `lora.meshcore_keys` lists, and from home Wi-Fi/upload credentials. Key editors always start blank, mask typed values, and explain that saving blank restores the public default. Saved custom channel keys are plaintext on the private SD card. Public source/starter packaging rejects any nonempty messaging key, including an explicitly expanded public key; leave both example fields blank.

TX permission is runtime-only and starts **OFF** for each messaging session and boot. Enable it through the separate confirmation screen before sending or announcing. Config files cannot authorize TX: imported `enabled` and `tx_enabled` fields are ignored by the firmware, and the public schema rejects true values. Switching protocol or leaving Messages clears transmit permission. With TX disabled the firmware does not send announcements, messages, retries or receipt replies.

## Contacts, trust and delivery

The candidate keeps up to **eight contacts shared between both protocols**. An observed name or announcement does not establish who controls a device. Open a contact, compare its entire 32-byte public key with its owner through a trusted route, and explicitly confirm **Review / trust public key**. A changed key is shown as changed and blocks private composition until reviewed again. Trust/forget actions bind the displayed key as well as the slot, so a changed contact cannot silently reuse a queued decision. Select the contact's protocol before composing privately.

Local Meshtastic/MeshCore identity material and contact/trust records use the application's **`lt-chat` NVS namespace**. They survive normal restarts and application changes that preserve NVS. They are private device data, not release artifacts; never publish a full-flash device backup as an installation image. Other applications' NVS namespaces are not used for messaging storage.

The inbox is a bounded **six-record RAM history**, not a permanent message archive. Leaving Messages wipes its history and pending message state. A pending private message can occupy the single outgoing slot until receipt, timeout or cancellation; the candidate makes at most three attempts. The status text distinguishes:

| Status | Meaning |
| --- | --- |
| Queued / Sending | Waiting for the radio or currently transmitting. |
| Sent (unconfirmed) | The local channel transmission completed. No recipient delivery is established. |
| Waiting for receipt | A private transmission completed and is waiting for a matching receipt. |
| Delivered | A matching authenticated private receipt was validated. This does not establish that a person read the message. |
| Receipt (unverified) | A matching legacy/unverified receipt was observed; it is not promoted to authenticated delivery. |
| Failed / no receipt | A local failure or exhausted receipt attempts. |
| Cancelled | Transmission permission or the pending operation was cancelled. |

MeshCore sends and identity announcements require a fresh GNSS UTC time. The candidate refuses sends when that time is unavailable or inconsistent with its persisted timestamp history. Private MeshCore reception also requires valid GNSS UTC before acknowledging or advancing a saved replay watermark; channel reception and signed contact discovery remain available without UTC. Neither an empty location nor a clock failure is replaced with fabricated coordinates/time.

## Radio and acceptance limits

This candidate uses **0 dBm raw SX1262 chip drive on both boards**. The Heltec V4-R8 has an external KCT8103L PA and attenuation network: raw chip drive is not measured antenna-port power. Its PA output has not been calibrated in this candidate. The U214 follows its own TCXO/RF-switch setup and 868–923 MHz hardware range. The full occupied bandwidth must fit the configured region and board before the radio starts.

The current software policy keeps RU and unknown/unhandled regions receive-only. It enforces at least five seconds between user sends/announcements, a bounded outgoing slot, channel assessment, and airtime-derived spacing. EU_868/TH use a 10% spacing parameter; UA_868/MY_919 use 1%; other explicitly supported entries use 100%. Spacing debt survives mode changes but is RAM-only and resets at reboot; it is not a persistent rolling-hour airtime ledger. These values describe the implementation, not measured airtime utilization or a regulatory certification. They do not establish collision-free reception or successful delivery.

Physical acceptance still needs both installation routes and real peer radios: Meshtastic channel/private messaging and announcements; MeshCore channel/private messaging, advert trust and receipts; changed-key rejection; TX-off silence; protocol changes; failed/transmit-timeout recovery back to RX; restart identity/trust persistence; GNSS-time refusal/recovery; and sustained UI/radio operation on each board. Keep test message contents, channel keys and device backups private. Do not label the candidate as a validated release until those results have been recorded for its exact binaries.

## Implementation provenance

[SquachWatch-CYD at `35244470`](https://github.com/skizzophrenic/SquachWatch-CYD/tree/35244470f890f170ef4b6588cee87b2c0407f495) was considered as a feature reference. LORA Tunnel's messaging UI, state handling and protocol adapters were implemented independently; SquachWatch GPL application source was not imported into this MIT project.

The MeshCore Ed25519 key-exchange/field-arithmetic primitive comes from [MeshCore `75b04ef`, `lib/ed25519`](https://github.com/meshcore-dev/MeshCore/tree/75b04ef06def54b348400cb1b138afb6749ffd4f/lib/ed25519), originally by [Orson Peters](https://github.com/orlp/ed25519), under its permissive zlib license. Its unmodified source, [retained license](../lib/meshdecode/src/meshcore_ed25519/license.txt) and [provenance notice](../lib/meshdecode/src/meshcore_ed25519/README.md) are included in source packages. Package validation requires both notices whenever that primitive source is present. Other dependency notices and relinking materials remain covered by [THIRD_PARTY.md](THIRD_PARTY.md) and [RELINKING.md](RELINKING.md).

## Reproducing the messaging host checks

The messaging tests require Python, a C/C++ host compiler, and the project's pinned Crypto/ArduinoJson dependencies installed by a firmware build. Meshtastic and engine tests also compile a portable Mbed TLS source tree. CI fetches official [Mbed TLS v3.6.1 at commit `71c569d44bf3a8bd53d874c81ee8ac644dd6e9e3`](https://github.com/Mbed-TLS/mbedtls/tree/71c569d44bf3a8bd53d874c81ee8ac644dd6e9e3), verifies the checked-out commit, and stores it under the ignored `build-output/host-deps/mbedtls-3.6.1` directory. This checkout is used only by host tests; it does not replace or modify the production ESP32 SDK.

Set `MESSAGING_MBEDTLS_DIR` to that checkout's absolute path, then run:

```text
python tools/check_meshtastic_message.py
python tools/check_meshcore_message.py
python tools/check_messaging.py
python tools/check_messaging_radio.py
```

An explicit `--mbedtls-dir` on the Meshtastic runner takes precedence over the environment variable. If neither is set, the tools look for an installed local ESP-IDF Mbed TLS 3.6 source tree. An invalid explicit path or environment setting fails instead of silently selecting a different dependency. The tools themselves perform no downloads or device operations. Radio tests simulate IRQ, bus and frontend behavior; they do not establish physical peer interoperability.
