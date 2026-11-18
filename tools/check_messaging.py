"""Exercise the actual messaging engine with real protocol and crypto adapters.

Only persistence, entropy and allocation are replaced by deterministic in-memory
host fakes. No device, files from microSD, user secrets, network or serial access.
"""
from pathlib import Path
import os
import subprocess
import tempfile
from check_mesh_crypto import ROOT, compiler, crypto_directory
from check_meshtastic_message import mbedtls_directory


def main():
    cxx, crypto, mbedtls = compiler(), crypto_directory(None), mbedtls_directory(None)
    cc = str(Path(cxx).with_name(Path(cxx).name.replace('g++', 'gcc').replace('clang++', 'clang')))
    environment = os.environ.copy()
    environment['PATH'] = str(Path(cxx).parent) + os.pathsep + environment.get('PATH', '')
    json_dir = ROOT / '.pio/libdeps/heltec-v4-r8-tft/ArduinoJson/src'
    if not json_dir.is_dir():
        raise RuntimeError('The existing pinned ArduinoJson dependency must be installed.')
    flags = ['-O1', '-Wall', '-Wextra', '-ffunction-sections', '-fdata-sections',
             '-DMBEDTLS_CONFIG_FILE="meshtastic_message_mbedtls_config.h"',
             '-I', str(ROOT / 'tests/meshtastic_message_host'), '-I', str(mbedtls / 'include'), '-I', str(mbedtls / 'library')]
    build = ROOT / '.pio/host-checks'
    build.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='messaging-engine-', dir=build) as temporary:
        temporary = Path(temporary)
        objects = []
        c_sources = [mbedtls / f'library/{name}.c' for name in ['aes', 'ccm', 'cipher', 'cipher_wrap', 'platform', 'platform_util', 'sha256', 'constant_time']]
        c_sources += [ROOT / 'lib/meshdecode/src/meshcore_ed25519' / name for name in ['fe.c', 'key_exchange.c']]
        for number, source in enumerate(c_sources):
            obj = temporary / f'c{number}.o'
            subprocess.run([cc, '-std=c99', *flags, '-c', str(source), '-o', str(obj)], cwd=ROOT, env=environment, check=True)
            objects.append(str(obj))
        binary = temporary / ('messaging.exe' if os.name == 'nt' else 'messaging')
        command = [cxx, '-std=c++14', *flags, '-Wl,--gc-sections', '-I', str(ROOT / 'include'),
                   '-I', str(ROOT / 'lib/meshdecode/src'), '-I', str(crypto), '-I', str(json_dir)]
        command += [str(ROOT / source) for source in ['tests/messaging_host/main.cpp', 'src/messaging.cpp',
                    'src/meshtastic_message_crypto.cpp', 'src/meshcore_message_crypto.cpp',
                    'lib/meshdecode/src/MeshtasticMessage.cpp', 'lib/meshdecode/src/MeshCoreMessage.cpp', 'lib/meshdecode/src/MeshCoreDecode.cpp']]
        command += [str(crypto / name) for name in ['AESCommon.cpp', 'AES128.cpp', 'BlockCipher.cpp', 'Crypto.cpp', 'BigNumberUtil.cpp',
                                                  'Curve25519.cpp', 'Ed25519.cpp', 'Hash.cpp', 'SHA512.cpp', 'SHA256.cpp', 'utility/LimbUtil.cpp']
                    if (crypto / name).is_file()]
        command += objects + ['-o', str(binary)]
        if os.name == 'nt':
            command += ['-static-libgcc', '-static-libstdc++']
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
        subprocess.run([str(binary)], cwd=ROOT, env=environment, check=True)
        storage_binary = temporary / ('messaging-storage.exe' if os.name == 'nt' else 'messaging-storage')
        storage_command = [cxx, '-std=c++14', '-O1', '-Wall', '-Wextra',
                           '-I', str(ROOT / 'tests/messaging_host/storage_fakes'), '-I', str(ROOT / 'include'), '-I', str(json_dir),
                           str(ROOT / 'tests/messaging_host/storage_main.cpp'), str(ROOT / 'src/messaging_storage.cpp'), '-o', str(storage_binary)]
        if os.name == 'nt':
            storage_command += ['-static-libgcc', '-static-libstdc++']
        subprocess.run(storage_command, cwd=ROOT, env=environment, check=True)
        subprocess.run([str(storage_binary)], cwd=ROOT, env=environment, check=True)


if __name__ == '__main__':
    main()
