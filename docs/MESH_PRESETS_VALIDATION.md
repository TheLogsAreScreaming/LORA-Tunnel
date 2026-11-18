# Mesh preset and group decoding development validation

Candidate: **0.6.0-dev**, 2026-11-17. This is a development build; the published
0.5.0 downloads and their acceptance records remain separate.

The change adds nine named Meshtastic presets and automatic/manual frequency
slots, including US LongTurbo at 908.750 MHz, 500 kHz, SF11, CR4/8. Settings also
select Meshtastic, MeshCore or alternating reception, the MeshCore profile,
combined dwell, and public-default decoding. One receiver listens to one profile
at a time. Configuration details and protocol references are in
[COMBINED_MESH.md](COMBINED_MESH.md).

## Software evidence

| Check | Result |
| --- | --- |
| Native parser, profiles and state tests | 189 passed |
| Python tests, including the actual pinned SDK linker checks | 114 passed, none skipped |
| Web installer Node tests | 7 passed |
| Schemas and shipped examples | 3 schemas and 9 example documents/records validated |
| Cardputer UI | 568 checks; one 32,400-byte screen buffer retained |
| Heltec UI | 2,159 touch/button/focus/draw-bound checks |
| Actual scanner transition functions | 76 checks per board |
| Actual configuration save/load/failure paths | Cardputer 529; Heltec 176 checks |
| Actual logger capacity | 34 checks; maximum projected target JSON arena use 3,084/4,096 bytes |
| Capture queues and AP inventory | 173 and 278 checks; ingress/writer records remain 1,328/1,648 bytes |
| Uploader worker, offline transport | Cardputer 17,127; Heltec 16,869 checks; no requests sent |
| Session and BLE maintenance lifecycle | 97 and 42 checks |
| Cardputer pinned keyboard headers | 214 checks; all 95 printable ASCII characters reachable |
| Both firmware targets | Compiled with the pinned framework/dependencies |
| Cardputer factory/application images | Layout, identity, version, checksum and size validation passed |

Crypto fixtures use independent AES-CTR, AES-ECB, HMAC-SHA256 and Ed25519 vectors.
They cover Meshtastic LongFast, LongTurbo and renamed channels; MeshCore Public
and configured 16/32-byte group keys; malformed frames; key collisions; and
MAC/ciphertext/signature tampering. MeshCore's two-byte shared-channel MAC is
reported separately from sender authentication. Group sender names remain
self-reported. Unsupported or unknown encrypted content remains raw evidence.

Regression checks cover atomic saves, backup recovery, missing/corrupt key
sources, unchanged credentials/unknown fields, occupied bandwidth on both
boards, float rounding at valid regional edges, retained receive-time packet
settings, and packets completing during a profile change. Source and web
packagers reject nonempty example key lists for either protocol.

## Physical evidence and remaining checks

The connected Heltec identified itself as the Expansion V2 target running 0.5.0
with capture stopped and SD, touch and LoRa ready. Its full 16 MiB flash was
backed up locally before installation. The partition-table MD5 and all four
bootloader/application image checksums and SHA-256 digests validated. Private
flash/SD content is excluded from public source packages.

The candidate exceeds the old LORA Tunnel Launcher slot by 12,192 bytes. It must
be installed into an adequately sized partition; writing it over that old slot
would overlap another application. Launcher reports version `dev` on the test
unit. Its USB application installer acknowledged all candidate bytes. The host
did not receive the final OK line before its timeout, so that result alone was
not treated as proof of installation. A fresh USB query subsequently confirmed
0.6.0-dev running, capture stopped, SD/touch/LoRa ready, and zero reported errors,
drops or allocation failures. Idle free heap was 100,696 bytes, largest internal
block 59,380, and loop/writer stack watermarks 4,296/6,496 bytes. These are idle
samples, not sustained capture measurements.

LongTurbo and MeshCore over-the-air decoding, physical settings persistence,
updated UI operation, and sustained operation of this candidate are pending.
Cardputer physical acceptance is also pending. Host vectors and compilation do
not certify RF coverage, device heap/stack margins, or successful delivery of a
particular transmitted message.
