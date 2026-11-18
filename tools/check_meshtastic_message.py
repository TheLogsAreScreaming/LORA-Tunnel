"""Test the real Meshtastic codec AND production crypto adapter on the host.

Uses local rweather/Crypto 0.4.0 and a local portable Mbed TLS 3.6 source tree.
No network, user keys, SD files, radio, Arduino build or device access occurs.
The ESP32 hardware-specific Mbed TLS acceleration still needs device testing.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
from check_mesh_crypto import ROOT, compiler, crypto_directory


def mbedtls_directory(explicit: Path | None) -> Path:
    if explicit:
        candidates = [explicit]
    elif os.environ.get("MESSAGING_MBEDTLS_DIR"):
        # CI supplies a separately pinned portable source checkout. Do not
        # replace or modify the production SDK, or silently ignore a bad path.
        candidates = [Path(os.environ["MESSAGING_MBEDTLS_DIR"])]
    else:
        packages = Path.home() / ".platformio/packages"
        candidates = sorted(packages.glob("framework-espidf*/components/mbedtls/mbedtls"))
    for candidate in candidates:
        info = candidate / "include/mbedtls/build_info.h"
        if (candidate / "library/ccm.c").is_file() and info.is_file() and '"3.6.' in info.read_text():
            return candidate
    raise RuntimeError("Provide --mbedtls-dir or MESSAGING_MBEDTLS_DIR pointing to a local Mbed TLS 3.6 source tree.")


def check(crypto: Path, mbedtls: Path) -> str:
    cxx = compiler()
    cc = str(Path(cxx).with_name(Path(cxx).name.replace("g++", "gcc").replace("clang++", "clang")))
    environment = os.environ.copy()
    environment["PATH"] = str(Path(cxx).parent) + os.pathsep + environment.get("PATH", "")
    include = ROOT / "tests/meshtastic_message_host"
    flags = ["-O1", "-Wall", "-Wextra", "-ffunction-sections", "-fdata-sections",
             '-DMBEDTLS_CONFIG_FILE="meshtastic_message_mbedtls_config.h"', "-I", str(include),
             "-I", str(mbedtls / "include"), "-I", str(mbedtls / "library")]
    build_root = ROOT / ".pio/host-checks"
    build_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="meshtastic-message-", dir=build_root) as temporary:
        temporary = Path(temporary)
        objects = []
        for name in ["aes", "ccm", "cipher", "cipher_wrap", "platform", "platform_util", "sha256", "constant_time"]:
            output = temporary / (name + ".o")
            subprocess.run([cc, "-std=c99", *flags, "-c", str(mbedtls / f"library/{name}.c"), "-o", str(output)],
                           cwd=ROOT, env=environment, check=True)
            objects.append(str(output))
        binary = temporary / ("meshtastic-message.exe" if os.name == "nt" else "meshtastic-message")
        command = [cxx, "-std=c++14", *flags, "-Wl,--gc-sections", "-I", str(ROOT / "include"),
                   "-I", str(crypto), str(include / "main.cpp"),
                   str(ROOT / "lib/meshdecode/src/MeshtasticMessage.cpp"),
                   str(ROOT / "src/meshtastic_message_crypto.cpp")]
        command += [str(crypto / source) for source in
                    ["Crypto.cpp", "BigNumberUtil.cpp", "Curve25519.cpp", "utility/LimbUtil.cpp"]
                    if (crypto / source).is_file()]
        command += objects + ["-o", str(binary)]
        if os.name == "nt": command += ["-static-libgcc", "-static-libstdc++"]
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
        completed = subprocess.run([str(binary)], cwd=ROOT, env=environment, check=False, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(f"Message fixtures failed ({completed.returncode}):\n{completed.stdout}{completed.stderr}")
        return completed.stdout.strip()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crypto-dir", type=Path)
    parser.add_argument("--mbedtls-dir", type=Path)
    args = parser.parse_args()
    print(check(crypto_directory(args.crypto_dir), mbedtls_directory(args.mbedtls_dir)))
