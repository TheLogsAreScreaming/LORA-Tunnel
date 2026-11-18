#pragma once
#include <cstdint>
#include <cstddef>
#include <cstring>
extern uint32_t hostMillis;
inline uint32_t millis() { return hostMillis; }

using TaskHandle_t=void*;
static uintptr_t hostTaskIdentity=1;
inline TaskHandle_t xTaskGetCurrentTaskHandle() {return reinterpret_cast<TaskHandle_t>(hostTaskIdentity);}
inline size_t strlcpy(char* destination,const char* source,size_t size) {
  const size_t length=std::strlen(source);
  if(size) {const size_t copied=length<size-1?length:size-1;std::memcpy(destination,source,copied);destination[copied]=0;}
  return length;
}
#if !defined(LORA_TUNNEL_CARDPUTER_ADV)
struct HostSerial {void println(const char*){}};
static HostSerial Serial;
#endif
