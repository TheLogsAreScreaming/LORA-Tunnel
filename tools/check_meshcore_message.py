"""Compile and test the real MeshCore messaging adapter against fixed independent vectors."""
from pathlib import Path
import os
import subprocess
import tempfile
from check_mesh_crypto import compiler, crypto_directory

ROOT = Path(__file__).resolve().parents[1]


def main():
    cxx, crypto = compiler(), crypto_directory(None)
    environment = os.environ.copy()
    environment['PATH'] = str(Path(cxx).parent) + os.pathsep + environment.get('PATH', '')
    sources = ['AESCommon.cpp', 'AES128.cpp', 'BlockCipher.cpp', 'Crypto.cpp',
               'BigNumberUtil.cpp', 'Curve25519.cpp', 'Ed25519.cpp', 'Hash.cpp', 'SHA512.cpp', 'SHA256.cpp']
    if (crypto / 'utility/LimbUtil.cpp').is_file():
        sources.append('utility/LimbUtil.cpp')
    build = ROOT / '.pio/host-checks'
    build.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='meshcore-message-', dir=build) as temporary:
        binary = Path(temporary) / ('meshcore-message.exe' if os.name == 'nt' else 'meshcore-message')
        command = [cxx, '-std=c++14', '-O1', '-Wall', '-Wextra', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
                   '-I', str(ROOT / 'include'), '-I', str(ROOT / 'lib/meshdecode/src'), '-I', str(crypto),
                   str(ROOT / 'tests/meshcore_message_host/main.cpp'), str(ROOT / 'src/meshcore_message_crypto.cpp'),
                   str(ROOT / 'lib/meshdecode/src/MeshCoreMessage.cpp'), str(ROOT / 'lib/meshdecode/src/MeshCoreDecode.cpp')]
        # Compile vendored .c as C, exactly as the firmware build will, rather
        # than relying on g++'s different default treatment of .c input files.
        cc = Path(cxx).with_name('gcc.exe' if os.name == 'nt' else 'gcc')
        if not cc.is_file():
            cc = Path(cxx).with_name('clang.exe' if os.name == 'nt' else 'clang')
        if not cc.is_file():
            raise RuntimeError('A C compiler beside the C++ compiler is required.')
        for source in ['key_exchange.c', 'fe.c']:
            obj = Path(temporary) / (source + '.o')
            subprocess.run([str(cc), '-std=c99', '-O1', '-Wall', '-Wextra', '-ffunction-sections', '-fdata-sections',
                            '-c', str(ROOT / 'lib/meshdecode/src/meshcore_ed25519' / source), '-o', str(obj)],
                           cwd=ROOT, env=environment, check=True)
            command.append(str(obj))
        command.extend(str(crypto / source) for source in sources)
        command.extend(['-o', str(binary)])
        if os.name == 'nt':
            command.extend(['-static-libgcc', '-static-libstdc++'])
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
        subprocess.run([str(binary)], cwd=ROOT, env=environment, check=True)


if __name__ == '__main__':
    main()
