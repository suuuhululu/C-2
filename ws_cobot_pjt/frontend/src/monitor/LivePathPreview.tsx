import { useRef, useState } from "react";
import type { PathResult, Profile, Run, SegmentObservation } from "./api";
import { cutStrokes, cylinderPoint, pathProgressStates } from "./preview";

const styles = {
  PENDING: { color: "#292f2c", label: "가공 예정", dash: undefined },
  IN_PROGRESS: { color: "#c3922d", label: "진행 중", dash: undefined },
  COMPLETED: { color: "#2e7293", label: "이동 완료", dash: undefined },
  PASSED: { color: "#168348", label: "가공 확인", dash: undefined },
  FAILED: { color: "#c34437", label: "가공 실패", dash: undefined },
  UNKNOWN: { color: "#929b96", label: "판정 미확인", dash: "1.5 1.2" },
};

const progressStyles = {
  PENDING: { ...styles.PENDING, label: "미완료" },
  IN_PROGRESS: styles.IN_PROGRESS,
  COMPLETED: styles.COMPLETED,
  UNKNOWN: { ...styles.UNKNOWN, label: "진행 미확인" },
};

export default function LivePathPreview({
  path,
  run,
  profile: currentProfile,
  fresh,
}: {
  path: PathResult | null;
  run: Run;
  profile?: Profile;
  fresh: boolean;
}) {
  const [yaw, setYaw] = useState(0),
    drag = useRef<number | null>(null);
  const evidence = run.execution_preview;
  const profile = path?.profile_snapshot ?? currentProfile;
  const match =
    path &&
    evidence?.contract === "mock-execution-preview/1" &&
    evidence.run_id === run.run_id &&
    evidence.path_id === path.path_id &&
    evidence.path_version === path.path_version &&
    evidence.path_sha256 === path.path_sha256;
  const observations = match ? evidence.observations : [];
  const strokes = cutStrokes(path);
  const pathMatchesRun =
    !!path &&
    path.path_id === run.path_id &&
    path.path_version === run.path_version &&
    path.path_sha256 === run.path_sha256;
  const progressStates = pathMatchesRun
    ? pathProgressStates(
        strokes,
        run.engraving_progress,
        run.phase,
        run.status,
        fresh,
      )
    : {};
  const terminal = ["SUCCEEDED", "FAILED", "STOPPED"].includes(run.status);
  function verdict(o?: SegmentObservation) {
    if (!o) return "UNKNOWN";
    if (
      (!fresh || run.status === "UNKNOWN") &&
      !terminal &&
      ["PENDING", "IN_PROGRESS"].includes(o.verdict)
    )
      return "UNKNOWN";
    return o.verdict;
  }
  function paint(segment: string, point: number) {
    if (!match) {
      const state = progressStates[`${segment}:${point}`] || "UNKNOWN";
      return progressStyles[state];
    }
    return styles[
      verdict(
        observations.find(
          (o) =>
            o.segment_id === segment &&
            point >= o.start_point_index &&
            point < o.end_point_index,
        ),
      )
    ];
  }
  const half = Math.PI * (profile?.payload.surface.radius_mm || 34);
  const r = (profile?.payload.surface.radius_mm || 34) / 1000;
  const h = (profile?.payload.surface.height_mm || 150) / 1000;
  const scale = 1050,
    cx = 95,
    cy = 110,
    rad = r * scale,
    top = cy - (h / 2) * scale,
    bottom = cy + (h / 2) * scale;
  function project(point: number[]) {
    const p = cylinderPoint(point, profile);
    const x = p[0] * Math.cos(yaw) - p[1] * Math.sin(yaw),
      depth = p[0] * Math.sin(yaw) + p[1] * Math.cos(yaw);
    return [
      cx + x * scale,
      cy - (p[2] - h / 2) * scale + depth * scale * 0.2,
      depth,
    ];
  }
  const failures = observations.filter(
    (o) => o.verdict === "FAILED" || o.verdict === "UNKNOWN",
  );
  const legend = match
    ? ["PENDING", "IN_PROGRESS", "PASSED", "FAILED", "UNKNOWN"]
    : ["PENDING", "IN_PROGRESS", "COMPLETED", "UNKNOWN"];
  const progressCounts = Object.values(progressStates).reduce(
    (counts, state) => ({ ...counts, [state]: (counts[state] || 0) + 1 }),
    {} as Record<string, number>,
  );
  return (
    <section className="live-path" aria-label="실시간 경로 진행과 가공 판정">
      <div className="live-path-heading">
        <h3>실시간 경로 확인</h3>
        <span>
          {match
            ? "모의 판정 · 압력 센서 미연결"
            : "공정 진행 피드백 · 품질 판정 아님"}
        </span>
      </div>
      <div className="path-legend">
        {legend.map((key) => {
          const s = match
            ? styles[key as keyof typeof styles]
            : progressStyles[key as keyof typeof progressStyles];
          return (
            <span key={key}>
              <i
                style={{
                  borderColor: s.color,
                  borderStyle: key === "UNKNOWN" ? "dashed" : "solid",
                }}
              />
              {s.label}
              <b>
                {match
                  ? observations.filter((o) => verdict(o) === key).length
                  : progressCounts[key] || 0}
              </b>
            </span>
          );
        })}
      </div>
      {!pathMatchesRun && (
        <p className="field-help">
          실행 경로와 진행 데이터의 연결을 확인하는 중입니다.
        </p>
      )}
      <div className="live-path-canvases">
        <svg
          viewBox="-120 -158 240 172"
          role="img"
          aria-label={
            match
              ? "전개면 경로: 검정 예정, 황색 진행, 초록 확인, 빨강 실패, 회색 미확인"
              : "전개면 경로: 검정 미완료, 황색 진행, 파랑 이동 완료, 회색 진행 미확인"
          }
        >
          <defs>
            <pattern
              id="live-grid"
              width="10"
              height="10"
              patternUnits="userSpaceOnUse"
            >
              <path
                d="M10 0H0V10"
                fill="none"
                stroke="#dfe7dc"
                strokeWidth=".25"
              />
            </pattern>
          </defs>
          <rect
            x={-half}
            y="-150"
            width={half * 2}
            height="150"
            fill="url(#live-grid)"
            stroke="#b1c3ae"
            strokeWidth=".4"
          />
          <rect
            x={-half}
            y="-150"
            width={half * 2}
            height="10"
            fill="#e9e4d780"
          />
          <rect
            x={-half}
            y="-10"
            width={half * 2}
            height="10"
            fill="#e9e4d780"
          />
          {strokes.flatMap((s) =>
            s.points_uv_mm.slice(1).map((p, i) => {
              const a = s.points_uv_mm[i],
                style = paint(s.segment_id, i);
              return (
                <line
                  key={`${s.segment_id}-${i}`}
                  x1={a[0]}
                  y1={-a[1]}
                  x2={p[0]}
                  y2={-p[1]}
                  stroke={style.color}
                  strokeWidth=".85"
                  strokeDasharray={style.dash}
                  strokeLinecap="round"
                >
                  <title>
                    {s.segment_id} · {style.label}
                  </title>
                </line>
              );
            }),
          )}
          <text x="0" y="10" textAnchor="middle" fontSize="3.5" fill="#829381">
            전개면 · U/V mm · 선을 가리켜 구간 확인
          </text>
        </svg>
        <svg
          viewBox="0 0 190 230"
          role="img"
          aria-label={
            match ? "원기둥의 동일 구간 판정" : "원기둥의 동일 경로 진행률"
          }
          onPointerDown={(e) => {
            drag.current = e.clientX;
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            if (drag.current !== null) {
              setYaw((v) => v + (e.clientX - drag.current!) * 0.015);
              drag.current = e.clientX;
            }
          }}
          onPointerUp={() => {
            drag.current = null;
          }}
          onPointerCancel={() => {
            drag.current = null;
          }}
        >
          <defs>
            <linearGradient id="live-cylinder">
              <stop stopColor="#d7dfd2" />
              <stop offset=".3" stopColor="#fafbf2" />
              <stop offset="1" stopColor="#d3ddcd" />
            </linearGradient>
          </defs>
          <path
            d={`M${cx - rad} ${top}V${bottom}A${rad} ${rad * 0.2} 0 0 0 ${cx + rad} ${bottom}V${top}Z`}
            fill="url(#live-cylinder)"
            stroke="#bcc9b5"
            strokeWidth=".6"
          />
          <ellipse
            cx={cx}
            cy={top}
            rx={rad}
            ry={rad * 0.2}
            fill="#f2f5eb"
            stroke="#bcc9b5"
            strokeWidth=".6"
          />
          {strokes.flatMap((s) =>
            s.points_m.slice(1).map((p, i) => {
              const a = project(s.points_m[i]),
                b = project(p),
                style = paint(s.segment_id, i);
              if ((a[2] + b[2]) / 2 > 0) return null;
              return (
                <line
                  key={`${s.segment_id}-${i}`}
                  x1={a[0]}
                  y1={a[1]}
                  x2={b[0]}
                  y2={b[1]}
                  stroke={style.color}
                  strokeWidth="1.1"
                  strokeDasharray={style.dash}
                  strokeLinecap="round"
                />
              );
            }),
          )}
          <text
            x={cx}
            y="222"
            textAnchor="middle"
            fontSize="6.5"
            fill="#829381"
          >
            드래그하여 관찰 방향 회전
          </text>
        </svg>
      </div>
      {failures.length > 0 && (
        <div className="path-quality-issues">
          {failures.map((o) => (
            <span key={o.segment_id}>
              <b>{o.segment_id}</b> ·{" "}
              {o.verdict === "FAILED"
                ? "모의 압력 확인 실패"
                : "구간 판정 미확인"}{" "}
              · 점 {o.start_point_index}~{o.end_point_index}
            </span>
          ))}
        </div>
      )}
      <p className="path-quality-note">
        {match
          ? "색상은 구간별 모의 판정 기록을 사용합니다. 이동 완료만으로 초록색을 표시하지 않습니다."
          : "파란색은 공정 노드가 보고한 완료 CUT 길이입니다. 가공 품질 합격은 최종 검사에서 별도로 확인합니다."}
      </p>
    </section>
  );
}
