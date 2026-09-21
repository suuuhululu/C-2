#include "dsr_hardware2/control_authority_observation.hpp"
#include <cassert>
#include <iostream>
int main() {
  dsr_hardware2::AuthorityObservation s;
  assert(!s.snapshot(0).valid);
  s.monitoring_tick(1); assert(!s.snapshot(1).valid);
  s.reset(); s.access_event(2,10); s.monitoring_tick(20);
  assert(s.snapshot(30).valid && s.snapshot(30).has_control); // 초기 HW GRANT 보존
  s.access_event(0,31); s.access_event(1,32);
  assert(s.snapshot(40).has_control); // REQUEST/DENY와 현재 보유권 구분
  s.access_event(3,50); assert(s.snapshot(60).valid && !s.snapshot(60).has_control);
  s.access_event(2,70); s.disconnect(); assert(!s.snapshot(71).valid);
  s.monitoring_tick(72); assert(!s.snapshot(73).valid); // 이전 GRANT 재사용 금지
  s.access_event(2,80); assert(s.snapshot(81).has_control);
  assert(!s.snapshot(700).connected && !s.snapshot(700).valid);
  s.monitoring_tick(710); assert(!s.snapshot(711).valid); // 조용한 단절 후 재연결
  s.access_event(2,720); assert(s.snapshot(721).has_control);
  s.access_event(99,722); assert(!s.snapshot(723).valid);
  std::cout << "PASS: startup, grant, request/deny, loss, disconnect, stale, reconnect, unknown\n";
}
