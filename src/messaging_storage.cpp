#include "messaging.h"
#include "resource_memory.h"
#include <Preferences.h>
#include <esp_system.h>
#include <cstring>

namespace tunnel { namespace messaging {
namespace {
Load load(const char* key,void* bytes,std::size_t size) {
  Preferences prefs;
  if(!prefs.begin("lt-chat",false))return Load::Invalid;
  const bool present=prefs.isKey(key);
  const bool ok=present&&prefs.getBytesLength(key)==size&&prefs.getBytes(key,bytes,size)==size;
  prefs.end();return !present?Load::Missing:ok?Load::Ok:Load::Invalid;
}
bool save(const char* key,const void* bytes,std::size_t size) {
  if(size>1024)return false;
  Preferences prefs;
  if(!prefs.begin("lt-chat",false))return false;
  bool ok=prefs.putBytes(key,bytes,size)==size;
  std::uint8_t verified[1024]{};
  ok=ok&&prefs.getBytesLength(key)==size&&prefs.getBytes(key,verified,size)==size&&
      !std::memcmp(bytes,verified,size);
  volatile auto* p=verified;for(std::size_t i=0;i<sizeof(verified);++i)p[i]=0;
  prefs.end();return ok;
}
void* allocate(std::size_t bytes){return allocatePayload(bytes);}
void release(void* bytes){heap_caps_free(bytes);}
}
const Storage& platformStorage(){static const Storage store{load,save,esp_random,allocate,release};return store;}
} }
