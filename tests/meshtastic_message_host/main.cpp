// Copyright (c) 2026 Valleytech Solutions. SPDX-License-Identifier: MIT
// Real production adapter, independent Python AES/X25519/CCM/HMAC fixtures.
#include "meshtastic_message.h"
#include "vectors.h"
#include <RNG.h>
#include <array>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <vector>

RNGClass::RNGClass(){}
RNGClass::~RNGClass(){}
void RNGClass::rand(std::uint8_t*,std::size_t){std::abort();}
RNGClass RNG; // No generation path may call this: test keys are RFC7748 public data.

using namespace tunnel::meshtastic;
using Bytes=std::vector<std::uint8_t>;
namespace {
const Crypto& crypto=platformCrypto();
Bytes hex(const char* text){Bytes v;auto nibble=[](char c){if(c>='0'&&c<='9')return c-'0';if(c>='a'&&c<='f')return c-'a'+10;assert(false);return 0;};
  while(*text){assert(text[1]);v.push_back(std::uint8_t(nibble(*text)*16+nibble(text[1])));text+=2;}return v;}
void key(std::uint8_t out[32],const char* value){const auto data=hex(value);assert(data.size()==32);std::memcpy(out,data.data(),32);}
bool equal(const Frame& frame,const char* expected){const auto bytes=hex(expected);return frame.length==bytes.size()&&!std::memcmp(frame.bytes,bytes.data(),bytes.size());}
Identity alice(){Identity x;x.node=0x12345678;key(x.private_key,fixture::alicePrivate);key(x.public_key,fixture::alicePublic);std::strcpy(x.name,"Alice test");std::strcpy(x.short_name,"AL");return x;}
Identity bob(){Identity x;x.node=0x9abcdef0;key(x.private_key,fixture::bobPrivate);key(x.public_key,fixture::bobPublic);std::strcpy(x.name,"Bob test");std::strcpy(x.short_name,"BOB");return x;}
Contact contact(const Identity& identity){Contact c;c.node=identity.node;c.has_public_key=true;std::memcpy(c.public_key,identity.public_key,32);return c;}
Tx tx(){Tx t;t.packet_id=0x10203040;t.extra_nonce=0x50607080;t.want_ack=true;return t;}
Channel channel(unsigned size){Channel c;c.key_length=std::uint8_t(size);c.hash=size==16?8:size==32?0x42:0x5a;
  if(size==16){const auto k=hex("d4f1bb3a20290759f0bcffabcf4e6901");std::memcpy(c.key,k.data(),16);}
  else if(size==32)for(unsigned i=0;i<32;++i)c.key[i]=std::uint8_t(i);return c;}
void write32(std::uint8_t* p,std::uint32_t value){for(unsigned i=0;i<4;++i)p[i]=std::uint8_t(value>>(i*8));}
Frame clearPayload(const Bytes& payload,std::uint32_t to=Broadcast){Frame f;auto a=alice();auto t=tx();assert(encodeChannelText(channel(0),a,t,"x",f,crypto));
  write32(f.bytes,to);assert(payload.size()<=239);std::memcpy(f.bytes+16,payload.data(),payload.size());f.length=16+payload.size();return f;}

void keysAndPrimitives(){
  const auto a=alice(),b=bob();std::uint8_t output[32],expected[32];
  assert(crypto.derivePublic(a.private_key,output));assert(!std::memcmp(output,a.public_key,32));
  assert(crypto.derivePublic(b.private_key,output));assert(!std::memcmp(output,b.public_key,32));
  key(expected,fixture::shared);assert(crypto.sharedKey(a.private_key,b.public_key,output));assert(!std::memcmp(output,expected,32));
  assert(crypto.sharedKey(b.private_key,a.public_key,output));assert(!std::memcmp(output,expected,32));
  std::uint8_t bad[32]{};assert(!crypto.derivePublic(bad,output));assert(!crypto.sharedKey(bad,b.public_key,output));
  assert(!crypto.sharedKey(a.private_key,bad,output));bad[0]=1;assert(!crypto.sharedKey(a.private_key,bad,output));
  // Verify output erasure on rejected peer keys.
  for(auto v:output)assert(v==0);
}
void channelText(){
  const char* fixtures[]={fixture::clear,fixture::channel16,fixture::channel32};unsigned index=0;
  for(unsigned size:{0U,16U,32U}){
    const auto ch=channel(size);Frame f;Parsed p;
    assert(encodeChannelText(ch,alice(),tx(),"Hello mesh!",f,crypto));assert(equal(f,fixtures[index++]));
    assert(decodeChannel(f.bytes,f.length,ch,p,crypto));assert(p.kind==Kind::Text&&std::strcmp(p.text,"Hello mesh!")==0);
    assert(!p.authenticated&&!p.private_envelope&&p.header.want_ack&&p.header.hop_start==3&&p.header.hop_limit==3);
    assert(p.header.to==Broadcast&&p.header.from==alice().node&&p.header.id==tx().packet_id);
    auto wrong=ch;wrong.hash^=1;assert(!decodeChannel(f.bytes,f.length,wrong,p,crypto));assert(p.status==Status::WrongChannel&&p.text[0]==0);
  }
  Frame f;auto t=tx();t.packet_id=0;assert(!encodeChannelText(channel(16),alice(),t,"x",f,crypto));assert(f.length==0);
  t=tx();t.hop_limit=8;assert(!encodeChannelText(channel(16),alice(),t,"x",f,crypto));
  auto bad=channel(16);bad.key_length=17;assert(!encodeChannelText(bad,alice(),tx(),"x",f,crypto));
  assert(!encodeChannelText(channel(16),alice(),tx(),"",f,crypto));
  assert(!encodeChannelText(channel(16),alice(),tx(),"bad\ncontrol",f,crypto));
  const char invalid[]={char(0xc0),char(0xaf),0};assert(!encodeChannelText(channel(16),alice(),tx(),invalid,f,crypto));
  std::array<char,122> longText;longText.fill('a');longText[120]=0;assert(encodeChannelText(channel(32),alice(),tx(),longText.data(),f,crypto));
  longText[120]='a';longText[121]=0;assert(!encodeChannelText(channel(32),alice(),tx(),longText.data(),f,crypto));
  assert(encodeChannelText(channel(16),alice(),tx(),"caf\xc3\xa9",f,crypto));Parsed p;
  assert(decodeChannel(f.bytes,f.length,channel(16),p,crypto)&&!p.sanitized);
}
void privateText(){
  const auto a=alice(),b=bob();const auto ac=contact(a),bc=contact(b);Frame f;Parsed p;
  assert(encodePrivateText(a,bc,tx(),"Hello mesh!",f,crypto));assert(equal(f,fixture::privateText));
  assert(decodePrivate(f.bytes,f.length,b,ac,p,crypto));assert(p.authenticated&&p.private_envelope&&p.kind==Kind::Text);
  assert(std::strcmp(p.text,"Hello mesh!")==0&&p.header.want_ack);
  // Every ciphertext byte, tag byte and random nonce byte must be authenticated.
  for(std::size_t n=16;n<f.length;++n){auto altered=f;altered.bytes[n]^=1;
    assert(!decodePrivate(altered.bytes,altered.length,b,ac,p,crypto));assert(!p.authenticated&&p.text[0]==0);}
  for(std::size_t n=0;n<12;++n){auto altered=f;altered.bytes[n]^=1;assert(!decodePrivate(altered.bytes,altered.length,b,ac,p,crypto));}
  for(std::size_t n=0;n<f.length;++n)assert(!decodePrivate(f.bytes,n,b,ac,p,crypto));
  auto wrong=ac;wrong.node^=0x100;assert(!decodePrivate(f.bytes,f.length,b,wrong,p,crypto));
  wrong=ac;wrong.public_key[4]^=1;assert(!decodePrivate(f.bytes,f.length,b,wrong,p,crypto));
  wrong=bc;wrong.has_public_key=false;assert(!encodePrivateText(a,wrong,tx(),"x",f,crypto));
  assert(f.length==0);assert(!encodePrivateText(a,ac,tx(),"x",f,crypto));
  assert(encodePrivateText(a,bc,tx(),"x",f,crypto));
  // Relays legitimately change hop flags / next-hop / relay bytes; no claim of
  // authentication is made for those mutable header fields.
  f.bytes[12]^=1;f.bytes[14]=0x55;f.bytes[15]=0x66;assert(decodePrivate(f.bytes,f.length,b,ac,p,crypto));
  std::array<char,121> text;text.fill('z');text.back()=0;assert(encodePrivateText(a,bc,tx(),text.data(),f,crypto));
  assert(decodePrivate(f.bytes,f.length,b,ac,p,crypto));assert(std::strlen(p.text)==120);
}
void nodeInfo(){
  const auto a=alice();Frame f;Parsed p;
  assert(encodeNodeInfo(channel(16),a,tx(),f,crypto,true));assert(decodeChannel(f.bytes,f.length,channel(16),p,crypto));
  assert(p.kind==Kind::NodeInfo&&p.request_response&&p.has_public_key&&!p.authenticated);
  assert(!std::memcmp(p.public_key,a.public_key,32)&&std::strcmp(p.name,a.name)==0&&std::strcmp(p.short_name,a.short_name)==0);
  assert(encodeNodeInfo(channel(0),a,tx(),f,crypto,false,bob().node));assert(decodeChannel(f.bytes,f.length,channel(0),p,crypto));
  assert(p.header.to==bob().node&&!p.request_response);
  auto unnamed=a;unnamed.name[0]=0;assert(!encodeNodeInfo(channel(16),unnamed,tx(),f,crypto));
  auto noKey=a;std::memset(noKey.public_key,0,32);assert(encodeNodeInfo(channel(16),noKey,tx(),f,crypto));
  assert(decodeChannel(f.bytes,f.length,channel(16),p,crypto)&&!p.has_public_key);
  // Empty NodeInfo request, bitfield's want_response mirror and unknown fields.
  f=clearPayload({8,4,18,0,72,2,0x98,6,1});assert(decodeChannel(f.bytes,f.length,channel(0),p,crypto));
  assert(p.kind==Kind::NodeInfo&&p.request_response&&!p.has_public_key);
  f=clearPayload({8,4,18,0,72,2,24,0});assert(decodeChannel(f.bytes,f.length,channel(0),p,crypto)&&p.request_response);
  f=clearPayload({8,4,18,0,24,0,72,2});assert(decodeChannel(f.bytes,f.length,channel(0),p,crypto)&&p.request_response);
}
void receipts(){
  const auto a=alice(),b=bob();const auto ac=contact(a),bc=contact(b);Tx t=tx();++t.packet_id;Frame f;Parsed p;
  for(unsigned error:{0U,3U}){
    assert(encodeReceipt(channel(16),b,a.node,t,tx().packet_id,error,f,crypto,&ac));
    assert(equal(f,error?fixture::nak:fixture::ack));
    assert(decodeChannel(f.bytes,f.length,channel(16),p,crypto,&a,&bc));
    assert(p.kind==Kind::Receipt&&p.routing_error==error&&p.has_receipt_proof&&p.receipt_proof_valid&&p.authenticated);
    assert(!p.header.want_ack&&receiptMatches(p,a.node,b.node,tx().packet_id));
    assert(!receiptMatches(p,a.node,b.node,tx().packet_id+1));
    assert(!receiptMatches(p,b.node,a.node,tx().packet_id));
    assert(!receiptMatches(p,a.node,b.node^1,tx().packet_id));assert(!receiptMatches(p,a.node,b.node,0));
    // Same encrypted receipt without an accepted contact remains unverified.
    assert(decodeChannel(f.bytes,f.length,channel(16),p,crypto));assert(p.has_receipt_proof&&!p.receipt_proof_valid&&!p.authenticated);
    assert(!receiptMatches(p,a.node,b.node,tx().packet_id));
  }
  assert(encodeReceipt(channel(0),b,a.node,t,tx().packet_id,0,f,crypto,&ac));
  const Frame good=f;
  // Error, request id, peer and requester are all proof inputs.
  for(std::size_t offset:{std::size_t(21),f.length-1}){f=good;f.bytes[offset]^=1;
    assert(!decodeChannel(f.bytes,f.length,channel(0),p,crypto,&a,&bc));assert(p.text[0]==0&&!p.authenticated);}
  f=good;f.bytes[4]^=1;assert(!decodeChannel(f.bytes,f.length,channel(0),p,crypto,&a,&bc));
  f=good;f.bytes[0]^=1;assert(!decodeChannel(f.bytes,f.length,channel(0),p,crypto,&a,&bc));
  assert(encodeReceipt(channel(16),b,a.node,t,tx().packet_id,0,f,crypto));
  assert(decodeChannel(f.bytes,f.length,channel(16),p,crypto,&a,&bc));assert(!p.authenticated&&!p.has_receipt_proof);
  assert(!receiptMatches(p,a.node,b.node,tx().packet_id));assert(receiptMatches(p,a.node,b.node,tx().packet_id,false));
  assert(encodePrivateReceipt(b,ac,t,tx().packet_id,3,f,crypto));
  assert(decodePrivate(f.bytes,f.length,a,bc,p,crypto)&&p.authenticated&&p.routing_error==3);
  assert(receiptMatches(p,a.node,b.node,tx().packet_id));
  assert(!encodeReceipt(channel(16),b,a.node,t,0,0,f,crypto));
  assert(!encodeReceipt(channel(16),b,Broadcast,t,tx().packet_id,0,f,crypto));
}
void malformed(){
  Parsed p;const auto c=channel(0);Frame f;
  for(const auto& bytes:std::vector<Bytes>{
    {},{0},{8},{8,1,18},{8,1,18,120,'a'}, // truncated
    {8,1,8,1,18,1,'x'}, // duplicate port
    {8,1,18,1,'x',18,1,'y'}, // duplicate payload
    {8,1,18,1,'x',24,2}, // invalid bool
    {8,1,18,1,'x',37,1,0,0,0}, // destination mismatch
    {8,4,18,3,66,1,0}, // invalid public key length
    {8,4,18,4,16,1,16,2}, // wrong User wire type / duplicate
    {8,5,18,2,24,0}, // receipt with no request id
    {8,1,18,1,'x',0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,1}, // overlong varint
    {8,1,18,1,'x',0x53} // unsupported protobuf group
  }){f=clearPayload(bytes);assert(!decodeChannel(f.bytes,f.length,c,p,crypto));assert(p.text[0]==0&&!p.authenticated);}
  f=clearPayload({8,5,18,2,24,0,53,1,0,0,0});assert(!decodeChannel(f.bytes,f.length,c,p,crypto)); // broadcast ACK
  f=clearPayload({8,5,18,2,10,0,53,1,0,0,0},bob().node);assert(!decodeChannel(f.bytes,f.length,c,p,crypto)); // route request
  f=clearPayload({8,99,18,0});assert(!decodeChannel(f.bytes,f.length,c,p,crypto)&&p.status==Status::Unsupported);
  f=clearPayload({8,1,18,1,0});assert(decodeChannel(f.bytes,f.length,c,p,crypto)&&p.sanitized&&p.text[0]=='?');
  Header h;assert(!peekHeader(nullptr,20,h));assert(!peekHeader(f.bytes,256,h));
  f.bytes[8]=f.bytes[9]=f.bytes[10]=f.bytes[11]=0;assert(!decodeChannel(f.bytes,f.length,c,p,crypto));
  // Deterministic arbitrary protobuf and header bytes exercise length/tag
  // boundaries. This is supplemental coverage, not a replacement for vectors.
  std::uint32_t random=0xa5e98312U;
  for(unsigned sample=0;sample<4000;++sample){
    Bytes bytes(sample%240);for(auto& b:bytes){random^=random<<13;random^=random>>17;random^=random<<5;b=std::uint8_t(random);}
    f=clearPayload(bytes);decodeChannel(f.bytes,f.length,c,p,crypto);
    if(p.status!=Status::Ok)assert(p.text[0]==0&&!p.authenticated);
  }
}
}
int main(){keysAndPrimitives();channelText();privateText();nodeInfo();receipts();malformed();
  std::cout<<"PASS: real production crypto adapter; RFC7748 keys; independent AES128/256-CTR, X25519/SHA256/AES256-CCM DM and ACK/NAK proof vectors; NodeInfo discovery; strict peer/request binding; tamper, malformed, weak-key and text bounds. Replay-cache/persistence/radio integration remain caller responsibilities.\n";
}
