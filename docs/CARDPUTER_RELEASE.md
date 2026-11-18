# Cardputer release packaging

The current release is **0.6.0** for **Cardputer ADV with Cap LoRa-1262 (U214)**. The [release notes](RELEASE_0_6_0.md) describe its features and known limitations; [CARDPUTER_ADV.md](CARDPUTER_ADV.md) covers installation and controls. The [0.5.0 release record](RELEASE_0_5_0.md) and [earlier Cardputer measurements](CARDPUTER_SOFTWARE_VALIDATION.md) remain historical evidence.

## Build and package

```sh
python -m platformio run -e cardputer-adv-lora1262
python tools/package_cardputer.py --build .pio/build/cardputer-adv-lora1262 --check-only
python tools/package_cardputer.py --build .pio/build/cardputer-adv-lora1262 --output dist/cardputer-0.6.0 --version 0.6.0
python tools/package_source.py dist/LORA-Tunnel-0.6.0-source.zip
python tools/package_relink.py package 0.6.0 dist/LORA-Tunnel-0.6.0-Cardputer-ADV-LoRa1262-relink.zip --env cardputer-adv-lora1262
```

Package the final committed source. The site builder checks every source-archive file against its commit and binds the dependency companion to the exact factory image. Cardputer packaging verifies the ESP32-S3 image checksums/digests, 8 MB partition layout, blank factory NVS, target identity and application size. The Launcher app must equal the factory image's application at `0x10000`.

| File | Installation route |
| --- | --- |
| `LORA-Tunnel-0.6.0-Cardputer-ADV-LoRa1262-FACTORY-0x0.bin` | USB, web installer or M5Burner at address zero; replaces Launcher |
| `LORA-Tunnel-0.6.0-Cardputer-ADV-LoRa1262-LAUNCHER-APP.bin` | Bmorcelli Launcher SD menu; Launcher chooses the destination partition |

Provide both files, the source archive, board-specific dependency/relinking archive, empty-credential SD starter and SHA-256 checksum list. Do not publish flash backups or private SD configuration. Older release artifacts remain immutable.

## Publication record

Full hardware acceptance is separate from release authorization with disclosed limitations. A stable release record uses `result: scoped-release` with its exact `version`, target, factory/application hashes, explicit `publication_authorized`, authorization date, passed software checks, and a nonempty `unverified_checks` list. Record `usb_application_verified` truthfully for the exact release binary. The builder rejects an old `scoped-beta` record for a stable version. Pending checks must not be marked as passed.

For the owner-authorized 0.6.0 promotion, an uninstalled final image uses `usb_application_verified: false`, `publication_basis: "owner-authorized-software-release"`, a nonempty `authorization_note`, and the exact entry `"Physical installation of the exact release image"` in `unverified_checks`. Its `candidate_reference` identifies the same target, version `0.6.0-dev.chat5`, source commit `b113b9e4230553bcf909a75018a5578209bf20a4`, and that candidate's actual USB verification result: true for the Heltec application and false for Cardputer. This reference preserves the distinction between prior candidate evidence and final-image testing; it does not convert owner acceptance into a hardware test result.

The complete acceptance checklist includes display/keyboard, known-source RF, GPS-valid saved observations, power/wake, sustained capture, browser factory flashing, Launcher installation/return and live service receipts. A stable version label does not substitute for these results.

## Two-target web installer

Create a private schema-2 catalog containing the Heltec and Cardputer entries. Each entry includes its version, full source commit, paths and SHA-256 hashes for factory/source/relink artifacts, and a publication record. Each target also supplies its application BIN/hash for Launcher downloads. Each board has its own factory manifest, hardware requirements and guide. The site source may be shared when both targets use the same source release.

```sh
python tools/build_web.py --catalog dist/catalog-0.6.0.json --output build-output/web-0.6.0
```

`--local-preview` permits local review of unpublished candidates; that output must not be deployed. A normal build requires publication evidence for each enabled target. Validate links, hardware switching, confirmation reset and download hashes before deploying. ESP32-S3 chip detection cannot identify which board or cap is attached.

## M5Burner

Update the existing **LORA Tunnel — Cardputer ADV + Cap LoRa-1262** listing at [burner.m5stack.com](https://burner.m5stack.com/). Select Cardputer ADV and upload the factory image. Link the GitHub release and mention the U214 requirement, microSD setup, region selection, LongTurbo/configurable receive profiles, Messages with TX off by default, and the separate Launcher download. Disclose the current peer-testing and storage limits in the release notes. Retain the project logo/cover and professional description.

Submission and public catalog approval are different states. Record the version and actual dashboard result; do not claim public availability while review is pending. Do not upload the Heltec factory image or the Launcher application as the M5Burner standalone firmware.

## Verification after publishing

Check the GitHub release, production installer catalog/manifests and every public download against local SHA-256 hashes. Update Gitea by ordinary manual upload or an authorized Git push; do not use repository migration. Verify M5Burner submission state separately. Keep device-specific captures, credentials and recovery images outside public artifacts.
