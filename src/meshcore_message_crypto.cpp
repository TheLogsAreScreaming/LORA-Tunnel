// SPDX-License-Identifier: MIT
// Original adapter to pinned rweather/Crypto 0.4.0 (MIT) and the unmodified
// Orson Peters key-exchange primitive (zlib; provenance/license beside source).
// The latter consumes expanded Ed25519 scalar bytes, not the persistent seed.
#include "meshcore_message.h"
#include "mesh_signature.h"
#include "meshcore_ed25519/ed_25519.h"
#include <AES.h>
#include <Ed25519.h>
#include <SHA256.h>
#include <SHA512.h>
#include <cstring>

namespace tunnel { namespace meshcore_message {
namespace {
void wipe(void* data,std::size_t n){volatile std::uint8_t* p=static_cast<volatile std::uint8_t*>(data);while(n--)*p++=0;}
bool publicKey(const std::uint8_t seed[32],std::uint8_t pub[32]){
  if(!seed || !pub)return false;
  Ed25519::derivePublicKey(pub,seed);return mesh::signature_detail::pointAllowed(pub);
}
bool sign(const std::uint8_t seed[32],const std::uint8_t pub[32],const std::uint8_t* msg,std::size_t n,std::uint8_t sig[64]){
  if(!seed || !pub || !msg || !sig || n>68)return false;
  std::uint8_t derived[32];Ed25519::derivePublicKey(derived,seed);
  const bool matches=std::memcmp(derived,pub,32)==0;wipe(derived,sizeof(derived));
  if(!matches){wipe(sig,64);return false;}
  Ed25519::sign(sig,seed,pub,msg,n);return true;
}
bool verify(const std::uint8_t pub[32],const std::uint8_t sig[64],const std::uint8_t* msg,std::size_t n){
  return msg && n<=68 && mesh::ed25519InputsAllowed(pub,sig) && Ed25519::verify(sig,pub,msg,n);
}
bool shared(const std::uint8_t seed[32],const std::uint8_t peer[32],std::uint8_t out[32]){
  if(!out)return false;
  wipe(out,32);
  if(!seed || !peer || !mesh::signature_detail::pointAllowed(peer))return false;
  std::uint8_t expanded[64];SHA512 sha;sha.update(seed,32);sha.finalize(expanded,sizeof(expanded));sha.clear();
  // MeshCore's keypair expands SHA512(seed), clamps its first 32 bytes, and
  // passes that scalar to ed25519_key_exchange; this primitive clamps again.
  ed25519_key_exchange(out,peer,expanded);wipe(expanded,sizeof(expanded));
  unsigned nonzero=0;for(unsigned i=0;i<32;++i)nonzero|=out[i];return nonzero!=0;
}
bool sha256(const std::uint8_t* input,std::size_t n,std::uint8_t out[32]){
  if(!input || !out || n>256)return false;
  SHA256 sha;sha.update(input,n);sha.finalize(out,32);sha.clear();return true;
}
bool hmac(const std::uint8_t key[32],const std::uint8_t* input,std::size_t n,std::uint8_t out[32]){
  if(!key || !input || !out || !n || n>176)return false;
  SHA256 sha;sha.resetHMAC(key,32);sha.update(input,n);sha.finalizeHMAC(key,32,out,32);sha.clear();return true;
}
bool ecb(bool encrypt,const std::uint8_t key[16],const std::uint8_t* input,std::size_t n,std::uint8_t* out){
  if(!key || !input || !out || !n || n>176 || n%16)return false;
  AES128 aes;if(!aes.setKey(key,16))return false;
  for(std::size_t i=0;i<n;i+=16){if(encrypt)aes.encryptBlock(out+i,input+i);else aes.decryptBlock(out+i,input+i);}
  aes.clear();return true;
}
}
const Crypto& platformCrypto(){static const Crypto c{publicKey,sign,verify,shared,sha256,hmac,ecb};return c;}
} }
