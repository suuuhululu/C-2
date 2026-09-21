import { useRef, useState } from "react";
import { Grid3X3, Maximize2, Minus, Plus, RotateCcw } from "lucide-react";
import type {
  Asset,
  PathResult,
  Placement,
  Profile,
  WorkAreaPolicy,
} from "./api";
import { cutStrokes, cylinderPoint, previewSegments } from "./preview";
import { mm, policyWorkArea, profileWorkArea } from "./workArea";
import WorkAreaSummary from "./WorkAreaSummary";

function transformPoint(point: number[], from: Placement, to: Placement) {
  const a = (-from.rotation_deg * Math.PI) / 180;
  const x = point[0] - from.offset_u_mm,
    y = point[1] - from.offset_v_mm;
  const lx =
    ((x * Math.cos(a) - y * Math.sin(a)) / from.width_mm) * to.width_mm;
  const ly =
    ((x * Math.sin(a) + y * Math.cos(a)) / from.height_mm) * to.height_mm;
  const b = (to.rotation_deg * Math.PI) / 180;
  return [
    lx * Math.cos(b) - ly * Math.sin(b) + to.offset_u_mm,
    lx * Math.sin(b) + ly * Math.cos(b) + to.offset_v_mm,
  ];
}

export function UnwrappedPreview({
  profile,
  workAreaPolicy,
  draft,
  result,
  asset,
  stale,
  locked,
  onChange,
}: {
  profile?: Profile;
  workAreaPolicy?: WorkAreaPolicy;
  draft: Placement;
  result: PathResult | null;
  asset: Asset | null;
  stale: boolean;
  locked: boolean;
  onChange: (p: Placement) => void;
}) {
  const [zoom, setZoom] = useState(1),
    [grid, setGrid] = useState(true),
    [original, setOriginal] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ u: number; v: number; draft: Placement } | null>(null);
  const s = profile?.payload.surface;
  const half = s ? s.radius_mm * Math.PI : 106.814;
  const height = s?.height_mm ?? 150;
  const workArea = workAreaPolicy
    ? policyWorkArea(profile, workAreaPolicy)
    : profileWorkArea(profile);
  const actual = !!s?.axis_origin_m && (s.u_origin_angle_deg || 0) === 0;
  function point(e: React.PointerEvent) {
    const matrix = svg.current?.getScreenCTM();
    if (!matrix) return [0, 0];
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(
      matrix.inverse(),
    );
    return [p.x, -p.y];
  }
  function down(e: React.PointerEvent<SVGGElement>) {
    if (locked) return;
    const [u, v] = point(e);
    drag.current = { u, v, draft: { ...draft } };
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function move(e: React.PointerEvent<SVGGElement>) {
    if (!drag.current || locked) return;
    const [u, v] = point(e),
      d = drag.current;
    onChange({
      ...d.draft,
      offset_u_mm: +Math.max(
        -250,
        Math.min(250, d.draft.offset_u_mm + u - d.u),
      ).toFixed(1),
      offset_v_mm: +Math.max(
        -100,
        Math.min(250, d.draft.offset_v_mm + v - d.v),
      ).toFixed(1),
    });
  }
  return (
    <section className="panel unwrap-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">LAYOUT / 01</span>
          <h2>원기둥 전개면</h2>
        </div>
        <span className={`tag ${stale ? "amber" : ""}`}>
          {result ? (stale ? "배치 편집 중" : "생성 결과") : "배치 준비"}
        </span>
      </div>
      <div className="preview-toolbar">
        <div className="segmented">
          <button
            className={!original ? "selected" : ""}
            onClick={() => setOriginal(false)}
          >
            전개면
          </button>
          <button
            className={original ? "selected" : ""}
            onClick={() => setOriginal(true)}
          >
            원본 비교
          </button>
        </div>
        <div className="zoom-tools">
          <button
            aria-label="축소"
            onClick={() => setZoom((z) => Math.max(0.7, z - 0.15))}
          >
            <Minus size={15} />
          </button>
          <span>{Math.round(zoom * 100)}%</span>
          <button
            aria-label="확대"
            onClick={() => setZoom((z) => Math.min(2, z + 0.15))}
          >
            <Plus size={15} />
          </button>
          <button
            title="화면 맞춤"
            aria-label="화면 맞춤"
            onClick={() => setZoom(1)}
          >
            <Maximize2 size={15} />
          </button>
          <button
            aria-label="격자 표시"
            aria-pressed={grid}
            onClick={() => setGrid(!grid)}
          >
            <Grid3X3 size={15} />
          </button>
        </div>
      </div>
      <div className="unwrap-stage">
        <svg
          ref={svg}
          viewBox={`${-(half + 28) / zoom} ${-height / 2 - (height / 2 + 23) / zoom} ${((half + 28) * 2) / zoom} ${(height + 46) / zoom}`}
          role="img"
          aria-label={
            actual
              ? "원기둥 전개면. U=0은 base +X입니다."
              : "원기둥 전개면. U 중심은 앞면 0도입니다."
          }
        >
          <defs>
            <pattern
              id="minor-grid"
              width="5"
              height="5"
              patternUnits="userSpaceOnUse"
            >
              <path
                d="M5 0H0V5"
                fill="none"
                stroke="#dfe6df"
                strokeWidth=".18"
              />
            </pattern>
            <pattern
              id="major-grid"
              width="25"
              height="25"
              patternUnits="userSpaceOnUse"
            >
              <rect width="25" height="25" fill="url(#minor-grid)" />
              <path
                d="M25 0H0V25"
                fill="none"
                stroke="#bdcabe"
                strokeWidth=".25"
              />
            </pattern>
          </defs>
          <text
            x="0"
            y={-height - 13}
            textAnchor="middle"
            className="drawing-dimension"
          >
            {(half * 2).toFixed(2)} mm <tspan fill="#8b968e"> / 펼친 폭</tspan>
          </text>
          <line
            x1={-half}
            x2={half}
            y1={-height - 7}
            y2={-height - 7}
            className="dimension-line"
          />
          <rect
            x={-half}
            y={-height}
            width={half * 2}
            height={height}
            fill={grid ? "url(#major-grid)" : "#fbfcf9"}
            stroke="#9cae9f"
            strokeWidth=".5"
          />
          <line
            x1="0"
            x2="0"
            y1={-height}
            y2="0"
            stroke="#79a391"
            strokeWidth=".35"
            strokeDasharray="2 2"
          />
          {workArea && (
            <g pointerEvents="none" aria-label="상하 조각 제외 구간">
              <rect
                x={-half}
                y={-height}
                width={half * 2}
                height={workArea.topExcluded}
                fill="#eec9ae"
                opacity=".3"
              />
              <rect
                x={-half}
                y={-workArea.bottomExcluded}
                width={half * 2}
                height={workArea.bottomExcluded}
                fill="#eec9ae"
                opacity=".3"
              />
              {workArea.bottomRange.map((v) => (
                <line
                  key={v}
                  x1={-half}
                  x2={half}
                  y1={-v}
                  y2={-v}
                  stroke="#b47b4d"
                  strokeWidth=".5"
                  strokeDasharray="2 2"
                />
              ))}
              <text x={-half + 3} y={-height + 5} className="drawing-note">
                상단 {mm(workArea.topExcluded)} mm 제외
              </text>
              <text x={-half + 3} y={-3} className="drawing-note">
                하단 {mm(workArea.bottomExcluded)} mm 제외
              </text>
            </g>
          )}
          <text
            x={-half - 7}
            y="-73"
            transform={`rotate(-90 ${-half - 7} -73)`}
            className="drawing-dimension"
            textAnchor="middle"
          >
            {height} mm / 높이
          </text>
          <text x={-half} y="8" className="drawing-note">
            −180° · 이음매
          </text>
          <text x="0" y="8" className="drawing-note" textAnchor="middle">
            {actual ? "0° · base +X · U=0" : "0° · 앞면 · U=0"}
          </text>
          <text x={half} y="8" className="drawing-note" textAnchor="end">
            +180° · 이음매
          </text>
          {asset && (
            <g
              onPointerDown={down}
              onPointerMove={move}
              onPointerUp={() => {
                drag.current = null;
              }}
              onPointerCancel={() => {
                drag.current = null;
              }}
              style={{
                cursor: locked ? "default" : "grab",
                touchAction: "none",
              }}
            >
              {(original || !result) && (
                <image
                  href={asset.url}
                  x={draft.offset_u_mm - draft.width_mm / 2}
                  y={-draft.offset_v_mm - draft.height_mm / 2}
                  width={draft.width_mm}
                  height={draft.height_mm}
                  preserveAspectRatio="none"
                  transform={`rotate(${-draft.rotation_deg} ${draft.offset_u_mm} ${-draft.offset_v_mm})`}
                  opacity={0.77}
                />
              )}
              {!original &&
                result &&
                cutStrokes(result).map((st) => (
                  <polyline
                    key={st.segment_id}
                    points={st.points_uv_mm
                      .map((p) => {
                        const q = transformPoint(p, result.input, draft);
                        return `${q[0]},${-q[1]}`;
                      })
                      .join(" ")}
                    fill="none"
                    stroke="#284a3d"
                    strokeWidth=".6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                ))}
              <g
                transform={`translate(${draft.offset_u_mm} ${-draft.offset_v_mm}) rotate(${-draft.rotation_deg})`}
              >
                <rect
                  x={-draft.width_mm / 2}
                  y={-draft.height_mm / 2}
                  width={draft.width_mm}
                  height={draft.height_mm}
                  fill="transparent"
                  stroke="#358d78"
                  strokeWidth=".5"
                  strokeDasharray={stale ? "2 1" : undefined}
                />
                {[-1, 1].flatMap((x) =>
                  [-1, 1].map((y) => (
                    <rect
                      key={`${x}${y}`}
                      x={(x * draft.width_mm) / 2 - 1.1}
                      y={(y * draft.height_mm) / 2 - 1.1}
                      width="2.2"
                      height="2.2"
                      fill="white"
                      stroke="#358d78"
                      strokeWidth=".45"
                    />
                  )),
                )}
                <path d="M-3 0H3 M0-3V3" stroke="#358d78" strokeWidth=".5" />
                <text
                  y={draft.height_mm / 2 + 6}
                  className="drawing-note"
                  fill="#358d78"
                  textAnchor="middle"
                >
                  {draft.width_mm.toFixed(1)} × {draft.height_mm.toFixed(1)} mm
                </text>
              </g>
            </g>
          )}
          {!asset && (
            <g>
              <text
                x="0"
                y="-78"
                textAnchor="middle"
                className="empty-canvas-title"
              >
                나만의 선을 올려주세요
              </text>
              <text x="0" y="-68" textAnchor="middle" className="drawing-note">
                이미지 첨부 후 크기와 위치를 정합니다.
              </text>
            </g>
          )}
        </svg>
      </div>
      <div className="preview-caption">
        <span>
          <i className="legend-line" />
          도안 <i className="legend-box" />
          선택 영역 · 옆면 360° / 높이 {height} mm
        </span>
        <span>U → · 바닥 V ↑ · mm</span>
      </div>
      <WorkAreaSummary profile={profile} policy={workAreaPolicy} />
      <div className={`preview-message ${stale ? "changed" : ""}`}>
        {result ? (
          <>
            <b>
              {stale
                ? "입력이 바뀌었습니다. 경로를 다시 생성하세요."
                : result.preview.contract === "c2-path-preview/1"
                  ? "첨부 이미지의 중심선 경로 · 기하 검증 완료 · 실기 미검증"
                  : "모의 중심선 샘플 · 첨부 이미지의 실제 변환 결과가 아닙니다."}
            </b>
            <span>
              {result.path_id.slice(0, 8)} · v{result.path_version} ·{" "}
              {result.segment_count}개 구간
            </span>
          </>
        ) : (
          <>
            <b>마우스로 도안을 이동하거나 왼쪽에서 수치를 입력하세요.</b>
            <span>
              전체 옆면을 표시합니다. 음영은 상하 조각 제외 구간이며, 도안
              배치만으로 실제 CUT의 범위 검사가 완료되지는 않습니다.
            </span>
          </>
        )}
      </div>
    </section>
  );
}

export function CylinderPreview({
  result,
  stale,
  profile: currentProfile,
}: {
  result: PathResult | null;
  stale: boolean;
  profile?: Profile;
}) {
  const [yaw, setYaw] = useState(0);
  const drag = useRef<number | null>(null);
  const profile = result?.profile_snapshot ?? currentProfile;
  const radius = (profile?.payload.surface.radius_mm || 34) / 1000,
    scale = 1460,
    cx = 180,
    cy = 153;
  const height = (profile?.payload.surface.height_mm ?? 150) / 1000;
  const rad = radius * scale,
    tilt = 0.22,
    top = cy - (height / 2) * scale,
    bottom = cy + (height / 2) * scale;
  const project = (point: number[]) => {
    const p = cylinderPoint(point, profile);
    const x = p[0] * Math.cos(yaw) - p[1] * Math.sin(yaw);
    const depth = p[0] * Math.sin(yaw) + p[1] * Math.cos(yaw);
    return [
      cx + x * scale,
      cy - (p[2] - height / 2) * scale + depth * scale * tilt,
      depth,
    ];
  };
  return (
    <section className="panel cylinder-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">SURFACE / 02</span>
          <h2>원기둥 적용 미리보기</h2>
        </div>
        <button
          className="icon-button"
          aria-label="관찰 방향 초기화"
          onClick={() => setYaw(0)}
        >
          <RotateCcw size={15} />
        </button>
      </div>
      <svg
        viewBox="0 0 360 303"
        className="cylinder-canvas"
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
        role="img"
        aria-label="드릴 끝 경로를 표시한 원기둥. 마우스로 관찰 방향을 회전합니다."
      >
        <defs>
          <linearGradient id="wax">
            <stop stopColor="#d5d9cf" />
            <stop offset=".28" stopColor="#fbfaf0" />
            <stop offset=".58" stopColor="#f1f0e6" />
            <stop offset="1" stopColor="#c8cebf" />
          </linearGradient>
          <radialGradient id="shadow">
            <stop stopColor="#6c7f6c" stopOpacity=".18" />
            <stop offset="1" stopColor="#6c7f6c" stopOpacity="0" />
          </radialGradient>
        </defs>
        <ellipse cx={cx} cy={bottom + 16} rx="84" ry="17" fill="url(#shadow)" />
        <path
          d={`M${cx - rad},${top} L${cx - rad},${bottom} A${rad},${rad * tilt} 0 0 0 ${cx + rad},${bottom} L${cx + rad},${top} Z`}
          fill="url(#wax)"
          stroke="#b4bdb0"
          strokeWidth=".8"
        />
        <ellipse
          cx={cx}
          cy={top}
          rx={rad}
          ry={rad * tilt}
          fill="#efeee3"
          stroke="#b4bdb0"
          strokeWidth=".8"
        />
        {previewSegments(result).flatMap((st) =>
          st.points_m.slice(1).map((pt, i) => {
            const a = project(st.points_m[i]),
              b = project(pt);
            if ((a[2] + b[2]) / 2 > 0) return null;
            return (
              <line
                key={`${st.segment_id}-${i}`}
                x1={a[0]}
                y1={a[1]}
                x2={b[0]}
                y2={b[1]}
                stroke={st.kind === "CUT" ? "#365849" : "#929b96"}
                strokeDasharray={st.kind === "CUT" ? undefined : "2 2"}
                strokeWidth="1.05"
                strokeLinecap="round"
              />
            );
          }),
        )}
        <text x="308" y="144" className="cylinder-label" textAnchor="middle">
          {height * 1000}
        </text>
        <text x="308" y="158" className="cylinder-label" textAnchor="middle">
          mm
        </text>
        <path
          d="M278 49v214 M274 49h8 M274 263h8"
          stroke="#b4bdb0"
          fill="none"
        />
        <text x="180" y="291" className="cylinder-label" textAnchor="middle">
          Ø {(radius * 2000).toFixed(1)} mm ·{" "}
          {profile?.payload.contract === "c2-path-test-profile/1"
            ? "시험 프로파일"
            : "모의 규격"}
        </text>
      </svg>
      <div className="cylinder-note">
        {result
          ? stale
            ? "이전 생성 결과 · 다시 생성 필요"
            : "전개면과 동일 경로 · 드릴 끝 기준"
          : "경로 생성 후 적용 모습이 표시됩니다."}
        <span>드래그하여 관찰 방향 회전 · 점선은 비절삭 이동</span>
      </div>
    </section>
  );
}
