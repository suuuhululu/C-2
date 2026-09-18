"""운영자 HTTP 모델. 미리보기 mock-preview/1은 팀 합의 전 교체 가능한 로컬 형식이다."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid4())


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class GenerateInput(Input):
    schema_version: Literal[1] = 1
    request_id: UUID
    source_mode: Literal['SIMULATION'] = 'SIMULATION'
    asset_id: UUID
    asset_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    width_mm: float = Field(gt=0, le=500)
    height_mm: float = Field(gt=0, le=500)
    offset_u_mm: float = Field(ge=-500, le=500)
    offset_v_mm: float = Field(ge=-500, le=500)
    rotation_deg: float = Field(ge=-180, le=180)
    conversion_preset: Literal['simulation_centerline'] = 'simulation_centerline'
    tool_id: Literal['engraving_knife'] = 'engraving_knife'
    profile_snapshot_id: UUID
    profile_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class RunInput(Input):
    schema_version: Literal[1] = 1
    request_id: UUID
    source_mode: Literal['SIMULATION'] = 'SIMULATION'
    path_id: UUID
    path_version: int = Field(ge=1)
    path_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    operator_confirmed_fixture: Literal[True]


class StopInput(Input):
    schema_version: Literal[1] = 1
    request_id: UUID
    reason: str = Field(default='운영자 정지 요청', min_length=1, max_length=300)


class InspectionInput(Input):
    run_id: UUID
    verdict: Literal['PASS', 'HOLD', 'REJECT']
    reason: str = Field(min_length=1, max_length=500)


class ScenarioInput(Input):
    scenario: Literal['normal', 'generation_failure', 'grip_failure', 'cut_quality_failure', 'stop_unknown', 'communication_loss']
