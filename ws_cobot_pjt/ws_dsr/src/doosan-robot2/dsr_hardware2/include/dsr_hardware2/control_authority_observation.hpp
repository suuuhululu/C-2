#pragma once
// C-2: 제어권 콜백을 읽기 전용으로 보존한다. 제어권 요청/로봇 명령 없음.
#include <cstdint>
#include <mutex>

namespace dsr_hardware2 {
struct AuthoritySnapshot {
  bool connected{false};
  bool valid{false};
  bool has_control{false};
  int last_event{-1};
  int64_t monitoring_age_ms{-1};
};

class AuthorityObservation {
 public:
  void reset() {
    std::lock_guard<std::mutex> lock(mutex_);
    known_ = held_ = false; disconnected_ = true;
    last_event_ = -1; tick_ms_ = decision_ms_ = -1;
  }
  void access_event(int event, int64_t now_ms) {
    std::lock_guard<std::mutex> lock(mutex_);
    last_event_ = event;
    // DRFC.h: REQUEST=0, DENY=1, GRANT=2, LOSS=3.
    // REQUEST/DENY는 요청의 이벤트이며 현재 보유권 자체를 바꾸지 않는다.
    if (event == 2 || event == 3) {
      known_ = true; held_ = event == 2; decision_ms_ = now_ms;
    } else if (event != 0 && event != 1) {
      known_ = false;
    }
  }
  void monitoring_tick(int64_t now_ms) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (tick_ms_ >= 0 && now_ms-tick_ms_ > timeout_ms &&
        now_ms-decision_ms_ > timeout_ms) known_ = false;
    tick_ms_ = now_ms; disconnected_ = false;
  }
  void disconnect() {
    std::lock_guard<std::mutex> lock(mutex_);
    disconnected_ = true; known_ = held_ = false;
  }
  AuthoritySnapshot snapshot(int64_t now_ms) {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto age = tick_ms_ < 0 ? -1 : now_ms-tick_ms_;
    const bool connected = !disconnected_ && age >= 0 && age <= timeout_ms;
    // 주기 발행이 오래된 GRANT를 새 관측처럼 되살리지 않게 한다.
    if (!connected && now_ms-decision_ms_ > timeout_ms) known_ = false;
    return {connected, connected && known_, connected && known_ && held_, last_event_, age};
  }
  static constexpr int64_t timeout_ms = 500;
 private:
  std::mutex mutex_;
  bool known_{false}, held_{false}, disconnected_{true};
  int last_event_{-1};
  int64_t tick_ms_{-1}, decision_ms_{-1};
};

// 하드웨어 초기 GRANT와 컨트롤러 콜백이 동일 캐시를 사용한다 (M0609 1대 구성).
AuthorityObservation & control_authority_observation();
int64_t authority_steady_ms();
}  // namespace dsr_hardware2
