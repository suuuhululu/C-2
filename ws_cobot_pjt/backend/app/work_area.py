"""HMI 작업 영역 합의본. 좌표 노드의 입력 스냅샷을 덮어쓰지 않는다."""
import json
import math
from copy import deepcopy
from pathlib import Path

from .storage import digest, encoded


def load_policy():
    value = json.loads((Path(__file__).resolve().parents[1] / 'config/work_area.json').read_text())
    if value.get('contract') != 'hmi-work-area-policy/1':
        raise ValueError('지원하지 않는 HMI 작업 영역 기준입니다.')
    for key in ('top_exclusion_mm', 'bottom_exclusion_mm'):
        n = value.get(key)
        if type(n) not in (int, float) or not math.isfinite(n) or n < 0:
            raise ValueError(f'{key}는 0 이상의 유한한 수여야 합니다.')
    return value


def register_policy(store):
    """동일 설정은 같은 ID, 변경된 설정은 새 관리 자산으로 보존한다."""
    policy = load_policy()
    sha = digest(encoded(policy))
    with store.db() as db:
        row = db.execute("SELECT id FROM assets WHERE kind='hmi_work_area_policy' AND sha256=?",
                         (sha,)).fetchone()
    aid = row['id'] if row else store.put_json(policy, 'hmi_work_area_policy', 'work-area-policy.json')['id']
    store.read_asset(aid, sha)
    return dict(id=aid, sha256=sha, payload=policy)


def mock_profile_with_policy(profile, policy):
    """모의 형상에만 적용. ROS 프로파일은 경로 노드 제공본을 그대로 사용한다."""
    result = deepcopy(profile)
    height = result['surface']['height_mm']
    low = policy['bottom_exclusion_mm']
    high = height - policy['top_exclusion_mm']
    if not 0 <= low < high <= height:
        raise ValueError('제외 구간이 양초 높이를 벗어납니다.')
    result['surface']['valid_v_range_mm'] = [low, high]
    result['note'] = '모의 형상에 합의 작업 영역을 적용했습니다. 실측·실기 도달 가능 판정이 아닙니다.'
    return result
