"""Print independent, synthetic fixtures; not run by the ordinary host check.

Uses Python cryptography (46.0.5 when generated), RFC7748 public test keys,
and protocol facts documented in meshtastic_message.h. Never reads user keys.
"""
import hashlib
import hmac
import struct
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

A = bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
B = bytes.fromhex("5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb")
alice, bob = X25519PrivateKey.from_private_bytes(A), X25519PrivateKey.from_private_bytes(B)
key = hashlib.sha256(alice.exchange(bob.public_key())).digest()
KEY16 = bytes.fromhex("d4f1bb3a20290759f0bcffabcf4e6901")
KEY32 = bytes(range(32))
FROM, TO, PACKET, EXTRA = 0x12345678, 0x9abcdef0, 0x10203040, 0x50607080

def header(to, sender, packet, channel, ack=False):
    return struct.pack("<IIIBBBB", to, sender, packet, 0x63 | (8 if ack else 0), channel, 0, 0)

def channel(payload, secret, channel_hash, to=0xffffffff, sender=FROM, packet=PACKET, ack=True):
    nonce = struct.pack("<IIII", packet, 0, sender, 0)
    if secret:
        enc = Cipher(algorithms.AES(secret), modes.CTR(nonce)).encryptor()
        payload = enc.update(payload) + enc.finalize()
    return header(to, sender, packet, channel_hash, ack) + payload

def emit(name, data):
    print(f'constexpr const char* {name}="{data.hex()}";')

print("// SPDX-License-Identifier: MIT\n// Independently generated synthetic fixtures; see generate_vectors.py.\nnamespace fixture {")
for name, data in [("alicePrivate", A), ("bobPrivate", B),
                   ("alicePublic", alice.public_key().public_bytes_raw()),
                   ("bobPublic", bob.public_key().public_bytes_raw()), ("shared", key)]:
    emit(name, data)
plain = b"\x08\x01\x12\x0bHello mesh!"
emit("clear", channel(plain, b"", 0x5a))
emit("channel16", channel(plain, KEY16, 8))
emit("channel32", channel(plain, KEY32, 0x42))
nonce = struct.pack("<III", PACKET, EXTRA, FROM) + b"\0"
emit("privateText", header(TO, FROM, PACKET, 0, True) + AESCCM(key, tag_length=8).encrypt(nonce, plain, None) + struct.pack("<I", EXTRA))
for name, error in [("ack", 0), ("nak", 3)]:
    routing = bytes([0x18, error])
    proof = hmac.digest(key, b"ack" + struct.pack("<III", TO, FROM, PACKET) + routing, "sha256")[:8]
    payload = routing + b"\x22\x08" + proof
    data = b"\x08\x05\x12" + bytes([len(payload)]) + payload + b"\x35" + struct.pack("<I", PACKET)
    emit(name, channel(data, KEY16, 8, to=FROM, sender=TO, packet=PACKET+1, ack=False))
print("}")
