#pragma once
#include "ui.h"
#include "lora_profiles.h"
#include "lora_scan.h"
#include <cstdio>
#include <cstring>

// Shared, allocation-free choice construction for the touch and keyboard UIs.
// Selecting/navigating an option never writes configuration; each layout emits
// exactly one action only when its explicit Save/Enter control is activated.
namespace ui { namespace mesh_settings {
enum Field : unsigned { Protocol, Preset, Slot, MeshCore, Dwell, PublicDecode, FieldCount };
constexpr const char* fieldTitles[]={"PROTOCOL", "MESHTASTIC PRESET", "FREQUENCY SLOT", "MESHCORE PROFILE", "SCAN DWELL", "PUBLIC DECODING"};
constexpr uint32_t dwellValues[]={30000,60000,120000,300000,600000};
struct Option {
  Action action=Action::SaveLoRaMode;
  int value=0;
  const char* text="";
  bool available=false;
  char label[48]{};
  char detail[48]{};
};
inline const char* blockedReason(const Model& m) {
  if(m.running)return "Stop capture before changing settings";
  if(m.upload_busy)return "Wait for the upload to finish";
  if(!m.sd)return "Insert SD to save mesh settings";
  if(!m.region_configured)return "Choose a LoRa region first";
  return "";
}
inline bool editable(const Model& m) { return !m.shutting_down && !blockedReason(m)[0]; }
inline const char* modeName(unsigned mode) { return mode==1?"MeshCore":mode==2?"Both / alternating":"Meshtastic"; }
inline unsigned count(unsigned field,const Model& m) {
  switch(field) {
    case Protocol:return 3;
    case Preset:return unsigned(tunnel::lora_profiles::modemPresetCount);
    case Slot:return unsigned(m.meshtastic_slots)+1;
    case MeshCore:{ unsigned n=1; for(const auto& p:tunnel::lora_scan::meshCoreProfiles)
      if(!std::strcmp(p.region,m.region) && tunnel::lora_scan::meshCoreProfile(m.region,p.name))++n; return n; }
    case Dwell:return sizeof(dwellValues)/sizeof(dwellValues[0]);
    case PublicDecode:return 2;
    default:return 0;
  }
}
inline const tunnel::lora_scan::MeshCoreProfile* meshCoreChoice(const Model& m,unsigned index) {
  if(!index)return tunnel::lora_scan::meshCoreProfile(m.region,"AUTO");
  for(const auto& p:tunnel::lora_scan::meshCoreProfiles)
    if(!std::strcmp(p.region,m.region) && tunnel::lora_scan::meshCoreProfile(m.region,p.name) && !--index)return &p;
  return nullptr;
}
inline Option option(unsigned field,unsigned index,const Model& m) {
  Option out;
  if(index>=count(field,m))return out;
  out.available=true;
  switch(field) {
    case Protocol:
      out.action=Action::SaveLoRaMode;out.value=int(index);
      std::snprintf(out.label,sizeof(out.label),"%s",modeName(index));
      out.available=!index || tunnel::lora_scan::meshCoreProfile(m.region,m.meshcore_profile);
      std::snprintf(out.detail,sizeof(out.detail),"%s",index==2?"One radio alternates; packets may miss":index==1?"Listen only on the MeshCore profile":"Listen only on the Meshtastic preset");
      break;
    case Preset:{
      const auto& p=tunnel::lora_profiles::modemPresets[index];
      out.action=Action::SaveMeshtasticPreset;out.text=p.code;
      std::snprintf(out.label,sizeof(out.label),"%s",p.name);
      tunnel::lora_profiles::Profile radio{};
      out.available=tunnel::lora_profiles::makeProfile(m.region,p.code,m.meshtastic_slot,radio) && tunnel::lora_profiles::selectable(radio);
      if(out.available)std::snprintf(out.detail,sizeof(out.detail),"%.3f MHz / %.0f kHz SF%u 4/%u",radio.frequency_mhz,radio.bandwidth_khz,unsigned(radio.sf),unsigned(radio.cr));
      else std::snprintf(out.detail,sizeof(out.detail),"Does not fit region, radio or slot");
      break;
    }
    case Slot:{
      out.action=Action::SaveMeshtasticSlot;out.value=int(index);
      if(index)std::snprintf(out.label,sizeof(out.label),"Slot %u",index);
      else std::snprintf(out.label,sizeof(out.label),"AUTO / preset default");
      tunnel::lora_profiles::Profile radio{};
      out.available=m.meshtastic_slots && tunnel::lora_profiles::makeProfile(m.region,m.meshtastic_preset,uint16_t(index),radio) && tunnel::lora_profiles::selectable(radio);
      if(out.available)std::snprintf(out.detail,sizeof(out.detail),"%.3f MHz / slot %u",radio.frequency_mhz,unsigned(radio.frequency_slot));
      else std::snprintf(out.detail,sizeof(out.detail),"Outside radio band / choose preset");
      break;
    }
    case MeshCore:{
      const auto* p=meshCoreChoice(m,index);
      out.action=Action::SaveMeshCoreProfile;out.text=index && p?p->name:"AUTO";out.available=p!=nullptr;
      std::snprintf(out.label,sizeof(out.label),"%s",out.text);
      if(p)std::snprintf(out.detail,sizeof(out.detail),"%.3f MHz / %.1f kHz SF%u 4/%u",p->frequency_mhz,p->bandwidth_khz,unsigned(p->sf),unsigned(p->cr));
      else std::snprintf(out.detail,sizeof(out.detail),"No MeshCore profile for this region");
      break;
    }
    case Dwell:
      out.action=Action::SaveLoRaDwell;out.value=int(dwellValues[index]);
      std::snprintf(out.label,sizeof(out.label),"%lu seconds per profile",static_cast<unsigned long>(dwellValues[index]/1000));
      std::snprintf(out.detail,sizeof(out.detail),"Used only by Both / alternating");break;
    case PublicDecode:
      out.action=Action::SavePublicDecode;out.value=int(index);
      std::snprintf(out.label,sizeof(out.label),"Public channel decoding %s",index?"ON":"OFF");
      std::snprintf(out.detail,sizeof(out.detail),"Supplied private keys still apply");break;
  }
  return out;
}
inline unsigned selected(unsigned field,const Model& m) {
  if(field==Protocol)return m.lora_mode<3?m.lora_mode:0;
  if(field==Slot)return m.meshtastic_slot<=m.meshtastic_slots?m.meshtastic_slot:0;
  if(field==PublicDecode)return m.decode_public?1:0;
  for(unsigned i=0;i<count(field,m);++i) {
    const Option o=option(field,i,m);
    if(field==Preset && !std::strcmp(o.text,m.meshtastic_preset))return i;
    if(field==MeshCore && !std::strcmp(o.text,m.meshcore_profile))return i;
    if(field==Dwell && uint32_t(o.value)==m.lora_dwell_ms)return i;
  }
  return 0;
}
inline void summary(unsigned field,const Model& m,char* output,size_t capacity) {
  switch(field) {
    case Protocol:std::snprintf(output,capacity,"Protocol: %s",modeName(m.lora_mode));break;
    case Preset:{ const auto* p=tunnel::lora_profiles::findModemPreset(m.meshtastic_preset);
      std::snprintf(output,capacity,"Meshtastic: %s",p?p->name:"Custom / SD");break; }
    case Slot:if(m.meshtastic_slot)std::snprintf(output,capacity,"Frequency slot: %u",unsigned(m.meshtastic_slot));
      else std::snprintf(output,capacity,"Frequency slot: AUTO");break;
    case MeshCore:std::snprintf(output,capacity,"MeshCore: %.31s",m.meshcore_profile);break;
    case Dwell:std::snprintf(output,capacity,"Both dwell: %lu seconds",static_cast<unsigned long>(m.lora_dwell_ms/1000));break;
    case PublicDecode:std::snprintf(output,capacity,"Public decode: %s",m.decode_public?"ON":"OFF");break;
    default:if(capacity)output[0]=0;
  }
}
inline bool save(unsigned field,unsigned index,const Model& m,Handler handler) {
  const Option choice=option(field,index,m);
  if(!editable(m) || !choice.available || !handler)return false;
  handler(choice.action,choice.value,choice.text);
  return true;
}
} }
