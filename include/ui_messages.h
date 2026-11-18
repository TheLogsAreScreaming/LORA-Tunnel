#pragma once
#include "ui.h"
#include <algorithm>
#include <cstdio>
#include <cstring>

// Bounded navigation shared by both displays. The model's record pointers are
// borrowed only during an event/draw. A detail view owns one selected snapshot.
namespace ui { namespace messages {
using tunnel::messaging::Contact;
using tunnel::messaging::Record;
using tunnel::mesh::Protocol;
enum class Screen { Mode, Menu, Inbox, Detail, Contacts, Contact, Trust, Settings, TxConfirm, Identity };
enum class Result { None, Edit, Exit };
constexpr const char* settingNames[]={"Display name", "Meshtastic channel", "Meshtastic key (hex)", "MeshCore key (hex)", "Meshtastic hop limit"};
struct State {
  Screen screen=Screen::Mode;
  unsigned selected=0, setting=0;
  int target=-1;
  bool composing=false;
  Protocol pending_protocol=Protocol::Unknown;
  Protocol compose_protocol=Protocol::Unknown;
  Record record{};
  Contact contact{};
  char error[64]{};
};
inline const char* protocolName(Protocol p) {return p==Protocol::MeshCore?"MeshCore":p==Protocol::Meshtastic?"Meshtastic":"Unknown";}
inline void fingerprint(const Contact& c,char (&out)[65]) {
  for(unsigned i=0;i<32;++i)std::snprintf(out+i*2,3,"%02X",unsigned(c.public_key[i]));
}
inline bool hasKey(const Contact& c) {for(auto b:c.public_key)if(b)return true;return false;}
inline bool canDirect(const Contact& c) {return c.trusted && !c.key_changed && hasKey(c);}
inline void refreshRecord(State& s,const Model& m) {
  // Start/stop may pause or restore BLE asynchronously. A queued request is
  // not proof that the selected protocol obtained radio ownership.
  if(s.screen==Screen::Mode && s.pending_protocol!=Protocol::Unknown) {
    if(m.messages.active && m.messages.protocol==s.pending_protocol && !m.messages_transitioning) {
      s.pending_protocol=Protocol::Unknown;s.screen=Screen::Menu;s.error[0]=0;
    } else if(m.messages_transitioning)std::snprintf(s.error,sizeof(s.error),"Preparing messaging; please wait");
    else s.error[0]=0; // A rejected start leaves Mode and the main-loop notice visible.
  }
  if(s.screen!=Screen::Detail || !m.messages.history)return;
  for(unsigned i=0;i<std::min(unsigned(m.messages.history_count),unsigned(tunnel::messaging::HistoryCount));++i) {
    const auto& r=m.messages.history[i];
    if(r.id==s.record.id && r.protocol==s.record.protocol && r.peer==s.record.peer && r.outgoing==s.record.outgoing && !std::strcmp(r.text,s.record.text)) {
      s.record.delivery=r.delivery;s.record.authenticated=r.authenticated;return;
    }
  }
}
inline unsigned count(const State& s,const Model& m) {
  switch(s.screen) {
    case Screen::Mode:return 2;
    case Screen::Menu:return 9;
    case Screen::Inbox:return m.messages.history?std::min(unsigned(m.messages.history_count),unsigned(tunnel::messaging::HistoryCount)):0;
    case Screen::Contacts:return m.messages.contacts?std::min(unsigned(m.messages.contact_count),unsigned(tunnel::messaging::ContactCount)):0;
    case Screen::Contact:return 3;
    case Screen::Trust:case Screen::TxConfirm:return 2;
    case Screen::Settings:return 5;
    default:return 0;
  }
}
inline void row(const State& s,unsigned i,const Model& m,char* out,size_t size) {
  out[0]=0;
  if(i>=count(s,m))return;
  switch(s.screen) {
    case Screen::Mode:std::snprintf(out,size,"%s",i?"MeshCore":"Meshtastic");break;
    case Screen::Menu: {
      const char* names[]={"Inbox / sent messages","Write to channel","Contacts / private message","Messaging settings",m.messages.tx_enabled?"TX enabled - turn OFF":"Enable transmission (TX)","Announce my identity","My identity / radio","Change protocol","Stop messages / Home"};
      std::snprintf(out,size,"%s",names[i]);break;
    }
    case Screen::Inbox: {
      const auto& r=m.messages.history[i];
      std::snprintf(out,size,"%s %.14s: %.17s",r.outgoing?">":"<",r.name[0]?r.name:r.direct?"Private":"Channel",r.text);break;
    }
    case Screen::Contacts: {
      const auto& c=m.messages.contacts[i];
      std::snprintf(out,size,"%s %.26s",c.key_changed?"CHANGED":c.trusted?"TRUSTED":"VERIFY",c.name[0]?c.name:"Unnamed contact");break;
    }
    case Screen::Contact: {
      const char* names[]={canDirect(s.contact)?"Write private message":"Private: verify key first","Review / trust public key","Forget contact"};
      std::snprintf(out,size,"%s",names[i]);break;
    }
    case Screen::Trust:std::snprintf(out,size,"%s",i?"I verified this key - TRUST":"Cancel / keep untrusted");break;
    case Screen::TxConfirm:std::snprintf(out,size,"%s",i?"Enable TX for this session":"Cancel / keep TX off");break;
    case Screen::Settings:std::snprintf(out,size,"%s",settingNames[i]);break;
    default:break;
  }
}
inline const char* title(const State& s) {
  switch(s.screen) {
    case Screen::Mode:return "MESSAGES";
    case Screen::Menu:return "MESSAGES";
    case Screen::Inbox:return "INBOX";
    case Screen::Detail:return "MESSAGE";
    case Screen::Contacts:return "CONTACTS";
    case Screen::Contact:return "CONTACT";
    case Screen::Trust:return "VERIFY KEY";
    case Screen::Settings:return "MSG SETUP";
    case Screen::TxConfirm:return "ENABLE TX?";
    case Screen::Identity:return "MY IDENTITY";
  }return "MESSAGES";
}
inline void open(State& s,const Model& m) {s=State{};s.screen=m.messages.active?Screen::Menu:Screen::Mode;}
inline Result back(State& s,Handler emit) {
  s.error[0]=0;
  switch(s.screen) {
    case Screen::Mode:case Screen::Menu:s.pending_protocol=Protocol::Unknown;if(emit)emit(Action::StopMessages,0,"");return Result::Exit;
    case Screen::Detail:s.screen=Screen::Inbox;break;
    case Screen::Contact:s.screen=Screen::Contacts;break;
    case Screen::Trust:s.screen=Screen::Contact;break;
    default:s.screen=Screen::Menu;break;
  }return Result::None;
}
inline Result choose(State& s,unsigned i,const Model& m,Handler emit) {
  if(i>=count(s,m))return Result::None;
  s.error[0]=0;
  switch(s.screen) {
    case Screen::Mode:
      if(m.messages_transitioning) {std::snprintf(s.error,sizeof(s.error),"Restoring or preparing radio; wait");break;}
      if(m.messages.active) {
        if(m.messages.protocol==Protocol(i+1))s.screen=Screen::Menu;
        else std::snprintf(s.error,sizeof(s.error),"Stop current Messages mode first");
        break;
      }
      s.pending_protocol=Protocol(i+1);
      if(emit)emit(Action::StartMessages,int(i+1),"");
      break;
    case Screen::Menu:
      if(i==0)s.screen=Screen::Inbox;
      else if(i==1) {s.composing=true;s.compose_protocol=m.messages.protocol;s.target=-1;return Result::Edit;}
      else if(i==2)s.screen=Screen::Contacts;
      else if(i==3)s.screen=Screen::Settings;
      else if(i==4) {if(m.messages.tx_enabled) {if(emit)emit(Action::ToggleMessageTx,0,"");}else s.screen=Screen::TxConfirm;}
      else if(i==5) {if(emit)emit(Action::AnnounceIdentity,0,"");}
      else if(i==6)s.screen=Screen::Identity;
      else if(i==7) {s.pending_protocol=Protocol::Unknown;if(emit)emit(Action::StopMessages,0,"");s.screen=Screen::Mode;}
      else {if(emit)emit(Action::StopMessages,0,"");return Result::Exit;}
      break;
    case Screen::Inbox:s.record=m.messages.history[i];s.screen=Screen::Detail;break;
    case Screen::Contacts:s.contact=m.messages.contacts[i];s.selected=i;s.screen=Screen::Contact;break;
    case Screen::Contact:
      if(i==0) {
        if(!canDirect(s.contact)) {std::snprintf(s.error,sizeof(s.error),"Verify the current public key first");break;}
        if(s.contact.protocol!=m.messages.protocol) {std::snprintf(s.error,sizeof(s.error),"Select this contact's protocol first");break;}
        s.composing=true;s.compose_protocol=m.messages.protocol;s.target=int(s.selected);return Result::Edit;
      }
      if(i==1)s.screen=Screen::Trust;
      else if(i==2) {char key[65];fingerprint(s.contact,key);if(emit)emit(Action::ForgetContact,int(s.selected),key);s.screen=Screen::Contacts;}
      break;
    case Screen::Trust:
      if(i && hasKey(s.contact)) {char key[65];fingerprint(s.contact,key);if(emit)emit(Action::TrustContact,int(s.selected),key);}
      s.screen=Screen::Contact;break;
    case Screen::Settings:s.composing=false;s.setting=i;return Result::Edit;
    case Screen::TxConfirm:if(i && emit)emit(Action::ToggleMessageTx,1,"");s.screen=Screen::Menu;break;
    default:break;
  }return Result::None;
}
inline size_t editLimit(const State& s) {return s.composing?120:s.setting==0?31:s.setting==1?39:s.setting==4?1:64;}
inline bool secret(const State& s) {return !s.composing && (s.setting==2||s.setting==3);}
inline const char* editTitle(const State& s) {return s.composing?(s.target<0?"Channel message":"Private message"):settingNames[s.setting];}
inline bool submit(State& s,const char* value,const Model& m,Handler emit) {
  s.error[0]=0;
  if(s.composing) {
    if(!value[0]) {std::snprintf(s.error,sizeof(s.error),"Type a message before sending");return false;}
    if(std::strlen(value)>tunnel::messaging::TextBytes) {std::snprintf(s.error,sizeof(s.error),"Message exceeds 120 bytes");return false;}
    if(!m.messages.active || !m.messages.tx_enabled) {std::snprintf(s.error,sizeof(s.error),"Enable TX in Messages before sending");return false;}
    if(s.compose_protocol!=m.messages.protocol) {std::snprintf(s.error,sizeof(s.error),"Protocol changed; reopen the conversation");return false;}
    if(s.target>=0) {
      if(!m.messages.contacts||unsigned(s.target)>=std::min(unsigned(m.messages.contact_count),unsigned(tunnel::messaging::ContactCount))){std::snprintf(s.error,sizeof(s.error),"Contact changed; reopen the conversation");return false;}
      const auto& current=m.messages.contacts[s.target];
      if(current.protocol!=s.contact.protocol||current.protocol!=m.messages.protocol||current.node!=s.contact.node||
          std::memcmp(current.public_key,s.contact.public_key,32)||!canDirect(current)){
        std::snprintf(s.error,sizeof(s.error),"Contact changed; review its public key");return false;
      }
    }
    if(emit)emit(Action::SendMessage,s.target,value);
    s.screen=Screen::Inbox;
  } else {
    const size_t length=std::strlen(value);
    bool valid=length<=editLimit(s);
    for(size_t i=0;i<length;++i)valid=valid && value[i]>=32 && value[i]<=126;
    if(s.setting==0)valid=valid && length && !std::strchr(value,':');
    if(s.setting==2||s.setting==3) {
      valid=valid && (!length || length==32 || length==64);
      for(size_t i=0;i<length;++i)valid=valid && ((value[i]>='0'&&value[i]<='9')||(value[i]>='a'&&value[i]<='f')||(value[i]>='A'&&value[i]<='F'));
    }
    if(s.setting==4)valid=valid && length==1 && value[0]>='0' && value[0]<='7';
    if(!valid) {std::snprintf(s.error,sizeof(s.error),"%s",s.setting==0?"Name: 1-31 characters, no colon":s.setting==4?"Meshtastic hop limit: 0-7":s.setting==2||s.setting==3?"Key: 32/64 hex digits, or blank":"Channel: at most 39 characters");return false;}
    if(emit)emit(Action::SaveMessagingSetting,int(s.setting),value);
    s.screen=Screen::Settings;
  }return true;
}
} }
