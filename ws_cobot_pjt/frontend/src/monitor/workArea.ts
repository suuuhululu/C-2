import type { Profile, WorkAreaPolicy } from "./api";

export type WorkArea = {
  height: number;
  bottomRange: [number, number];
  topRange: [number, number];
  bottomExcluded: number;
  topExcluded: number;
  usableHeight: number;
};

// v: 윗면에서 아래(+), V: 바닥에서 위(+). 경로 좌표를 변경하지 않는다.
export function topToBottom(height: number, v: number) {
  return height - v;
}

function area(
  height: number | undefined,
  low: number,
  high: number,
): WorkArea | null {
  if (
    typeof height !== "number" ||
    ![height, low, high].every(Number.isFinite) ||
    height <= 0 ||
    low < 0 ||
    low >= high ||
    high > height
  )
    return null;
  return {
    height,
    bottomRange: [low, high],
    topRange: [topToBottom(height, high), topToBottom(height, low)],
    bottomExcluded: low,
    topExcluded: height - high,
    usableHeight: high - low,
  };
}

export function profileWorkArea(profile?: Profile): WorkArea | null {
  const s = profile?.payload.surface;
  if (!Array.isArray(s?.valid_v_range_mm) || s.valid_v_range_mm.length !== 2)
    return null;
  return area(s.height_mm, s.valid_v_range_mm[0], s.valid_v_range_mm[1]);
}

export function policyWorkArea(
  profile?: Profile,
  policy?: WorkAreaPolicy,
): WorkArea | null {
  const height = profile?.payload.surface.height_mm;
  const p = policy?.payload;
  if (
    !p ||
    p.contract !== "hmi-work-area-policy/1" ||
    typeof height !== "number" ||
    ![p.top_exclusion_mm, p.bottom_exclusion_mm].every(Number.isFinite) ||
    p.top_exclusion_mm < 0 ||
    p.bottom_exclusion_mm < 0
  )
    return null;
  return area(
    height,
    p.bottom_exclusion_mm,
    topToBottom(height, p.top_exclusion_mm),
  );
}

export function sameWorkArea(a: WorkArea | null, b: WorkArea | null) {
  return (
    !!a &&
    !!b &&
    Math.abs(a.height - b.height) < 1e-6 &&
    a.bottomRange.every((v, i) => Math.abs(v - b.bottomRange[i]) < 1e-6)
  );
}

export function mm(value: number) {
  return String(+value.toFixed(2));
}
export function rangeText(range: [number, number]) {
  return range.map(mm).join(" ~ ");
}
