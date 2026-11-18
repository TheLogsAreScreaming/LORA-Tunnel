#pragma once
#include <ArduinoJson.h>
#include <cstring>
#include "mesh_config.h"

namespace tunnel { namespace messaging {
struct Settings {
  char name[32]="LORA Tunnel", meshtastic_channel[40]{}; // Empty = current preset name.
  std::uint8_t meshtastic_key[32]{}, meshcore_key[32]{};
  std::uint8_t meshtastic_key_length=0, meshcore_key_length=0; // Empty = public key.
  std::uint8_t hop_limit=3;
};
inline bool printable(const char* text,std::size_t maximum,bool empty=false) {
  if(!text)return false;
  const auto length=std::strlen(text);
  if(length>maximum || (!empty&&!length))return false;
  for(std::size_t i=0;i<length;++i)if(static_cast<unsigned char>(text[i])<32 || static_cast<unsigned char>(text[i])>126)return false;
  return true;
}
inline bool readText(JsonVariantConst value,char* out,std::size_t capacity,bool empty=false) {
  if(!value.is<const char*>())return false;
  const JsonString text=value.as<JsonString>();
  if(text.size()!=std::strlen(text.c_str()) || !printable(text.c_str(),capacity-1,empty))return false;
  std::memcpy(out,text.c_str(),text.size()+1);return true;
}
inline bool readHex(const char* text,std::uint8_t out[32],std::uint8_t& length) {
  if(!text)return false;
  const std::size_t n=std::strlen(text);
  if(n!=0 && n!=32 && n!=64)return false;
  std::memset(out,0,32);length=std::uint8_t(n/2);
  for(std::size_t i=0;i<length;++i) {
    const int a=meshHex(text[2*i]),b=meshHex(text[2*i+1]);
    if(a<0||b<0)return false;
    out[i]=std::uint8_t(a*16+b);
  }
  return true;
}
inline bool readKey(JsonVariantConst value,std::uint8_t out[32],std::uint8_t& length) {
  if(!value.is<const char*>())return false;
  const auto text=value.as<JsonString>();
  return text.size()==std::strlen(text.c_str()) && readHex(text.c_str(),out,length);
}
inline bool parseSettings(JsonVariantConst root,Settings& output) {
  Settings value;
  if(!root.containsKey("messaging")){output=value;return true;}
  const JsonVariantConst section=root["messaging"];
  if(!section.is<JsonObjectConst>())return false;
  if(section.containsKey("name")&&!readText(section["name"],value.name,sizeof(value.name)))return false;
  if(std::strchr(value.name,':'))return false;
  if(section.containsKey("meshtastic_channel")&&!readText(section["meshtastic_channel"],value.meshtastic_channel,sizeof(value.meshtastic_channel),true))return false;
  if(section.containsKey("meshtastic_key_hex")&&!readKey(section["meshtastic_key_hex"],value.meshtastic_key,value.meshtastic_key_length))return false;
  if(section.containsKey("meshcore_key_hex")&&!readKey(section["meshcore_key_hex"],value.meshcore_key,value.meshcore_key_length))return false;
  if(section.containsKey("hop_limit")) {
    if(!section["hop_limit"].is<unsigned>()||section["hop_limit"].as<unsigned>()>7)return false;
    value.hop_limit=section["hop_limit"];
  }
  // Imported enabled/tx_enabled flags never grant transmit permission. It is a
  // deliberate runtime action, reset when leaving Messages and at each boot.
  output=value;return true;
}
inline bool sameSettings(const Settings& a,const Settings& b) {
  return !std::strcmp(a.name,b.name)&&!std::strcmp(a.meshtastic_channel,b.meshtastic_channel)&&
      a.hop_limit==b.hop_limit&&a.meshtastic_key_length==b.meshtastic_key_length&&
      a.meshcore_key_length==b.meshcore_key_length&&
      !std::memcmp(a.meshtastic_key,b.meshtastic_key,32)&&!std::memcmp(a.meshcore_key,b.meshcore_key,32);
}
inline bool validSettings(const Settings& value) {
  if(!std::memchr(value.name,0,sizeof(value.name))||!std::memchr(value.meshtastic_channel,0,sizeof(value.meshtastic_channel)))return false;
  const auto validLength=[](unsigned n){return n==0||n==16||n==32;};
  return printable(value.name,31)&&!std::strchr(value.name,':')&&printable(value.meshtastic_channel,39,true)&&
      validLength(value.meshtastic_key_length)&&validLength(value.meshcore_key_length)&&value.hop_limit<=7;
}
inline void writeSettings(JsonVariant root,const Settings& value) {
  root["messaging"]["name"]=value.name;
  root["messaging"]["meshtastic_channel"]=value.meshtastic_channel;
  root["messaging"]["hop_limit"]=value.hop_limit;
  char hex[65]{};const char digits[]="0123456789abcdef";
  for(unsigned k=0;k<2;++k) {
    const auto* bytes=k?value.meshcore_key:value.meshtastic_key;
    const auto length=k?value.meshcore_key_length:value.meshtastic_key_length;
    for(unsigned i=0;i<length;++i){hex[2*i]=digits[bytes[i]>>4];hex[2*i+1]=digits[bytes[i]&15];}
    hex[2*length]=0;
    root["messaging"][k?"meshcore_key_hex":"meshtastic_key_hex"]=hex;
  }
  volatile char* p=hex;for(auto& ch:hex){(void)ch;*p++=0;}
}
} }
