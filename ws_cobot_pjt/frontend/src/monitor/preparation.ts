import type { PreparationFeedback } from "./api";

export function activePreparation(state?: string) {
  return ["ACCEPTED", "RUNNING", "CANCELING"].includes(state || "");
}

// 단계 진입이나 COMPLETE 피드백을 8점 성공으로 보간하지 않는다.
export function measurementPoints(events: PreparationFeedback[]) {
  const points = Array<string>(8).fill("PENDING");
  let sequence = 0;
  for (const event of events) {
    if (typeof event.sequence !== "number" || event.sequence <= sequence)
      continue;
    sequence = event.sequence;
    if (
      event.stage !== "SIDE_TOUCH" ||
      event.total_points !== 8 ||
      typeof event.point_index !== "number" ||
      !Number.isInteger(event.point_index) ||
      event.point_index < 1 ||
      event.point_index > 8
    )
      continue;
    if (
      ["RUNNING", "SUCCEEDED", "FAILED", "STOPPED", "UNKNOWN"].includes(
        event.status || "",
      )
    )
      points[event.point_index - 1] = event.status!;
  }
  return points;
}

export function preparationLabel(state?: string, ready = false) {
  if (state === "SUCCEEDED")
    return ready
      ? "SIM 준비·측정·등록 완료"
      : "이전 준비 기록 · 다시 준비 필요";
  return (
    (
      {
        ACCEPTED: "준비 요청 접수",
        RUNNING: "준비·측정 진행 중",
        CANCELING: "취소 요청 · 종료 확인 중",
        STOPPED: "준비 취소 완료",
        FAILED: "준비 실패",
        UNKNOWN: "준비 종료 미확인 · 다음 작업 차단",
        INVALIDATED: "다시 준비 필요",
      } as Record<string, string>
    )[state || ""] || "준비·측정 대기"
  );
}

export const preparationStages: Record<string, string> = {
  VALIDATING: "요청·설정 검사",
  ROBOT_STATUS: "로봇 상태 검사",
  ROBOT_CHECK: "로봇 상태 검사",
  HOME_CHECK: "홈 위치 확인",
  HOME_MOVE: "홈 이동 중",
  HOME_RECHECK: "홈 도착·정지 후 재검사",
  MEASUREMENT_PRECHECK: "측정 접근·후퇴 조건 검사",
  TOP_APPROACH: "윗면 접근",
  TOP_TOUCH: "윗면 접촉 측정",
  SIDE_START: "옆면 측정 시작",
  SIDE_TOUCH: "옆면 8점 측정",
  RETRACT: "정상 후퇴·정지 확인",
  FIT: "측정값 계산·검증",
  BINDING: "측정 스냅샷 연결 확인",
  COMPLETE: "최종 결과 확인",
};

// UI 확인을 특정 작업 맥락에만 귀속. HTTP/ROS 데이터에는 넣지 않는다.
export function executionConfirmationKey(parts: unknown[], available: boolean) {
  return available ? JSON.stringify(parts) : "";
}
