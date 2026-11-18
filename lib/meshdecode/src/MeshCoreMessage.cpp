// SPDX-License-Identifier: MIT
// Original bounded wire implementation from MeshCore protocol facts, pinned to
// meshcore-dev/MeshCore 75b04ef06def54b348400cb1b138afb6749ffd4f:
// docs/{packet_format,payloads}.md, src/{Utils,Mesh}.cpp and
// src/helpers/BaseChatMesh.cpp. No upstream application implementation copied.
#include "meshcore_message.h"
#include "mesh_decode.h"
#include "text_sanitize.h"
#include <cstring>

namespace tunnel { namespace meshcore_message {
namespace {
constexpr std::uint8_t PublicKey[16]={0x8b,0x33,0x87,0xe9,0xc5,0xcd,0xea,0x6a,0xc9,0xe5,0xed,0xba,0xa1,0x15,0xcd,0x72};
void wipe(void* data,std::size_t n) { volatile std::uint8_t* p=static_cast<volatile std::uint8_t*>(data); while(n--)*p++=0; }
struct Scratch { std::uint8_t secret[32]{},plain[176]{},hash[32]{}; ~Scratch(){wipe(this,sizeof(*this));} };
bool same(const std::uint8_t* a,const std::uint8_t* b,std::size_t n) { unsigned d=0; while(n--)d|=*a++^*b++; return !d; }
std::size_t bounded(const char* s,std::size_t max) { if(!s)return max+1; std::size_t n=0; while(n<=max && s[n])++n; return n; }
bool textSize(const char* s,std::size_t max,std::size_t& n) { n=bounded(s,max); return n && n<=max; }
std::uint32_t read32(const std::uint8_t* p) { return std::uint32_t(p[0])|(std::uint32_t(p[1])<<8)|(std::uint32_t(p[2])<<16)|(std::uint32_t(p[3])<<24); }
void put32(std::uint8_t* p,std::uint32_t v) { for(unsigned i=0;i<4;++i)p[i]=std::uint8_t(v>>(i*8)); }
std::size_t pathBytes(std::uint8_t encoding) { return (encoding>>6)==3?MaxPath+1:std::size_t(encoding&63)*((encoding>>6)+1); }
struct Envelope { std::uint8_t type=0,route=0,pathEncoding=0; const std::uint8_t* path=nullptr; const std::uint8_t* payload=nullptr; std::size_t size=0; };
bool envelope(const std::uint8_t* f,std::size_t n,Envelope& e) {
  if(!f || n<2 || n>255 || (f[0]>>6))return false;
  e.type=(f[0]>>2)&15; e.route=f[0]&3;
  const std::size_t po=(e.route==0 || e.route==3)?5:1;
  if(n<=po)return false;
  e.pathEncoding=f[po]; const std::size_t bytes=pathBytes(e.pathEncoding);
  if(bytes>MaxPath || po+1+bytes>=n)return false;
  e.path=f+po+1; e.payload=e.path+bytes; e.size=n-(po+1+bytes);
  return e.size<=184;
}
bool seal(const Crypto& c,const std::uint8_t secret[32],const std::uint8_t* plain,std::size_t n,std::uint8_t* out,std::size_t& length) {
  length=0; if(!c.ecb || !c.hmac || !n || n>176)return false;
  Scratch s; std::memcpy(s.plain,plain,n); const std::size_t padded=(n+15)&~std::size_t(15);
  if(!c.ecb(true,secret,s.plain,padded,out+2) || !c.hmac(secret,out+2,padded,s.hash))return false;
  std::memcpy(out,s.hash,2); length=padded+2; return true;
}
bool open(const Crypto& c,const std::uint8_t secret[32],const std::uint8_t* sealed,std::size_t n,Scratch& s,std::size_t& length) {
  length=0; if(!c.ecb || !c.hmac || n<18 || n>178 || (n-2)%16)return false;
  if(!c.hmac(secret,sealed+2,n-2,s.hash) || !same(s.hash,sealed,2))return false;
  if(!c.ecb(false,secret,sealed+2,n-2,s.plain))return false;
  length=n-2; return true;
}
bool keySecret(const std::uint8_t* key,std::size_t n,Scratch& s,const Crypto& c) {
  if(!key || (n!=16 && n!=32) || !c.sha256)return false;
  std::memcpy(s.secret,key,n); return c.sha256(key,n,s.hash);
}
bool ackHash(const std::uint8_t* plain,std::size_t n,const std::uint8_t sender[32],const Crypto& c,std::uint8_t out[4]) {
  if(!c.sha256 || n>125)return false;
  std::uint8_t input[157]{},hash[32]{}; std::memcpy(input,plain,n); std::memcpy(input+n,sender,32);
  const bool ok=c.sha256(input,n+32,hash); if(ok)std::memcpy(out,hash,4);
  wipe(input,sizeof(input));wipe(hash,sizeof(hash));return ok;
}
bool peerOpen(const Envelope& e,const Identity& self,const Contact& peer,const Crypto& c,Scratch& s,std::size_t& n) {
  return e.size>=20 && e.payload[0]==self.public_key[0] && e.payload[1]==peer.public_key[0] &&
      c.shared && c.shared(self.seed,peer.public_key,s.secret) && open(c,s.secret,e.payload+2,e.size-2,s,n);
}
bool plainText(const std::uint8_t* plain,std::size_t n,std::size_t max,std::size_t& length,bool extendedAttempt=false) {
  if(n<6 || plain[4]>>2)return false;
  length=0; while(5+length<n && plain[5+length])++length;
  if(!length || length>max)return false;
  std::size_t tail=5+length;
  if(extendedAttempt && tail+1<n && plain[tail+1]>3)tail+=2;
  for(;tail<n;++tail)if(plain[tail])return false;
  return true;
}
void pathInfo(const Envelope& e,Message& m) {
  m.flood=e.route==0 || e.route==1; m.path_encoding=e.pathEncoding;
  std::memcpy(m.path,e.path,pathBytes(e.pathEncoding));
}
}
const std::uint8_t* publicGroupKey(){return PublicKey;}
bool identity(const std::uint8_t seed[32],const Crypto& c,Identity& out) {
  // Loading persistent bytes directly into out.seed is supported.
  std::uint8_t copy[32]{};if(seed)std::memcpy(copy,seed,32);out=Identity{};
  if(!seed || !c.publicKey || !c.publicKey(copy,out.public_key)){out=Identity{};wipe(copy,sizeof(copy));return false;}
  std::memcpy(out.seed,copy,32);wipe(copy,sizeof(copy));return true;
}
bool groupText(const std::uint8_t* key,std::size_t kl,const char* name,const char* text,std::uint32_t stamp,std::uint8_t attempt,const Crypto& c,Frame& out) {
  out=Frame{}; std::size_t nn,tn; Scratch s;
  if(!stamp || attempt>3 || !textSize(name,MaxName,nn) || !textSize(text,MaxText,tn) || !keySecret(key,kl,s,c))return false;
  put32(s.plain,stamp); s.plain[4]=attempt; std::memcpy(s.plain+5,name,nn);
  s.plain[5+nn]=':';s.plain[6+nn]=' ';std::memcpy(s.plain+7+nn,text,tn);
  out.bytes[0]=(5<<2)|1; out.bytes[2]=s.hash[0]; std::size_t n=0;
  if(!seal(c,s.secret,s.plain,7+nn+tn,out.bytes+3,n)){out=Frame{};return false;}
  out.length=3+n;return true;
}
bool parseGroup(const std::uint8_t* f,std::size_t len,const std::uint8_t* key,std::size_t kl,const Crypto& c,Message& out) {
  out=Message{};Envelope e;Scratch s;std::size_t n,tn;
  if(!envelope(f,len,e) || e.type!=5 || e.size<19 || !keySecret(key,kl,s,c) || e.payload[0]!=s.hash[0] ||
     !open(c,s.secret,e.payload+1,e.size-1,s,n) || !plainText(s.plain,n,MaxName+2+MaxText,tn))return false;
  std::size_t split=0; while(split+1<tn && !(s.plain[5+split]==':' && s.plain[6+split]==' '))++split;
  if(!split || split>MaxName || split+2>=tn || tn-split-2>MaxText)return false;
  Message m;m.kind=Kind::GroupText;m.timestamp=read32(s.plain);m.attempt=s.plain[4]&3;
  copyUtf8Bounded(m.name,sizeof(m.name),s.plain+5,split);copyUtf8Bounded(m.text,sizeof(m.text),s.plain+7+split,tn-split-2);
  pathInfo(e,m);out=m;return true;
}
bool advert(const Identity& self,const char* name,std::uint32_t stamp,const Crypto& c,Frame& out) {
  out=Frame{};std::size_t nn; if(!stamp || !textSize(name,MaxName,nn) || !c.sign)return false;
  std::uint8_t signedBytes[68]{};std::memcpy(signedBytes,self.public_key,32);put32(signedBytes+32,stamp);
  signedBytes[36]=0x81;std::memcpy(signedBytes+37,name,nn);
  out.bytes[0]=(4<<2)|1;std::memcpy(out.bytes+2,signedBytes,36);
  if(!c.sign(self.seed,self.public_key,signedBytes,37+nn,out.bytes+38)){out=Frame{};return false;}
  out.bytes[102]=0x81;std::memcpy(out.bytes+103,name,nn);out.length=103+nn;return true;
}
bool parseAdvert(const std::uint8_t* f,std::size_t n,const Crypto& c,Contact& out) {
  out=Contact{};if(!c.verify)return false;
  mesh::Crypto adapter{};adapter.verify=c.verify;mesh::Result decoded;
  mesh::decodeMeshCore(f,n,adapter,decoded,nullptr,0,false);
  if(decoded.status!=mesh::Status::Decoded || decoded.packet_type!=4 || !decoded.has_node ||
     decoded.authentication!=mesh::Authentication::Verified || !decoded.has_role || decoded.role!=1 || decoded.sanitized)return false;
  const std::size_t nn=bounded(decoded.name,MaxName);if(!nn || nn>MaxName || !decoded.timestamp)return false;
  std::memcpy(out.public_key,decoded.public_key,32);std::memcpy(out.name,decoded.name,nn+1);out.timestamp=decoded.timestamp;return true;
}
bool directText(const Identity& self,const Contact& peer,const char* text,std::uint32_t stamp,std::uint8_t attempt,const Crypto& c,Frame& out,std::uint8_t ack[4]) {
  out=Frame{};if(!ack)return false;std::memset(ack,0,4);std::size_t tn;Scratch s;
  if(!stamp || attempt>3 || !textSize(text,MaxText,tn) || !c.shared || !c.shared(self.seed,peer.public_key,s.secret))return false;
  put32(s.plain,stamp);s.plain[4]=attempt;std::memcpy(s.plain+5,text,tn);
  if(!ackHash(s.plain,5+tn,self.public_key,c,ack))return false;
  out.bytes[0]=(2<<2)|1;out.bytes[2]=peer.public_key[0];out.bytes[3]=self.public_key[0];std::size_t n=0;
  if(!seal(c,s.secret,s.plain,5+tn,out.bytes+4,n)){out=Frame{};std::memset(ack,0,4);return false;}
  out.length=4+n;return true;
}
bool parseDirect(const std::uint8_t* f,std::size_t len,const Identity& self,const Contact& peer,const Crypto& c,Message& out) {
  out=Message{};Envelope e;Scratch s;std::size_t n,tn;
  if(!envelope(f,len,e) || e.type!=2 || !peerOpen(e,self,peer,c,s,n) || !plainText(s.plain,n,MaxText,tn,true))return false;
  Message m;m.kind=Kind::DirectText;m.timestamp=read32(s.plain);m.attempt=s.plain[4]&3;
  if(!ackHash(s.plain,5+tn,peer.public_key,c,m.ack))return false;
  std::memcpy(m.sender,peer.public_key,32);std::memcpy(m.recipient,self.public_key,32);
  copyUtf8Bounded(m.text,sizeof(m.text),s.plain+5,tn);copyUtf8Bounded(m.name,sizeof(m.name),reinterpret_cast<const std::uint8_t*>(peer.name),bounded(peer.name,MaxName));
  pathInfo(e,m);out=m;return true;
}
bool reply(const Identity& self,const Contact& peer,const Message& received,const Crypto& c,Frame& out) {
  out=Frame{};if(received.kind!=Kind::DirectText || !same(received.sender,peer.public_key,32) || !same(received.recipient,self.public_key,32))return false;
  if(!received.flood){out.bytes[0]=(3<<2)|1;std::memcpy(out.bytes+2,received.ack,4);out.length=6;return true;}
  const std::size_t pn=pathBytes(received.path_encoding);if(pn>MaxPath || !c.shared)return false;
  Scratch s;if(!c.shared(self.seed,peer.public_key,s.secret))return false;
  s.plain[0]=received.path_encoding;std::memcpy(s.plain+1,received.path,pn);s.plain[1+pn]=3;std::memcpy(s.plain+2+pn,received.ack,4);
  out.bytes[0]=(8<<2)|1;out.bytes[2]=peer.public_key[0];out.bytes[3]=self.public_key[0];std::size_t n=0;
  if(!seal(c,s.secret,s.plain,6+pn,out.bytes+4,n)){out=Frame{};return false;}
  out.length=4+n;return true;
}
bool parseReceipt(const std::uint8_t* f,std::size_t len,const Identity& self,const Contact& peer,const std::uint8_t expected[4],const Crypto& c,Message& out) {
  out=Message{};Envelope e;if(!expected || !envelope(f,len,e))return false;Message m;m.kind=Kind::Receipt;
  if(e.type==3){
    if((e.size!=4 && e.size!=6) || !same(e.payload,expected,4))return false;
    m.receipt_trust=ReceiptTrust::HashOnly;
  }else if(e.type==8){
    Scratch s;std::size_t n;if(!peerOpen(e,self,peer,c,s,n))return false;
    const std::size_t pn=pathBytes(s.plain[0]);if(pn>MaxPath || pn+6>n || s.plain[pn+1]!=3 || !same(s.plain+pn+2,expected,4))return false;
    // A modern peer may append extended-attempt and random bytes to the four
    // byte receipt. Both forms pad the remainder of the AES block with zeroes.
    std::size_t tail=pn+6;bool zero=true;for(std::size_t i=tail;i<n;++i)zero&=s.plain[i]==0;
    if(!zero){if(tail+2>n)return false;tail+=2;for(;tail<n;++tail)if(s.plain[tail])return false;}
    m.path_encoding=s.plain[0];std::memcpy(m.path,s.plain+1,pn);m.receipt_trust=ReceiptTrust::AuthenticatedPeer;
    std::memcpy(m.sender,peer.public_key,32);std::memcpy(m.recipient,self.public_key,32);
  }else return false;
  std::memcpy(m.ack,expected,4);out=m;return true;
}
} }
