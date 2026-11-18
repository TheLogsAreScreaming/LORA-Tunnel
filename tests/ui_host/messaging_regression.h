// SPDX-License-Identifier: MIT
// Same shared state-machine regressions run through both actual UI fixtures.
namespace ui_message_regression {
unsigned count=0;ui::Action last{};
void emit(ui::Action action,int,const char*){++count;last=action;}
template<class Check> void run(Check check) {
  using namespace ui::messages;
  ui::Model m;State s;count=0;
  open(s,m);choose(s,0,m,emit);
  check(count==1&&last==ui::Action::StartMessages&&s.screen==Screen::Mode,"queued start does not falsely show active message menu");
  m.messages_transitioning=true;refreshRecord(s,m);
  check(s.screen==Screen::Mode&&s.error[0],"asynchronous BLE preparation remains visible in protocol chooser");
  choose(s,1,m,emit);check(count==1&&s.screen==Screen::Mode,"protocol selection during radio transition emits no competing start");
  m.messages.active=true;m.messages.protocol=Protocol::Meshtastic;refreshRecord(s,m);
  check(s.screen==Screen::Mode,"active-looking stale model cannot bypass unfinished transition");
  m.messages_transitioning=false;m.messages.protocol=Protocol::MeshCore;refreshRecord(s,m);
  check(s.screen==Screen::Mode,"different active protocol does not satisfy pending start");
  m.messages.protocol=Protocol::Meshtastic;refreshRecord(s,m);
  check(s.screen==Screen::Menu&&s.pending_protocol==Protocol::Unknown,"matching active owner alone completes start UI");
  choose(s,7,m,emit);check(last==ui::Action::StopMessages&&s.screen==Screen::Mode,"protocol change first requests stop");
  m.messages.active=false;m.messages_transitioning=true;const auto stopped=count;
  choose(s,1,m,emit);check(count==stopped&&s.screen==Screen::Mode,"BLE restore blocks new protocol start");
  m.messages_transitioning=false;choose(s,1,m,emit);
  check(count==stopped+1&&s.screen==Screen::Mode,"restored radio accepts explicit next protocol request without assuming success");
  std::strcpy(m.notice,"Radio initialization failed");refreshRecord(s,m);
  check(s.screen==Screen::Mode&&!s.error[0],"failed start retains chooser and leaves owning notice visible");
  check(back(s,emit)==Result::Exit&&s.pending_protocol==Protocol::Unknown&&last==ui::Action::StopMessages,"Back cancels pending start rather than leaving latent UI activation");

  tunnel::messaging::Contact contacts[2]{};
  contacts[0].protocol=contacts[1].protocol=Protocol::Meshtastic;
  contacts[0].node=0x12345678;contacts[1].node=0xabcdef12;
  contacts[0].public_key[0]=1;contacts[1].public_key[0]=2;contacts[0].trusted=contacts[1].trusted=true;
  m.messages.contacts=contacts;m.messages.contact_count=2;m.messages.active=m.messages.tx_enabled=true;m.messages.protocol=Protocol::Meshtastic;
  s=State{};s.screen=Screen::Contacts;choose(s,0,m,emit);
  check(choose(s,0,m,emit)==Result::Edit,"trusted contact starts a snapshot-bound draft");
  const State selected=s;const auto original=contacts[0];const auto before=count;
  contacts[0]=contacts[1];check(!submit(s,"private draft",m,emit)&&count==before,"compacted contact index cannot redirect an existing private draft");
  contacts[0]=original;contacts[0].public_key[0]^=1;s=selected;check(!submit(s,"private draft",m,emit)&&count==before,"changed fingerprint blocks stale private draft");
  contacts[0]=original;contacts[0].node^=1;s=selected;check(!submit(s,"private draft",m,emit)&&count==before,"changed node with same public key blocks stale private draft");
  contacts[0]=original;contacts[0].trusted=false;s=selected;check(!submit(s,"private draft",m,emit)&&count==before,"revoked trust blocks private draft");
  contacts[0]=original;contacts[0].key_changed=true;s=selected;check(!submit(s,"private draft",m,emit)&&count==before,"key-change warning blocks private draft");
  contacts[0]=original;m.messages.protocol=Protocol::MeshCore;s=selected;check(!submit(s,"private draft",m,emit)&&count==before,"protocol switch cannot redirect private draft");
  m.messages.protocol=Protocol::Meshtastic;m.messages.contact_count=0;s=selected;check(!submit(s,"private draft",m,emit)&&count==before,"deleted contact blocks private draft");
  m.messages.contact_count=255;s=selected;s.target=8;check(!submit(s,"private draft",m,emit)&&count==before,"malformed count cannot extend contact backing array");
  m.messages.contact_count=2;s=selected;check(submit(s,"private draft",m,emit)&&count==before+1&&last==ui::Action::SendMessage,"unchanged trusted snapshot may submit one private message");
  s.screen=Screen::Menu;choose(s,1,m,emit);const auto channelBefore=count;m.messages.protocol=Protocol::MeshCore;
  check(!submit(s,"channel draft",m,emit)&&count==channelBefore,"channel draft cannot silently move to another protocol");
}
}
