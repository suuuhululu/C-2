import { useEffect, useRef, useState } from "react";
import { ApiError, request } from "./api";
import type { PreparationRecord, PreparationState, Snapshot } from "./api";
import {
  measurementPoints,
  preparationLabel,
  preparationStages,
} from "./preparation";

type Body = {
  request_id: string;
  input_profile_snapshot_id: string;
  input_profile_sha256: string;
  height_m: number;
};
const pendingKey = "c2-preparation-request";
const value = (n?: number | null, scale = 1) =>
  n != null && Number.isFinite(n)
    ? (n * scale).toFixed(scale === 1 ? 4 : 1)
    : "미확인";

export default function PreparationPanel({
  data,
  connected,
  locked,
  onSnapshot,
  onError,
  onInvalidate,
}: {
  data: PreparationState;
  connected: boolean;
  locked: boolean;
  onSnapshot: (snapshot: Snapshot) => void;
  onError: (message: string) => void;
  onInvalidate: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [history, setHistory] = useState<PreparationRecord[] | null>(null);
  const body = useRef<Body | null>(null);
  const current = data.current;
  const real = data.input_config?.payload.source_mode === "REAL";
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(pendingKey);
      if (saved) {
        body.current = JSON.parse(saved);
        setUncertain(true);
      }
    } catch {
      sessionStorage.removeItem(pendingKey);
    }
  }, []);
  useEffect(() => {
    if (current?.request_id === body.current?.request_id) {
      body.current = null;
      sessionStorage.removeItem(pendingKey);
      setUncertain(false);
    }
  }, [current?.request_id, data.input_config?.id]);
  async function refresh() {
    onSnapshot(await request<Snapshot>("/snapshot"));
  }
  async function begin() {
    const config = data.input_config;
    if (!config || !data.supported) return;
    if (
      !connected ||
      pending ||
      (!body.current && (locked || data.blocks_work || !!data.start_error))
    )
      return;
    onInvalidate();
    if (!body.current)
      body.current = {
        request_id: crypto.randomUUID(),
        input_profile_snapshot_id: config.id,
        input_profile_sha256: config.sha256,
        height_m: config.payload.workcell.height_m,
      };
    sessionStorage.setItem(pendingKey, JSON.stringify(body.current));
    setPending(true);
    try {
      // 새로고침 후 불확실 요청은 먼저 조회한다. 과거 수동 체크 본문을 새 요청으로 재전송하지 않는다.
      if (uncertain) {
        try {
          await request(`/preparations/${body.current!.request_id}`);
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 404)) throw e;
          await request("/preparations", body.current);
        }
      } else await request("/preparations", body.current);
      body.current = null;
      sessionStorage.removeItem(pendingKey);
      setUncertain(false);
      await refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status < 500) {
        body.current = null;
        sessionStorage.removeItem(pendingKey);
        setUncertain(false);
      } else setUncertain(true);
      onError((e as Error).message);
    } finally {
      setPending(false);
    }
  }
  async function cancel() {
    if (!current || pending) return;
    onInvalidate();
    setPending(true);
    try {
      await request(`/preparations/${current.request_id}/cancel`, {});
      await refresh();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setPending(false);
    }
  }
  const observed = current?.result?.observed_state;
  const m = observed?.measurement;
  const geometry =
    current?.result?.outcome === "SUCCEEDED" && m?.geometry_ready ? m : null;
  const points = measurementPoints(current?.feedback || []);
  if (geometry?.contact_indices) {
    for (const i of geometry.contact_indices) {
      if (Number.isInteger(i) && i >= 1 && i <= 8) points[i - 1] = "SUCCEEDED";
    }
  }
  const reportedCount = current?.feedback.at(-1)?.completed_side_points;
  const canCancel =
    current && ["ACCEPTED", "RUNNING", "CANCELING"].includes(current.state);
  return (
    <section className="panel preparation-panel" aria-label="양초 준비와 측정">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">PREPARATION / 01</span>
          <h2>양초 준비·측정</h2>
        </div>
        <span className="tag">
          {data.supported
            ? `${data.transport} · ${real ? "REAL 실제 측정" : "SIM 전용"}`
            : "ROS 연결 대기"}
        </span>
      </div>
      <p className="field-help">{data.reason}{data.start_error && <strong role="alert"> {data.start_error}</strong>}</p>
      {data.input_config && (
        <p className="field-help">
          <a
            href={`/api/operator/assets/${data.input_config.id}/content`}
            target="_blank"
            rel="noreferrer"
          >
            측정 전 설정 원본
          </a>{" "}
          · ID {data.input_config.id} · SHA-256 {data.input_config.sha256}
        </p>
      )}
      <div className="preparation-columns">
        <div>
          <p>
            양초 높이{" "}
            <b>
              {value(data.input_config?.payload.workcell.height_m, 1000)} mm
            </b>{" "}
            · 운영자 자 측정 입력
          </p>
          <p className="field-help">
            측정 전 드릴을 수동으로 끄세요. 프로그램은 드릴 전원·그리퍼 개폐를
            제어하지 않습니다. 장착 상태는 제어의 실제 관측으로 확인하며,
            화면에서 정상값을 생성하지 않습니다.
          </p>
          <button
            className="primary"
            onClick={begin}
            disabled={
              !data.supported ||
              !connected ||
              pending ||
              (!uncertain && (locked || data.blocks_work || !!data.start_error))
            }
          >
            {pending
              ? "요청 확인 중…"
              : uncertain
                ? "같은 요청으로 접수 확인"
                : current
                  ? "다시 준비·측정"
                  : "사전 검사·양초 측정 요청"}
          </button>
        </div>
        <div role="status" aria-live="polite">
          <strong>
            {current?.state === "SUCCEEDED" &&
            current.binding_status === "MEASUREMENT_ONLY"
              ? "REAL 측정 결과 수신 완료 · 경로/조각 미승인"
              : preparationLabel(current?.state, data.ready)}
          </strong>
          <p>
            진행 단계:{" "}
            {preparationStages[current?.stage || ""] ||
              current?.stage ||
              "요청 대기"}
          </p>
          <p>
            {current?.message ||
              current?.result?.message ||
              current?.feedback.at(-1)?.message ||
              "최종 준비 결과가 확인되어야 측정값을 사용할 수 있습니다."}
          </p>
          <div className="measurement-points" aria-label="옆면 8점 측정 상태">
            {points.map((state, i) => (
              <span
                key={i}
                className={`point-${state.toLowerCase()}`}
                title={`${i + 1}/8: ${state}`}
                aria-label={`${i + 1}번 점 ${state === "SUCCEEDED" ? "완료" : state === "RUNNING" ? "측정 중" : "미완료"}`}
              >
                {i + 1}
              </span>
            ))}
          </div>
          {reportedCount !== undefined && (
            <p>
              Action 진행 보고: 옆면 {reportedCount}/8점 (최종 결과 검증 전)
            </p>
          )}
          <p className="field-help">
            초록색은 각 점의 성공 응답입니다. 8점 완료만으로 준비 성공이나 실행
            승인을 뜻하지 않습니다.
          </p>
          {canCancel && (
            <button
              onClick={cancel}
              disabled={pending || current.state === "CANCELING"}
            >
              준비·측정 취소
            </button>
          )}
          <p className="field-help">
            취소 접수는 실제 정지 완료가 아닙니다. 최종 결과를 기다리고 드릴은
            수동으로 꺼주세요.
          </p>
          {observed && (
            <p>
              정지 확인:{" "}
              {observed.stop_confirmed === true
                ? `확인됨 (${real ? "제어 Result 보고" : "SIM"})`
                : observed.stop_confirmed === false
                  ? "미확인"
                  : "확인 근거 없음"}{" "}
              · {observed.partial ? "부분 결과" : "전체 결과"}
            </p>
          )}
          {m && (
            <dl className="preparation-values">
              <div>
                <dt>중심 X / Y (m)</dt>
                <dd>
                  {value(geometry?.axis_xy_m?.[0])} /{" "}
                  {value(geometry?.axis_xy_m?.[1])}
                </dd>
              </div>
              <div>
                <dt>반지름 (mm)</dt>
                <dd>{value(geometry?.radius_m, 1000)}</dd>
              </div>
              <div>
                <dt>윗면 Z / 계산한 바닥 Z (m)</dt>
                <dd>
                  {value(geometry?.top_z_m)} / {value(geometry?.bottom_z_m)}
                </dd>
              </div>
              <div>
                <dt>측정 유효 상태</dt>
                <dd>
                  {m.validity} ·{" "}
                  {m.geometry_ready
                    ? "기하 결과 있음"
                    : "경로 생성에 사용 불가"}
                </dd>
              </div>
            </dl>
          )}
          {m && (
            <p className="field-help">
              {real
                ? "실제 접촉 기반 결과 · ESTIMATED는 확인 수준 표시입니다. BIND와 실행 검사는 별도로 판단합니다."
                : "SIM 합성값"}{" "}
              · 수직 원통 가정 · 기울기·독립 정확도 미검증
            </p>
          )}
          {current && (
            <details>
              <summary>준비 기록·원본 보기</summary>
              <p>
                준비 {current.goal.preparation_id}
                <br />
                측정 {current.goal.measurement_id}
              </p>
              <a
                href={`/api/operator/preparations/${current.request_id}`}
                target="_blank"
                rel="noreferrer"
              >
                요청·진행·최종 결과
              </a>
              {current.measurement_record && (
                <>
                  {" "}
                  ·{" "}
                  <a
                    href={`/api/operator/assets/${current.measurement_record.id}/content`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    측정 원본
                  </a>
                </>
              )}
              {current.profile_snapshot && (
                <p>
                  측정 후 설정 {current.profile_snapshot.id} ·{" "}
                  {data.ready ? "SIM 제어 등록 확인" : "재연결 필요"}
                </p>
              )}
            </details>
          )}
        </div>
      </div>
      <details
        onToggle={(e) => {
          if (e.currentTarget.open)
            request<PreparationRecord[]>("/preparations")
              .then(setHistory)
              .catch((err) => onError(err.message));
        }}
      >
        <summary>이전 준비 이력</summary>
        {history?.length ? (
          <ul>
            {history.map((r) => (
              <li key={r.request_id}>
                <a
                  href={`/api/operator/preparations/${r.request_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {r.created_at} · {r.request_id.slice(0, 8)} · {r.state}
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p>준비 기록이 없습니다.</p>
        )}
      </details>
    </section>
  );
}
