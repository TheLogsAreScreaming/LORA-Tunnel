// SPDX-License-Identifier: MIT
#include "meshcore_message.h"
#include "vectors.h"
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <RNG.h>
// This harness supplies fixed public synthetic seeds. Unused upstream random
// generation entry points must never be called by the tested adapter.
RNGClass::RNGClass() {}
RNGClass::~RNGClass() {}
void RNGClass::rand(std::uint8_t*,std::size_t){std::abort();}
RNGClass RNG;
using namespace tunnel::meshcore_message;
static unsigned checks=0;
#define CHECK(x) do{++checks;if(!(x)){std::fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x);std::exit(1);}}while(0)
template<std::size_t N> void matches(const Frame& frame,const std::uint8_t (&expected)[N]){
  CHECK(frame.length==N);CHECK(std::memcmp(frame.bytes,expected,N)==0);
}
static Contact contact(const Identity& id,const char* name){Contact c;std::memcpy(c.public_key,id.public_key,32);std::strncpy(c.name,name,31);return c;}
static Frame encryptedPeer(const Identity& sender,const Identity& recipient,std::uint8_t type,const std::uint8_t* plaintext,std::size_t n){
  Frame f;const Crypto& c=platformCrypto();std::uint8_t secret[32],hash[32];CHECK(c.shared(sender.seed,recipient.public_key,secret));
  f.bytes[0]=(type<<2)|1;f.bytes[2]=recipient.public_key[0];f.bytes[3]=sender.public_key[0];
  CHECK(c.ecb(true,secret,plaintext,n,f.bytes+6));CHECK(c.hmac(secret,f.bytes+6,n,hash));
  std::memcpy(f.bytes+4,hash,2);f.length=n+6;return f;
}
int main(){
  const Crypto& crypto=platformCrypto();Identity alice,bob,collision;
  CHECK(identity(vectors::seed_a,crypto,alice));CHECK(identity(vectors::seed_b,crypto,bob));CHECK(identity(vectors::seed_collision,crypto,collision));
  CHECK(std::memcmp(alice.public_key,vectors::pub_a,32)==0);CHECK(std::memcmp(bob.public_key,vectors::pub_b,32)==0);
  Identity aliased;std::memcpy(aliased.seed,vectors::seed_a,32);CHECK(identity(aliased.seed,crypto,aliased));CHECK(std::memcmp(aliased.public_key,alice.public_key,32)==0);
  std::uint8_t shared[32],back[32];CHECK(crypto.shared(alice.seed,bob.public_key,shared));CHECK(crypto.shared(bob.seed,alice.public_key,back));
  CHECK(std::memcmp(shared,back,32)==0);CHECK(std::memcmp(shared,vectors::shared_ab,32)==0);
  std::uint8_t bad[32]{};CHECK(!crypto.shared(alice.seed,bad,shared));bad[0]=1;CHECK(!crypto.shared(alice.seed,bad,shared));
  for(auto b:shared)CHECK(b==0);
  Contact a=contact(alice,"Alice"),b=contact(bob,"Bob"),other=contact(collision,"SameHash");
  CHECK(b.public_key[0]==other.public_key[0]);
  Frame f;Contact parsed;Message m;
  CHECK(advert(alice,"Alice",0x66554433,crypto,f));matches(f,vectors::advert_a);
  CHECK(parseAdvert(f.bytes,f.length,crypto,parsed));CHECK(std::strcmp(parsed.name,"Alice")==0);CHECK(parsed.timestamp==0x66554433);
  CHECK(std::memcmp(parsed.public_key,alice.public_key,32)==0);
  for(std::size_t i=2;i<f.length;++i){Frame tampered=f;tampered.bytes[i]^=1;CHECK(!parseAdvert(tampered.bytes,tampered.length,crypto,parsed));}
  CHECK(!advert(alice,"Alice",0,crypto,f));CHECK(!parseAdvert(nullptr,0,crypto,parsed));
  CHECK(groupText(publicGroupKey(),16,"Alice","hello mesh",0x66554433,0,crypto,f));matches(f,vectors::group16);
  CHECK(parseGroup(f.bytes,f.length,publicGroupKey(),16,crypto,m));CHECK(m.kind==Kind::GroupText);CHECK(std::strcmp(m.text,"hello mesh")==0);CHECK(std::strcmp(m.name,"Alice")==0);
  CHECK(groupText(vectors::key32,32,"Alice","hello mesh",0x66554433,0,crypto,f));matches(f,vectors::group32);
  CHECK(parseGroup(f.bytes,f.length,vectors::key32,32,crypto,m));CHECK(!parseGroup(f.bytes,f.length,publicGroupKey(),16,crypto,m));CHECK(m.kind==Kind::None);
  for(std::size_t i=3;i<f.length;++i){Frame tampered=f;tampered.bytes[i]^=1;CHECK(!parseGroup(tampered.bytes,tampered.length,vectors::key32,32,crypto,m));}
  CHECK(!groupText(vectors::key32,31,"Alice","hello",1,0,crypto,f));CHECK(!groupText(vectors::key32,32,"Alice","hello",1,4,crypto,f));
  std::uint8_t ack[4];CHECK(directText(alice,b,"hello mesh",0x66554433,0,crypto,f,ack));matches(f,vectors::direct_a_b);CHECK(std::memcmp(ack,vectors::ack_a_b,4)==0);
  CHECK(parseDirect(f.bytes,f.length,bob,a,crypto,m));CHECK(m.kind==Kind::DirectText);CHECK(m.flood);CHECK(std::strcmp(m.text,"hello mesh")==0);CHECK(std::memcmp(m.ack,ack,4)==0);
  CHECK(!parseDirect(f.bytes,f.length,alice,b,crypto,m)); // wrong destination
  CHECK(!parseDirect(f.bytes,f.length,collision,a,crypto,m)); // same destination wire byte, different secret
  for(std::size_t i=2;i<f.length;++i){Frame tampered=f;tampered.bytes[i]^=1;CHECK(!parseDirect(tampered.bytes,tampered.length,bob,a,crypto,m));}
  // Inject a mutable flood route collected by relays, preserving the ciphertext.
  Frame routed=f;std::memmove(routed.bytes+5,routed.bytes+2,routed.length-2);routed.bytes[1]=3;routed.bytes[2]=0xaa;routed.bytes[3]=0xbb;routed.bytes[4]=0xcc;routed.length+=3;
  CHECK(parseDirect(routed.bytes,routed.length,bob,a,crypto,m));CHECK(m.path_encoding==3);CHECK(m.path[2]==0xcc);
  Frame receipt;CHECK(reply(bob,a,m,crypto,receipt));matches(receipt,vectors::path_b_a);
  CHECK(parseReceipt(receipt.bytes,receipt.length,alice,b,ack,crypto,m));CHECK(m.receipt_trust==ReceiptTrust::AuthenticatedPeer);CHECK(m.path_encoding==3);
  CHECK(std::memcmp(m.sender,b.public_key,32)==0);CHECK(std::memcmp(m.recipient,a.public_key,32)==0);
  CHECK(parseReceipt(vectors::path_b_a_6,sizeof(vectors::path_b_a_6),alice,b,ack,crypto,m));
  CHECK(!parseReceipt(receipt.bytes,receipt.length,alice,other,ack,crypto,m)); // same source hash, wrong shared secret
  CHECK(!parseReceipt(receipt.bytes,receipt.length,bob,a,ack,crypto,m));
  std::uint8_t wrongAck[4];std::memcpy(wrongAck,ack,4);wrongAck[3]^=1;CHECK(!parseReceipt(receipt.bytes,receipt.length,alice,b,wrongAck,crypto,m));
  for(std::size_t i=2;i<receipt.length;++i){Frame tampered=receipt;tampered.bytes[i]^=1;CHECK(!parseReceipt(tampered.bytes,tampered.length,alice,b,ack,crypto,m));}
  // Exact attempt correlation: same timestamp/text at attempt 1 must not settle
  // against an attempt-0 receipt. Root retains bounded outstanding attempt hashes.
  std::uint8_t retryAck[4];CHECK(directText(alice,b,"hello mesh",0x66554433,1,crypto,f,retryAck));CHECK(std::memcmp(ack,retryAck,4)!=0);
  CHECK(!parseReceipt(receipt.bytes,receipt.length,alice,b,retryAck,crypto,m));
  // A non-flood incoming message requires a bare ACK, which the wire cannot
  // authenticate. Do not upgrade its hash-only correlation to peer identity.
  CHECK(directText(alice,b,"hello mesh",0x66554433,0,crypto,f,ack));f.bytes[0]=(2<<2)|2;
  CHECK(parseDirect(f.bytes,f.length,bob,a,crypto,m));CHECK(!m.flood);CHECK(reply(bob,a,m,crypto,receipt));CHECK(receipt.length==6);
  CHECK(parseReceipt(receipt.bytes,receipt.length,alice,b,ack,crypto,m));CHECK(m.receipt_trust==ReceiptTrust::HashOnly);
  CHECK(!parseReceipt(receipt.bytes,receipt.length,alice,b,wrongAck,crypto,m));
  receipt.bytes[receipt.length++]=5;receipt.bytes[receipt.length++]=0xfe;CHECK(parseReceipt(receipt.bytes,receipt.length,alice,b,ack,crypto,m));
  receipt.length=7;CHECK(!parseReceipt(receipt.bytes,receipt.length,alice,b,ack,crypto,m));
  // Header path limits, unsupported versions, truncations, full bounded strings.
  CHECK(directText(alice,b,"hello mesh",0x66554433,0,crypto,f,ack));
  for(std::size_t n=0;n<f.length;++n)CHECK(!parseDirect(f.bytes,n,bob,a,crypto,m));
  Frame malformed=f;malformed.bytes[0]|=0x40;CHECK(!parseDirect(malformed.bytes,malformed.length,bob,a,crypto,m));
  malformed=f;malformed.bytes[1]=0xc0;CHECK(!parseDirect(malformed.bytes,malformed.length,bob,a,crypto,m));
  malformed=f;malformed.bytes[1]=0xbf;CHECK(!parseDirect(malformed.bytes,malformed.length,bob,a,crypto,m));
  CHECK(!parseDirect(f.bytes,256,bob,a,crypto,m));CHECK(!parseReceipt(nullptr,0,alice,b,ack,crypto,m));
  // These packets have correct MACs but unsupported/malformed plaintext. A
  // parser that stops after successful crypto would mistakenly accept them.
  std::uint8_t malformedPlain[16]{};malformedPlain[0]=1;malformedPlain[4]=4;malformedPlain[5]='x';
  malformed=encryptedPeer(alice,bob,2,malformedPlain,16);CHECK(!parseDirect(malformed.bytes,malformed.length,bob,a,crypto,m));
  malformedPlain[4]=0;malformedPlain[6]=0;malformedPlain[7]=1;
  malformed=encryptedPeer(alice,bob,2,malformedPlain,16);CHECK(!parseDirect(malformed.bytes,malformed.length,bob,a,crypto,m));
  malformedPlain[7]=5; // current upstream's explicit extended attempt tail
  malformed=encryptedPeer(alice,bob,2,malformedPlain,16);CHECK(parseDirect(malformed.bytes,malformed.length,bob,a,crypto,m));CHECK(std::strcmp(m.text,"x")==0);
  std::memset(malformedPlain,0,16);malformedPlain[0]=0xc0;malformedPlain[1]=3;std::memcpy(malformedPlain+2,ack,4);
  malformed=encryptedPeer(bob,alice,8,malformedPlain,16);CHECK(!parseReceipt(malformed.bytes,malformed.length,alice,b,ack,crypto,m));
  malformedPlain[0]=0;malformedPlain[1]=2;
  malformed=encryptedPeer(bob,alice,8,malformedPlain,16);CHECK(!parseReceipt(malformed.bytes,malformed.length,alice,b,ack,crypto,m));
  malformedPlain[1]=3;malformedPlain[15]=1;
  malformed=encryptedPeer(bob,alice,8,malformedPlain,16);CHECK(!parseReceipt(malformed.bytes,malformed.length,alice,b,ack,crypto,m));
  char maximum[121],tooLong[122],name[32],longName[33];std::memset(maximum,'x',120);maximum[120]=0;std::memset(tooLong,'x',121);tooLong[121]=0;
  std::memset(name,'n',31);name[31]=0;std::memset(longName,'n',32);longName[32]=0;
  CHECK(directText(alice,b,maximum,1,0,crypto,f,ack));CHECK(f.length<=255);CHECK(parseDirect(f.bytes,f.length,bob,a,crypto,m));CHECK(std::strlen(m.text)==120);
  CHECK(!directText(alice,b,tooLong,1,0,crypto,f,ack));CHECK(f.length==0);CHECK(!directText(alice,b,"",1,0,crypto,f,ack));
  CHECK(groupText(vectors::key32,32,name,maximum,1,0,crypto,f));CHECK(parseGroup(f.bytes,f.length,vectors::key32,32,crypto,m));CHECK(std::strlen(m.text)==120);CHECK(std::strlen(m.name)==31);
  CHECK(!groupText(vectors::key32,32,longName,maximum,1,0,crypto,f));CHECK(advert(alice,name,1,crypto,f));CHECK(parseAdvert(f.bytes,f.length,crypto,parsed));
  CHECK(!advert(alice,longName,1,crypto,f));
  // Explicit adapter failure must not expose a partially parsed output/frame.
  Crypto missing=crypto;missing.shared=nullptr;CHECK(!directText(alice,b,"test",1,0,missing,f,ack));CHECK(f.length==0);
  missing=crypto;missing.verify=nullptr;CHECK(!parseAdvert(vectors::advert_a,sizeof(vectors::advert_a),missing,parsed));
  std::printf("MeshCore message tests passed: %u checks (independent wire/crypto fixtures, adverts, groups, DMs, receipts, bounds and tampering)\n",checks);
}
