#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>
namespace nvs_fixture {
extern std::map<std::string,std::vector<std::uint8_t>> values;
extern bool failOpen,shortWrite,discardWrite,corruptRead,shortRead,wrongLength;
extern unsigned opens,closes;
}
class Preferences {
public:
  bool begin(const char* space,bool){if(std::strcmp(space,"lt-chat"))std::abort();++nvs_fixture::opens;return !nvs_fixture::failOpen;}
  void end(){++nvs_fixture::closes;}
  bool isKey(const char* key){return nvs_fixture::values.count(key)!=0;}
  std::size_t getBytesLength(const char* key){const auto it=nvs_fixture::values.find(key);return it==nvs_fixture::values.end()?0:it->second.size()+(nvs_fixture::wrongLength?1:0);}
  std::size_t putBytes(const char* key,const void* data,std::size_t n){
    if(nvs_fixture::shortWrite)return n? n-1:0;
    if(!nvs_fixture::discardWrite){const auto* p=static_cast<const std::uint8_t*>(data);nvs_fixture::values[key]=std::vector<std::uint8_t>(p,p+n);}return n;
  }
  std::size_t getBytes(const char* key,void* out,std::size_t n){
    const auto it=nvs_fixture::values.find(key);if(it==nvs_fixture::values.end()||it->second.size()!=n)return 0;
    std::memcpy(out,it->second.data(),n);if(n&&nvs_fixture::corruptRead)static_cast<std::uint8_t*>(out)[0]^=1;
    return nvs_fixture::shortRead&&n?n-1:n;
  }
};
