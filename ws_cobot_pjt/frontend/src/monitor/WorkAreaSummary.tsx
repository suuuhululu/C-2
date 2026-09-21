import type { Profile, WorkAreaPolicy } from "./api";
import {
  mm,
  policyWorkArea,
  profileWorkArea,
  rangeText,
  sameWorkArea,
} from "./workArea";

export default function WorkAreaSummary({
  profile,
  policy,
}: {
  profile?: Profile;
  policy?: WorkAreaPolicy;
}) {
  const current = profileWorkArea(profile);
  const target = policyWorkArea(profile, policy);
  const shown = policy ? target : current;
  return (
    <div className="work-area-summary">
      <strong>{policy ? "합의 작업 영역" : "경로 스냅샷 작업 영역"}</strong>
      {shown ? (
        <>
          <span>
            상단 {mm(shown.topExcluded)} mm · 하단 {mm(shown.bottomExcluded)} mm
            조각 제외
          </span>
          <span>바닥 기준 V ↑ {rangeText(shown.bottomRange)} mm</span>
          <span>
            윗면 기준 v ↓ {rangeText(shown.topRange)} mm · 작업 높이{" "}
            {mm(shown.usableHeight)} mm
          </span>
        </>
      ) : (
        <span>작업 영역 미확인 · 높이와 범위 설정을 확인하세요.</span>
      )}
      {policy && !sameWorkArea(target, current) && (
        <p className="work-area-warning" role="status">
          {current
            ? `현재 경로 프로파일: 바닥 V=${rangeText(current.bottomRange)} mm. 합의 기준 반영 대기입니다.`
            : "현재 경로 프로파일의 작업 영역을 확인할 수 없습니다."}{" "}
          표시한 기준은 좌표 노드의 계산 제한을 바꾸지 않습니다.
        </p>
      )}
      <small>
        작업 영역은 로봇 도달 가능 판정이 아닙니다. 윗면 Z·실측 유효성은 별도
        확인합니다.
      </small>
    </div>
  );
}
