// Copyright (c) 2026 Valleytech Solutions. SPDX-License-Identifier: MIT
// ESP32 crypto adapter; wire codec remains Arduino-independent. The pinned
// rweather Curve25519 implementation rejects weak peer/shared points.
#include "meshtastic_message.h"
#include <Curve25519.h>
#include <mbedtls/aes.h>
#include <mbedtls/ccm.h>
#include <mbedtls/platform_util.h>
#include <mbedtls/sha256.h>
#include <cstring>

namespace tunnel { namespace meshtastic { namespace {
bool nonzero(const std::uint8_t* p,std::size_t n){std::uint8_t v=0;while(n--)v|=*p++;return v!=0;}
bool ctr(const std::uint8_t* key,std::size_t size,const std::uint8_t iv[16],const std::uint8_t* input,std::size_t n,std::uint8_t* output) {
  if(!key||!iv||!input||!output||(size!=16&&size!=32)||n>239)return false;
  mbedtls_aes_context ctx;mbedtls_aes_init(&ctx);
  std::uint8_t counter[16],stream[16]{};std::size_t offset=0;std::memcpy(counter,iv,16);
  const bool ok=mbedtls_aes_setkey_enc(&ctx,key,unsigned(size*8))==0&&
      mbedtls_aes_crypt_ctr(&ctx,n,&offset,counter,stream,input,output)==0;
  mbedtls_aes_free(&ctx);mbedtls_platform_zeroize(counter,16);mbedtls_platform_zeroize(stream,16);
  if(!ok)mbedtls_platform_zeroize(output,n);return ok;
}
bool derivePublic(const std::uint8_t privateKey[32],std::uint8_t publicKey[32]) {
  if(!privateKey||!publicKey)return false;
  if(!nonzero(privateKey,32)){mbedtls_platform_zeroize(publicKey,32);return false;}
  std::uint8_t scalar[32];std::memcpy(scalar,privateKey,32);scalar[0]&=248;scalar[31]=(scalar[31]&127)|64;
  const bool ok=Curve25519::eval(publicKey,scalar,nullptr)&&nonzero(publicKey,32);
  mbedtls_platform_zeroize(scalar,32);
  if(!ok)mbedtls_platform_zeroize(publicKey,32);return ok;
}
bool sharedKey(const std::uint8_t privateKey[32],const std::uint8_t remote[32],std::uint8_t output[32]) {
  if(!privateKey||!remote||!output)return false;
  std::uint8_t secret[32]{},shared[32]{};
  std::memcpy(secret,privateKey,32);std::memcpy(shared,remote,32);
  secret[0]&=248;secret[31]=(secret[31]&127)|64;
  const bool ok=nonzero(privateKey,32)&&Curve25519::dh2(shared,secret)&&
      mbedtls_sha256(shared,32,output,0)==0;
  mbedtls_platform_zeroize(secret,32);mbedtls_platform_zeroize(shared,32);
  if(!ok)mbedtls_platform_zeroize(output,32);return ok;
}
bool seal(const std::uint8_t key[32],const std::uint8_t nonce[13],const std::uint8_t* input,
          std::size_t n,std::uint8_t* output,std::uint8_t tag[8]) {
  if(!key||!nonce||!input||!output||!tag||!n||n>227)return false;
  mbedtls_ccm_context ctx;mbedtls_ccm_init(&ctx);
  const bool ok=mbedtls_ccm_setkey(&ctx,MBEDTLS_CIPHER_ID_AES,key,256)==0&&
      mbedtls_ccm_encrypt_and_tag(&ctx,n,nonce,13,nullptr,0,input,output,tag,8)==0;
  mbedtls_ccm_free(&ctx);
  if(!ok){mbedtls_platform_zeroize(output,n);mbedtls_platform_zeroize(tag,8);}return ok;
}
bool open(const std::uint8_t key[32],const std::uint8_t nonce[13],const std::uint8_t* input,
          std::size_t n,const std::uint8_t tag[8],std::uint8_t* output) {
  if(!key||!nonce||!input||!output||!tag||!n||n>227)return false;
  mbedtls_ccm_context ctx;mbedtls_ccm_init(&ctx);
  const bool ok=mbedtls_ccm_setkey(&ctx,MBEDTLS_CIPHER_ID_AES,key,256)==0&&
      mbedtls_ccm_auth_decrypt(&ctx,n,nonce,13,nullptr,0,input,output,tag,8)==0;
  mbedtls_ccm_free(&ctx);if(!ok)mbedtls_platform_zeroize(output,n);return ok;
}
bool hmac(const std::uint8_t key[32],const std::uint8_t* input,std::size_t n,std::uint8_t output[32]) {
  if(!key||!input||!output||n>239)return false;
  std::uint8_t pad[64],inner[32]{};std::memset(pad,0x36,64);for(unsigned i=0;i<32;++i)pad[i]^=key[i];
  mbedtls_sha256_context ctx;mbedtls_sha256_init(&ctx);
  bool ok=mbedtls_sha256_starts(&ctx,0)==0&&mbedtls_sha256_update(&ctx,pad,64)==0&&
      mbedtls_sha256_update(&ctx,input,n)==0&&mbedtls_sha256_finish(&ctx,inner)==0;
  for(auto& byte:pad)byte^=0x36^0x5c;
  ok=ok&&mbedtls_sha256_starts(&ctx,0)==0&&mbedtls_sha256_update(&ctx,pad,64)==0&&
      mbedtls_sha256_update(&ctx,inner,32)==0&&mbedtls_sha256_finish(&ctx,output)==0;
  mbedtls_sha256_free(&ctx);mbedtls_platform_zeroize(pad,64);mbedtls_platform_zeroize(inner,32);
  if(!ok)mbedtls_platform_zeroize(output,32);return ok;
} }
const Crypto& platformCrypto(){static const Crypto crypto{ctr,sharedKey,seal,open,derivePublic,hmac};return crypto;}
} }
