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
