"""Exercise the real Heltec mesh settings UI with bounded host drawing.

Touch/button events, paging, staged saves and cancellation use production code.
Synthetic previews are layout evidence only; hardware acceptance is separate.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

from check_cardputer_ui import ROOT, compiler, render


def check(output: Path) -> str:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lora-heltec-mesh-ui-") as temporary:
        binary = Path(temporary) / ("ui-test.exe" if os.name == "nt" else "ui-test")
        cxx = compiler()
        command = [cxx, "-std=c++14", "-O1", "-Wall", "-Wextra", "-ffunction-sections", "-fdata-sections",
                   "-DLORA_TUNNEL_HOST_UI", "-I", str(ROOT / "tests/ui_host"), "-I", str(ROOT / "include"),
                   "-I", str(ROOT / "lib/recon/src"), str(ROOT / "tests/ui_host/heltec_mesh_ui.cpp"),
                   "-Wl,--gc-sections", "-o", str(binary)]
        if os.name == "nt":
            command.extend(("-static-libgcc", "-static-libstdc++"))
        environment = os.environ.copy()
        environment["PATH"] = str(Path(cxx).parent) + os.pathsep + environment.get("PATH", "")
        subprocess.run(command, cwd=ROOT, check=True, env=environment)
        result = subprocess.run([str(binary), str(output)], cwd=ROOT, capture_output=True, text=True, env=environment)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout.strip()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build-output/heltec-mesh-ui")
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    print(check(args.output))
    if args.render:
        render(args.output, size=(240, 320), rgb332=False)
