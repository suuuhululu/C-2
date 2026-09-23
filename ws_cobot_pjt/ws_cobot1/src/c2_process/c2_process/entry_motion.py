"""사전 entry 전용 프로파일. 공통 이동·조각 프로파일에는 적용하지 않는다."""
import math


def make_entry_motion_profile(travel, entry_plan):
    """명시된 entry 위치 허용오차만 복사본에 적용한다. 실제 이동은 호출자가 수행한다."""
    overrides = entry_plan["motion_overrides"]
    if set(overrides) != {"pos_tol_mm"}:
        raise ValueError("entry는 위치 허용오차만 별도 설정 가능")
    tolerance = overrides["pos_tol_mm"]
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("entry 위치 허용오차는 양의 유한값이어야 함")
    return dict(travel, pos_tol_mm=float(tolerance))
