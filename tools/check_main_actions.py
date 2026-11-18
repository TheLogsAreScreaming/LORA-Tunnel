"""Run actual main-loop actions and capture-stop lifecycle against host fakes.

Extracts those functions verbatim; no firmware build, SD, serial or RF access.
"""
from pathlib import Path
import os
import subprocess
import tempfile
from check_cardputer_ui import ROOT, compiler


def block(source, marker):
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
        end += 1
    return source[start:end]


def check():
    main = (ROOT / "src/main.cpp").read_text(encoding="utf-8")
    declarations = block(main, "enum class MessageOwner") + ";\n"
    declarations += block(main, "struct Action {") + ";\n"
    declarations += block(main, "struct ChatActionDiagnostics") + " chatActions;\n"
    callbacks = "\n".join(block(main, marker) for marker in (
        "void callback(ui::Action", "void requestSession()", "void serviceCaptureStorage()", "void performActions()"))
    # Exercise the actual loop's Stop-marker retry/completion block as well.
    callbacks += "\nvoid completeStopForTest(){\n" + block(main[main.index("void loop() {"):], "if(stopping)") + "\n}\n"
    fixture = (ROOT / "tests/main_action_host/main.cpp.in").read_text(encoding="utf-8")
    fixture = fixture.replace("// @MAIN_DECLARATIONS@", declarations).replace("// @MAIN_ACTIONS@", callbacks)
    cxx = compiler()
    environment = os.environ.copy()
    environment["PATH"] = str(Path(cxx).parent) + os.pathsep + environment.get("PATH", "")
    with tempfile.TemporaryDirectory(prefix="lora-main-actions-") as temporary:
        source = Path(temporary) / "main.cpp"
        binary = Path(temporary) / ("main.exe" if os.name == "nt" else "main")
        source.write_text(fixture, encoding="utf-8")
        command = [cxx, "-std=c++14", "-O1", "-Wall", "-Wextra", "-I", str(ROOT / "include"), str(source), "-o", str(binary)]
        if os.name == "nt":
            command += ["-static-libgcc", "-static-libstdc++"]
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
        result = subprocess.run([str(binary)], cwd=ROOT, env=environment, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout.strip()


if __name__ == "__main__":
    print(check())
