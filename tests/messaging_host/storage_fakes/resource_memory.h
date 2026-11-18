#pragma once
#include <cstddef>
#include <cstdlib>
inline void* allocatePayload(std::size_t n){return std::malloc(n);}
inline void heap_caps_free(void* p){std::free(p);}
