"""Release companions must bind the Cardputer linker inputs and exact output."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import package_relink as relink
import package_source


class CardputerLinkerCompanionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lora-relink-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.build = self.root / "build"
        self.output = self.build / "cardputer_linker"
        self.output.mkdir(parents=True)
        (self.root / "tools").mkdir()
        policy = self.root / "linker/cardputer/esp-idf-v5.5.5"
        policy.mkdir(parents=True)
        for name in ("freertos.lf", "esp_ringbuf.lf", "provenance.json"):
            (policy / name).write_text("pinned fixture")
        for name in relink.CARDPUTER_BUILD_SCRIPTS:
            (self.root / name).write_text("fixture input")
        # This adapter isolates collection/binding logic; the actual generator
        # has independent tests against the pinned archives and placement policy.
        (self.root / "tools/cardputer_linker.py").write_text(
            "import hashlib,json\nfrom pathlib import Path\n"
            "ROOT=Path(__file__).resolve().parents[1]\n"
            "def generate(sdk,objdump,output):\n"
            " inputs=ROOT/'expected-tools.json'\n"
            " if inputs.exists():\n"
            "  assert json.loads(inputs.read_text())=={'sdk':str(sdk),'objdump':str(objdump)}\n"
            " output.mkdir(parents=True,exist_ok=True)\n"
            " report=json.loads((ROOT/'expected-report.json').read_text())\n"
            " (output/'sections.ld').write_bytes(b'exact portable linker script')\n"
            " (output/'report.json').write_text(json.dumps(report))\n"
            " return report\n"
            "def verify(output,map_path,elf_path):\n"
            " return {'map_sha256':hashlib.sha256(map_path.read_bytes()).hexdigest(),"
            "'elf_sha256':hashlib.sha256(elf_path.read_bytes()).hexdigest()}\n")
        self.report = {"schema": 1, "target": relink.CARDPUTER_ENV, "generator_sha256": "fixture"}
        (self.root / "expected-report.json").write_text(json.dumps(self.report))
        (self.output / "report.json").write_text(json.dumps(self.report))
        (self.output / "sections.ld").write_bytes(b"exact portable linker script")
        (self.build / "firmware.map").write_bytes(b"verified map")
        (self.build / "firmware.elf").write_bytes(b"matching elf")
        self.verification = {
            "map_sha256": hashlib.sha256(b"verified map").hexdigest(),
            "elf_sha256": hashlib.sha256(b"matching elf").hexdigest(),
        }
        (self.output / "verification.json").write_text(json.dumps(self.verification))

    def collect(self):
        return relink.cardputer_linker_entries(self.root, self.build)

    def test_complete_portable_inventory_and_no_evidence_mutation(self):
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        entries = self.collect()
        names = {name for name, _ in entries}
        for name in relink.CARDPUTER_BUILD_SCRIPTS:
            self.assertIn("build-inputs/" + name, names)
        for name in relink.CARDPUTER_LINKER_OUTPUTS:
            self.assertIn("build-metadata/cardputer_linker/" + name, names)
        self.assertIn("build-inputs/linker/cardputer/esp-idf-v5.5.5/freertos.lf", names)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})
        self.assertFalse(any(str(self.root) in name for name in names))

    def test_generated_script_drift_rejected(self):
        (self.output / "sections.ld").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            self.collect()

    def test_source_report_drift_rejected(self):
        (self.root / "expected-report.json").write_text(json.dumps({**self.report, "generator_sha256": "new"}))
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            self.collect()

    def test_wrong_build_elf_or_map_rejected(self):
        for name in ("firmware.elf", "firmware.map"):
            with self.subTest(name=name):
                path = self.build / name
                before = path.read_bytes()
                path.write_bytes(b"different build")
                with self.assertRaisesRegex(ValueError, "exact ELF/map"):
                    self.collect()
                path.write_bytes(before)

    def test_missing_post_link_verification_rejected(self):
        (self.output / "verification.json").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "verification.json"):
            self.collect()

    def test_source_archive_contains_linker_rebuild_inputs(self):
        names = {p.relative_to(ROOT).as_posix() for p in package_source.collect_paths(ROOT)}
        self.assertTrue(set(relink.CARDPUTER_BUILD_SCRIPTS) <= names)
        for name in ("freertos.lf", "esp_ringbuf.lf", "provenance.json"):
            self.assertIn("linker/cardputer/esp-idf-v5.5.5/" + name, names)

    def test_application_source_hashes_bind_cardputer_build_inputs_only(self):
        card = relink.application_hashes(ROOT, relink.CARDPUTER_ENV)
        heltec = relink.application_hashes(ROOT, relink.ENV)
        for name in relink.CARDPUTER_BUILD_SCRIPTS:
            self.assertIn(name, card)
            self.assertNotIn(name, heltec)
        self.assertIn("linker/cardputer/esp-idf-v5.5.5/provenance.json", card)
        self.assertNotIn("linker/cardputer/esp-idf-v5.5.5/provenance.json", heltec)

    def test_heltec_collector_does_not_require_cardputer_linker(self):
        framework = self.root / ".pio-core/packages/framework-arduinoespressif32"
        framework.mkdir(parents=True)
        (framework / "package.json").write_text(json.dumps({"version": "3.3.12"}))
        for name in relink.LIBRARIES:
            (self.root / ".pio/libdeps" / relink.ENV / name).mkdir(parents=True)
        platform = self.root / ".pio-core/platforms/espressif32/platform.json"
        platform.parent.mkdir(parents=True)
        platform.write_text("{}")
        with patch.object(relink, "cardputer_linker_entries", side_effect=AssertionError("Card hook used")):
            entries = relink.collect(self.root, relink.ENV)
        self.assertFalse(any("cardputer_linker" in name for name, _ in entries))

    def install_core_fixture(self, core, env=relink.ENV):
        framework = core / "packages/framework-arduinoespressif32"
        framework.mkdir(parents=True)
        (framework / "package.json").write_text(json.dumps({"version": "3.3.12"}))
        (framework / "core-source.cpp").write_text("matching external framework")
        platform = core / "platforms/espressif32/platform.json"
        platform.parent.mkdir(parents=True)
        platform.write_text("{}")
        tool = core / "packages/toolchain-xtensa-esp-elf/package.json"
        tool.parent.mkdir(parents=True)
        tool.write_text("{}")
        names = relink.CARDPUTER_LIBRARIES if env == relink.CARDPUTER_ENV else relink.LIBRARIES
        for name in names:
            folder = self.root / ".pio/libdeps" / env / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "library.properties").write_text("version=4.5.0\n")
            (folder / "source.cpp").write_text("isolated application dependency")
        return core.resolve()

    def test_explicit_core_does_not_change_source_or_library_root(self):
        core = self.install_core_fixture(self.root / "external-core")
        stale = self.root / ".pio-core/packages/framework-arduinoespressif32"
        stale.mkdir(parents=True)
        (stale / "package.json").write_text('{"version":"wrong"}')
        entries = dict(relink.collect(self.root, core_dir=core))
        self.assertEqual(entries["framework/core-source.cpp"], core / "packages/framework-arduinoespressif32/core-source.cpp")
        self.assertEqual(entries["sdk-metadata/package.json"], core / "packages/framework-arduinoespressif32-libs/package.json")
        self.assertEqual(entries["build-metadata/platform.json"], core / "platforms/espressif32/platform.json")
        self.assertEqual(entries["build-metadata/toolchain-xtensa-esp-elf.json"], core / "packages/toolchain-xtensa-esp-elf/package.json")
        self.assertEqual(entries["libraries/Crypto/source.cpp"], self.root / ".pio/libdeps" / relink.ENV / "Crypto/source.cpp")
        self.assertEqual(entries["RELINKING.md"], self.root / "docs/RELINKING.md")
        self.assertFalse(any(str(core) in name for name in entries))

    def test_cardputer_collector_forwards_explicit_core_and_exact_build(self):
        core = self.install_core_fixture(self.root / "external-core", relink.CARDPUTER_ENV)
        with patch.object(relink, "cardputer_linker_entries", return_value=[]) as hook:
            relink.collect(self.root, relink.CARDPUTER_ENV, self.build, core)
        hook.assert_called_once_with(self.root, self.build, core)

    def test_cardputer_linker_uses_explicit_sdk_and_objdump(self):
        core = self.root / "external-core"
        objdump = core / "packages/toolchain-xtensa-esp-elf/bin/xtensa-esp32s3-elf-objdump.exe"
        objdump.parent.mkdir(parents=True)
        objdump.write_bytes(b"fixture executable, never run")
        (self.root / "expected-tools.json").write_text(json.dumps({
            "sdk": str(core / "packages/framework-arduinoespressif32-libs/esp32s3"),
            "objdump": str(objdump),
        }))
        entries = dict(relink.cardputer_linker_entries(self.root, self.build, core))
        self.assertEqual(entries["build-inputs/tools/cardputer_linker.py"], self.root / "tools/cardputer_linker.py")

    def test_explicit_missing_core_fails_without_local_fallback(self):
        self.install_core_fixture(self.root / ".pio-core")
        with self.assertRaises(FileNotFoundError):
            relink.collect(self.root, core_dir=self.root / "missing-core")

    def test_default_core_ignores_platformio_environment(self):
        core = self.install_core_fixture(self.root / ".pio-core")
        with patch.dict(os.environ, {"PLATFORMIO_CORE_DIR": str(self.root / "wrong-core")}):
            entries = dict(relink.collect(self.root))
        self.assertEqual(entries["framework/package.json"], core / "packages/framework-arduinoespressif32/package.json")

    def test_package_threads_explicit_core_without_changing_root(self):
        args = SimpleNamespace(root=self.root, output=self.root / "not-created.zip",
                               env=relink.ENV, build=self.build, core_dir=self.root / "external-core")
        with patch.object(relink, "collect", side_effect=RuntimeError("collection boundary")) as collect:
            with self.assertRaisesRegex(RuntimeError, "collection boundary"):
                relink.package(args)
        collect.assert_called_once_with(self.root.resolve(), relink.ENV, self.build.resolve(), args.core_dir)
        self.assertFalse(args.output.exists())

    def test_package_preserves_legacy_namespace_without_core_argument(self):
        args = SimpleNamespace(root=self.root, output=self.root / "not-created.zip", env=relink.ENV, build=None)
        with patch.object(relink, "collect", side_effect=RuntimeError("collection boundary")) as collect:
            with self.assertRaisesRegex(RuntimeError, "collection boundary"):
                relink.package(args)
        collect.assert_called_once_with(self.root.resolve(), relink.ENV, self.root / ".pio/build" / relink.ENV, None)

    def test_cli_accepts_explicit_core_path(self):
        core = self.root / "external core"
        argv = ["package_relink.py", "package", "0.6.0-dev.chat2", str(self.root / "not-created.zip"),
                "--root", str(self.root), "--core-dir", str(core), "--build", str(self.build)]
        with patch.object(sys, "argv", argv), patch.object(relink, "package") as package:
            relink.main()
        args = package.call_args.args[0]
        self.assertEqual(args.core_dir, core)
        self.assertEqual(args.root, self.root)
        self.assertEqual(args.build, self.build)


if __name__ == "__main__":
    unittest.main()
