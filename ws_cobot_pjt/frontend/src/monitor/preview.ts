import type { PathResult, Profile, Stroke } from "./api";

// 원본 preview와 실행용 path를 바꾸지 않고 표시할 구간만 선택한다.
export function previewSegments(path: PathResult | null) {
  if (!path) return [];
  if (path.preview.contract === "c2-path-preview/1")
    return path.preview.segments || [];
  if (path.preview.contract === "mock-preview/1")
    return path.preview.strokes || [];
  return [];
}

export function cutStrokes(path: PathResult | null): Stroke[] {
  return previewSegments(path).filter(
    (s): s is Stroke => s.kind === "CUT" && Array.isArray(s.points_uv_mm),
  );
}

export function matchesPreview(path: PathResult, contract: string) {
  const p = path.preview;
  return (
    p.contract === contract &&
    p.path_id === path.path_id &&
    p.path_version === path.path_version &&
    p.path_sha256 === path.path_sha256 &&
    previewSegments(path).length > 0 &&
    cutStrokes(path).length > 0
  );
}

export type PathProgressState =
  | "PENDING"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "UNKNOWN";

type ProgressStroke = Pick<Stroke, "segment_id" | "points_m">;

const length3 = (a: number[], b: number[]) =>
  Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);

// ExecuteProcess 피드백의 완료 CUT 길이 비율을 화면 선분에만 대응시킨다.
// COMPLETED는 모션 진행 표시이며 가공 품질 합격(PASSED)을 뜻하지 않는다.
export function pathProgressStates(
  strokes: ProgressStroke[],
  progress: number,
  phase: string,
  status: string,
  fresh: boolean,
) {
  const lines = strokes.flatMap((stroke) =>
    stroke.points_m.slice(1).map((point, index) => ({
      key: `${stroke.segment_id}:${index}`,
      length: length3(stroke.points_m[index], point),
    })),
  );
  const measuredTotal = lines.reduce(
    (sum, line) => sum + (Number.isFinite(line.length) ? line.length : 0),
    0,
  );
  const useMeasuredLength = measuredTotal > 0;
  const total = useMeasuredLength ? measuredTotal : lines.length;
  const ratio = Number.isFinite(progress)
    ? Math.max(0, Math.min(1, progress))
    : 0;
  const completed = total * ratio;
  const uncertain = !fresh || status === "UNKNOWN";
  const result: Record<string, PathProgressState> = {};
  let cursor = 0;
  for (const line of lines) {
    const length = useMeasuredLength ? Math.max(0, line.length) : 1;
    const end = cursor + length;
    if (end <= completed + Number.EPSILON) result[line.key] = "COMPLETED";
    else if (uncertain) result[line.key] = "UNKNOWN";
    else if (
      phase === "ENGRAVE" &&
      status === "RUNNING" &&
      cursor < completed &&
      completed < end
    )
      result[line.key] = "IN_PROGRESS";
    else result[line.key] = "PENDING";
    cursor = end;
  }
  return result;
}

// c2_base 절대 좌표를 관찰용 원점으로 옮겨 u=0을 화면 앞쪽에 표시한다.
// 로봇 TCP 변환이나 경로 파일 변경과는 별개다.
export function cylinderPoint(point: number[], profile?: Profile) {
  const s = profile?.payload.surface;
  if (!s?.axis_origin_m) return point; // mock-preview/1의 기존 좌표
  const [ox, oy, oz] = s.axis_origin_m;
  const x = point[0] - ox,
    y = point[1] - oy;
  const a = ((s.u_origin_angle_deg || 0) * Math.PI) / 180;
  return [
    -x * Math.sin(a) + y * Math.cos(a),
    -x * Math.cos(a) - y * Math.sin(a),
    point[2] - oz,
  ];
}
