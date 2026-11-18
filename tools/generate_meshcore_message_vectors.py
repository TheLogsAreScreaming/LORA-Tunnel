"""Reproduce synthetic MeshCore chat vectors with independent cryptography.

No user keys, radio traffic or firmware implementation are read. Python's
cryptography Ed25519/X25519/AES and hashlib/hmac are independent of the C++
rweather + orlp implementations. Ed25519-to-Montgomery conversion uses the
public relation u=(1+y)/(1-y), as documented by the pinned MeshCore primitive.
Protocol reference: meshcore-dev/MeshCore 75b04ef06def54b348400cb1b138afb6749ffd4f.
Generated file is reviewed/committed, so the normal host test needs no Python
cryptographic dependencies and never generates or stores user identities.
"""
from pathlib import Path
import hashlib
import hmac
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT = Path(__file__).resolve().parents[1]


def public(seed):
    return ed25519.Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def shared(seed, peer):
    scalar = bytearray(hashlib.sha512(seed).digest()[:32])
    scalar[0] &= 248
    scalar[31] = (scalar[31] & 63) | 64
    p = 2**255 - 19
    y = int.from_bytes(peer, 'little') & (2**255 - 1)
    u = ((1 + y) * pow(1 - y, p - 2, p)) % p
    return x25519.X25519PrivateKey.from_private_bytes(bytes(scalar)).exchange(
        x25519.X25519PublicKey.from_public_bytes(u.to_bytes(32, 'little')))


def seal(secret, plain):
    plain += bytes((-len(plain)) % 16)
    cipher = Cipher(algorithms.AES(secret[:16]), modes.ECB()).encryptor()
    encrypted = cipher.update(plain) + cipher.finalize()
    return hmac.new(secret, encrypted, hashlib.sha256).digest()[:2] + encrypted


def main():
    a, b = bytes(range(1, 33)), bytes(range(65, 97))
    pa, pb = public(a), public(b)
    # Real valid third identity with the same one-byte wire hash as B.
    for nonce in range(10000):
        cs = hashlib.sha256(b'synthetic collision' + nonce.to_bytes(4, 'little')).digest()
        if public(cs)[0] == pb[0]:
            break
    else:
        raise RuntimeError('synthetic collision not found')
    secret = shared(a, pb)
    assert secret == shared(b, pa)
    stamp = (0x66554433).to_bytes(4, 'little')
    name, text = b'Alice', b'hello mesh'
    data = stamp + b'\0' + text
    ack = hashlib.sha256(data + pa).digest()[:4]
    advert_data = pa + stamp + b'\x81' + name
    signature = ed25519.Ed25519PrivateKey.from_private_bytes(a).sign(advert_data)
    group16 = bytes.fromhex('8b3387e9c5cdea6ac9e5edbaa115cd72')
    group32 = bytes(range(32))
    path = b'\xaa\xbb\xcc'
    values = {
        'seed_a': a, 'seed_b': b, 'seed_collision': cs,
        'pub_a': pa, 'pub_b': pb, 'pub_collision': public(cs),
        'shared_ab': secret, 'key32': group32,
        'advert_a': b'\x11\0' + pa + stamp + signature + b'\x81' + name,
        'direct_a_b': b'\x09\0' + pb[:1] + pa[:1] + seal(secret, data),
        'ack_a_b': ack,
        'path_b_a': b'\x21\0' + pa[:1] + pb[:1] + seal(secret, bytes([len(path)]) + path + b'\x03' + ack),
        'path_b_a_6': b'\x21\0' + pa[:1] + pb[:1] + seal(secret, bytes([len(path)]) + path + b'\x03' + ack + b'\x05\xfe'),
    }
    for label, key in [('group16', group16), ('group32', group32)]:
        secret_key = key.ljust(32, b'\0')
        values[label] = b'\x15\0' + hashlib.sha256(key).digest()[:1] + seal(secret_key, stamp + b'\0' + name + b': ' + text)
        values[label + '_fingerprint'] = hashlib.sha256(b'\x05' + values[label][2:]).digest()[:8]
    generated = ['// Synthetic independent vectors. Reproduce with tools/generate_meshcore_message_vectors.py.', '#pragma once', '#include <cstdint>', 'namespace vectors {']
    for label, data in values.items():
        generated.append('static const std::uint8_t ' + label + '[]={' + ','.join(f'0x{x:02x}' for x in data) + '};')
    generated.append('}')
    target = ROOT / 'tests/meshcore_message_host/vectors.h'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(('\n'.join(generated) + '\n').encode('utf8'))
    print(f'Wrote {len(values)} independent synthetic vectors')


if __name__ == '__main__':
    main()
