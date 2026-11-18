#pragma once
// Minimal portable configuration for the host test only. Firmware uses SDK config.
#define MBEDTLS_AES_C
#define MBEDTLS_CIPHER_C
#define MBEDTLS_CIPHER_MODE_CTR
#define MBEDTLS_CCM_C
#define MBEDTLS_SHA256_C
#define MBEDTLS_PLATFORM_C
