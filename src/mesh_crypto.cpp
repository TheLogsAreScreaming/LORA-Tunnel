#include <TunnelMeshDecode.h>
#include "mesh_signature.h"
#include <mbedtls/aes.h>
#include <mbedtls/platform_util.h>
#include <mbedtls/sha256.h>
#include <Ed25519.h>
#include <cstring>

namespace tunnel { namespace mesh {
namespace {
bool ctr(const uint8_t* key,size_t keyLength,const uint8_t iv[16],
         const uint8_t* input,size_t length,uint8_t* output) {
  if(!key || !iv || !input || !output || (keyLength!=16 && keyLength!=32) || length>239)return false;
  mbedtls_aes_context ctx;
  mbedtls_aes_init(&ctx);
  uint8_t nonce[16],stream[16]{}; size_t offset=0;
  memcpy(nonce,iv,16);
  const bool ok=mbedtls_aes_setkey_enc(&ctx,key,unsigned(keyLength*8))==0 &&
      mbedtls_aes_crypt_ctr(&ctx,length,&offset,nonce,stream,input,output)==0;
  mbedtls_platform_zeroize(nonce,sizeof(nonce));
  mbedtls_platform_zeroize(stream,sizeof(stream));
  mbedtls_aes_free(&ctx);
  if(!ok)mbedtls_platform_zeroize(output,length);
  return ok;
}
bool verify(const uint8_t key[32],const uint8_t signature[64],const uint8_t* message,size_t length) {
  if(!key || !signature || !message || length>239)return false;
  if(!ed25519InputsAllowed(key,signature))return false;
  return Ed25519::verify(signature,key,message,length);
}
bool ecb(const uint8_t key[16],const uint8_t* input,size_t length,uint8_t* output) {
  if(!key || !input || !output || !length || length>176 || length%16)return false;
  mbedtls_aes_context ctx;
  mbedtls_aes_init(&ctx);
  bool ok=mbedtls_aes_setkey_dec(&ctx,key,128)==0;
  for(size_t offset=0;ok && offset<length;offset+=16)
    ok=mbedtls_aes_crypt_ecb(&ctx,MBEDTLS_AES_DECRYPT,input+offset,output+offset)==0;
  mbedtls_aes_free(&ctx);
  if(!ok)mbedtls_platform_zeroize(output,length);
  return ok;
}
bool hmac(const uint8_t* key,size_t keyLength,const uint8_t* input,size_t length,uint8_t output[32]) {
  if(!key || keyLength!=32 || !input || length>176 || !output)return false;
  // Fixed-size MeshCore secret: RFC2104 HMAC with stack-only SHA256 contexts,
  // avoiding mbedtls_md_hmac's per-packet context allocation on the Cardputer.
  uint8_t pad[64],inner[32]{};
  memset(pad,0x36,sizeof(pad));
  for(size_t i=0;i<keyLength;++i)pad[i]^=key[i];
  mbedtls_sha256_context ctx;
  mbedtls_sha256_init(&ctx);
  bool ok=mbedtls_sha256_starts(&ctx,0)==0 &&
      mbedtls_sha256_update(&ctx,pad,sizeof(pad))==0 &&
      mbedtls_sha256_update(&ctx,input,length)==0 &&
      mbedtls_sha256_finish(&ctx,inner)==0;
  for(size_t i=0;i<sizeof(pad);++i)pad[i]^=0x36^0x5c;
  ok=ok && mbedtls_sha256_starts(&ctx,0)==0 &&
      mbedtls_sha256_update(&ctx,pad,sizeof(pad))==0 &&
      mbedtls_sha256_update(&ctx,inner,sizeof(inner))==0 &&
      mbedtls_sha256_finish(&ctx,output)==0;
  mbedtls_sha256_free(&ctx);
  mbedtls_platform_zeroize(pad,sizeof(pad));
  mbedtls_platform_zeroize(inner,sizeof(inner));
  if(!ok)mbedtls_platform_zeroize(output,32);
  return ok;
}
bool sha256(const uint8_t* input,size_t length,uint8_t output[32]) {
  if(!input || (length!=16 && length!=32) || !output)return false;
  const bool ok=mbedtls_sha256(input,length,output,0)==0;
  if(!ok)mbedtls_platform_zeroize(output,32);
  return ok;
}
}
const Crypto& platformCrypto() {
  static const Crypto crypto{ctr,verify,ecb,hmac,sha256}; return crypto;
}
} }
