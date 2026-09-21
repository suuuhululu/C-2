import { useEffect, useState } from "react";
import type { Snapshot } from "./api";
import {
  measuredVector,
  observationQuality,
  qualityLabels,
} from "./observations";

export default function RobotObservations({
  snapshot,
  connected,
}: {
  snapshot: Snapshot | null;
  connected: boolean;
}) {
  const [nowMs, setNowMs] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 500);
    return () => clearInterval(timer);
  }, []);
  const s = snapshot?.state;
  // 서버의 시계와 화면 시계 차이가 있으면 보수적으로 미확인 처리한다.
  const fresh = connected && snapshot?.connection === "CONNECTED";
  const joint = observationQuality(
    s?.joints_quality,
    s?.joints_measured_at,
    fresh,
    nowMs,
  );
  const tcp = observationQuality(
    s?.tcp_quality,
    s?.tcp?.header.stamp,
    fresh,
    nowMs,
  );
  const robot = observationQuality(
    s?.robot_quality,
    s?.robot_measured_at,
    fresh,
    nowMs,
  );
  const grip = observationQuality(
    s?.grip_quality,
    s?.grip_measured_at,
    fresh,
    nowMs,
  );
  const p = s?.tcp?.pose.position;
  return (
    <section className="panel observation-panel" aria-label="상시 로봇 관측">
      <h2>
        상시 로봇 관측{" "}
        <small>
          {snapshot?.transport === "MOCK" ? "모의 데이터" : "/c2/process_state"}
        </small>
      </h2>
      <p className="field-help">
        준비 Action 결과와 별개입니다. 상태 메시지 수신은 준비 성공·장착
        확인·실제 정지를 보장하지 않습니다.
      </p>
      <p className="field-help">
        첫 유효한 REAL 준비 요청 전에는 관측 설정이 연결되지 않아 관절·TCP가
        미확인일 수 있습니다. 준비 완료 후에도 상태 발행은 계속됩니다. 표시
        시각은 조회 관측 시각이며 원본 센서 시각을 보증하지 않습니다.
      </p>
      <dl className="preparation-values">
        <div>
          <dt>공정 상태 / 단계</dt>
          <dd>
            {fresh
              ? `${s?.status || "UNKNOWN"} / ${s?.phase || "—"}`
              : "미확인"}
          </dd>
        </div>
        <div>
          <dt>연결 / 운전 모드 · {qualityLabels[robot]}</dt>
          <dd>
            {robot === "VALID"
              ? `${s?.robot_connection_state || "UNKNOWN"} / ${s?.robot_mode || "UNKNOWN"}`
              : "미확인"}
          </dd>
        </div>
        <div>
          <dt>관절 J1~J6 (rad) · {qualityLabels[joint]}</dt>
          <dd>{measuredVector(s?.joints, 6, joint)}</dd>
        </div>
        <div>
          <dt>제어기 TCP XYZ (m) · {qualityLabels[tcp]}</dt>
          <dd>
            {measuredVector(p ? [p.x, p.y, p.z] : null, 3, tcp)} ·{" "}
            {s?.tcp?.header.frame_id || "좌표계 미확인"}
          </dd>
        </div>
        <div>
          <dt>그리퍼 관측 · {qualityLabels[grip]}</dt>
          <dd>
            {grip === "VALID" ? s?.grip_state : "미확인"} (닫힘만으로 도구
            고정을 판정하지 않음)
          </dd>
        </div>
        <div>
          <dt>보고된 도구 / 확인 출처</dt>
          <dd>
            {fresh
              ? `${s?.mounted_tool_id || "미확인"} / ${s?.tool_confirmation_source || "UNKNOWN"}`
              : "미확인"}
          </dd>
        </div>
        <div>
          <dt>정지 상태</dt>
          <dd>{fresh ? s?.stop_state || "UNKNOWN" : "미확인"}</dd>
        </div>
        <div>
          <dt>관절 / TCP 조회 관측 시각</dt>
          <dd>
            {s?.joints_measured_at || "미확인"}
            <br />
            {s?.tcp?.header.stamp || "미확인"}
          </dd>
        </div>
      </dl>
    </section>
  );
}
