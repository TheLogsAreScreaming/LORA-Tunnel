"""Regenerate public synthetic MeshCore group fixtures, independently of C++.

Optional fixture maintenance only (requires Python cryptography). The regular
host check needs no Python cryptography package. No actual user keys/data used.
Wire reference: meshcore-dev/MeshCore 75b04ef06def54b348400cb1b138afb6749ffd4f,
src/Utils.cpp, src/Mesh.cpp and src/helpers/BaseChatMesh.cpp.
"""
import hashlib
import hmac
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def packet(key: bytes, timestamp: int, flags: int, text: bytes) -> str:
    plain = timestamp.to_bytes(4, "little") + bytes([flags]) + text
    plain += bytes((-len(plain)) % 16)
    encryptor = Cipher(algorithms.AES(key[:16]), modes.ECB()).encryptor()
    encrypted = encryptor.update(plain) + encryptor.finalize()
    mac = hmac.new(key.ljust(32, b"\0"), encrypted, hashlib.sha256).digest()[:2]
    return (b"\x15\x00" + hashlib.sha256(key).digest()[:1] + mac + encrypted).hex()


if __name__ == "__main__":
    public = bytes.fromhex("8b3387e9c5cdea6ac9e5edbaa115cd72")
    print("public", packet(public, 0x65543210, 0, b"Bench: hello turbo"))
    print("custom16", packet(bytes(range(16)), 0, 3, b"Other: private group"))
    print("custom32", packet(bytes(range(32)), 0x65543210, 0, b"Full: 32 byte channel"))
