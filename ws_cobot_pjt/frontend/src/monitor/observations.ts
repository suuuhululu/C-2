// 화면 표시용 2초 상한. 제어 노드의 더 엄격한 품질 판정을 완화하지 않는다.
export function observationQuality(
  quality: string | undefined,
  stamp: string | null | undefined,
  connected: boolean,
  nowMs: number,
  maxAgeMs = 2000,
) {
  if (!connected) return "UNKNOWN";
  if (quality !== "VALID")
    return ["STALE", "UNSUPPORTED"].includes(quality || "")
      ? quality!
      : "UNKNOWN";
  const time = stamp ? Date.parse(stamp) : NaN;
  if (!Number.isFinite(time) || time > nowMs) return "UNKNOWN";
  return nowMs - time <= maxAgeMs ? "VALID" : "STALE";
}

export const qualityLabels: Record<string, string> = {
  VALID: "최신 관측",
  STALE: "오래된 관측",
  UNKNOWN: "미확인",
  UNSUPPORTED: "미지원",
};

export function measuredVector(
  values: unknown,
  count: number,
  quality: string,
) {
  return quality === "VALID" &&
    Array.isArray(values) &&
    values.length === count &&
    values.every((v) => typeof v === "number" && Number.isFinite(v))
    ? values.map((v) => v.toFixed(4)).join(" / ")
    : "미확인";
}
