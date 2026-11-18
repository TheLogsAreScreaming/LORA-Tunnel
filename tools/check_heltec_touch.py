"""Compile actual board touch readers against controlled I2C reports, without hardware."""
from pathlib import Path
import os
import subprocess
import tempfile

from check_cardputer_ui import ROOT, compiler
from check_lora_hopping import extract


def check():
    header = (ROOT / "include/hardware.h").read_text(encoding="utf-8")
    touch_state = extract(header, "enum class TouchState") + ";\n"
    fixture = (ROOT / "tests/hardware_touch_host/main.cpp").read_text(encoding="utf-8")
    if fixture.count("// TOUCH_IMPLEMENTATION") != 1:
        raise RuntimeError("Touch fixture marker is invalid")
    cxx = compiler()
    environment = os.environ.copy()
    environment["PATH"] = str(Path(cxx).parent) + os.pathsep + environment.get("PATH", "")
    results = []
    with tempfile.TemporaryDirectory(prefix="lora-touch-") as temporary:
        work = Path(temporary)
        for target, source_name, defines in (
            ("Heltec", "hardware.cpp", []),
            ("Cardputer", "hardware_cardputer.cpp", ["-DLORA_TUNNEL_CARDPUTER_ADV"]),
        ):
            source = (ROOT / "src" / source_name).read_text(encoding="utf-8")
            actual = touch_state + extract(source, "TouchState readTouch(") + "\n"
            actual += extract(source, "bool touch(") + "\n"
            unit = work / (target + ".cpp")
            unit.write_text(fixture.replace("// TOUCH_IMPLEMENTATION", actual), encoding="utf-8")
            binary = work / (target + (".exe" if os.name == "nt" else ""))
            command = [cxx, "-std=c++14", "-O1", "-Wall", "-Wextra", *defines, str(unit), "-o", str(binary)]
            if os.name == "nt":
                command += ["-static-libgcc", "-static-libstdc++"]
            subprocess.run(command, cwd=ROOT, env=environment, check=True)
            result = subprocess.run([str(binary)], cwd=ROOT, env=environment, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(target + ": " + result.stdout + result.stderr)
            results.append(target + ": " + result.stdout.strip())
    return "\n".join(results)


if __name__ == "__main__":
    print(check())
