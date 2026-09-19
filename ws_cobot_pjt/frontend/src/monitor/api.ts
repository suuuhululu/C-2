export const SCHEMA_VERSION = 2;

export type Placement = {
  width_mm: number;
  height_mm: number;
  offset_u_mm: number;
  offset_v_mm: number;
  rotation_deg: number;
};
export type Asset = {
  asset_id: string;
  asset_sha256: string;
  name: string;
  url: string;
  metadata: { width: number; height: number };
};
export type Profile = {
  id: string;
  sha256: string;
  payload: {
    label: string;
    tool_id: string;
    tool_label: string;
    tcp_id: string;
    tcp_reference: string;
    note: string;
    frame_id: string;
    surface: {
      radius_mm: number;
      height_mm: number;
      u_range_mm: number[];
      v_range_mm: number[];
      valid_v_range_mm: number[];
    };
  };
};
export type Stroke = {
  stroke_id: string;
  segment_id: string;
  kind: string;
  points_uv_mm: number[][];
  points_m: number[][];
  connect_to_next: boolean;
};
export type PathResult = {
  path_id: string;
  path_version: number;
  path_sha256: string;
  svg_url: string;
  path_url: string;
  validation_url: string;
  validation_passed: boolean;
  segment_count: number;
  cut_length_m: number;
  input: Placement & { asset_id: string };
  preview: {
    contract: string;
    note: string;
    strokes: Stroke[];
    profile_snapshot_id: string;
    path_id: string;
    path_version: number;
    path_sha256: string;
  };
};
export type Event = {
  event_id: string;
  occurred_at: string;
  event_type: string;
  severity: string;
  code: string;
  message: string;
  phase: string;
};
export type Run = {
  run_id: string;
  request_id: string;
  path_id: string;
  path_version: number;
  path_sha256: string;
  status: string;
  phase: string;
  stop_state: string;
  engraving_progress: number;
  elapsed_s: number;
  message: string;
  error_code: string;
  created_at: string;
  execution_preview?: {
    contract: string;
    run_id: string;
    path_id: string;
    path_version: number;
    path_sha256: string;
    observations: SegmentObservation[];
  };
  inspections?: {
    id: string;
    verdict: string;
    reason: string;
    created_at: string;
  }[];
};
export type SegmentObservation = {
  segment_id: string;
  stroke_id: string;
  start_point_index: number;
  end_point_index: number;
  verdict: "PENDING" | "IN_PROGRESS" | "PASSED" | "FAILED" | "UNKNOWN";
  motion_status: string;
  reason: string;
  observed_at: string;
  quality_source: string;
  pressure_n: number | null;
};
export type Snapshot = {
  source_mode: string;
  transport: string;
  connection: string;
  server_time: string;
  profile: Profile;
  active_run: Run | null;
  storage_error: string | null;
  scenario: string;
  contract_status: string;
  events: Event[];
  state: {
    status: string;
    phase: string;
    mounted_tool_id: string;
    tool_confirmation_source: string;
    grip_state: string;
    source_epoch: string;
    seq: number;
    error_code: string;
    message: string;
  } | null;
};
export type Generation = {
  request_id: string;
  state: string;
  stage: string;
  progress: number;
  result: {
    success: boolean;
    path_id: string;
    path_version: number;
    message: string;
    error_code: string;
    diagnostic_asset_id?: string;
  } | null;
};

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function request<T>(url: string, body?: unknown): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 7000);
  try {
    const form = body instanceof FormData;
    const response = await fetch("/api/operator" + url, {
      method: body === undefined ? "GET" : "POST",
      headers:
        body === undefined
          ? {}
          : {
              "x-c2-monitor": "1",
              ...(form ? {} : { "Content-Type": "application/json" }),
            },
      body: body === undefined ? undefined : form ? body : JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      const message =
        typeof detail.detail === "string" ? detail.detail : detail.message;
      throw new ApiError(
        message || `입력을 확인해 주세요 (${response.status})`,
        response.status,
      );
    }
    return await response.json();
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw new Error("응답 미확인. 다시 요청하면 같은 요청 ID로 조회합니다.");
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export const initialPlacement: Placement = {
  width_mm: 70,
  height_mm: 108,
  offset_u_mm: 0,
  offset_v_mm: 75,
  rotation_deg: 0,
};
export const phaseNames: Record<string, string> = {
  PRECHECK: "준비 검사",
  TOOL_CHECK: "드릴 보정 확인",
  APPROACH: "표면 접근",
  ENGRAVE: "조각",
  RETRACT: "표면 이탈",
  FINISH: "공정 완료",
};
export const statusNames: Record<string, string> = {
  IDLE: "대기",
  ACCEPTED: "접수",
  RUNNING: "진행 중",
  STOPPING: "정지 처리",
  STOPPED: "정지 확인",
  SUCCEEDED: "공정 완료",
  FAILED: "실패",
  UNKNOWN: "미확인",
};
export const stageNames: Record<string, string> = {
  CONVERTING: "SVG 샘플 준비",
  EXTRACTING_2D: "2D 선 준비",
  OPTIMIZING_2D: "샘플 정리",
  MAPPING_3D: "표면 배치",
  BUILDING_PATH: "경로 샘플 생성",
  VALIDATING: "모의 범위 검사",
};
export const active = (run?: Run | null) =>
  !!run && ["ACCEPTED", "RUNNING", "STOPPING", "UNKNOWN"].includes(run.status);
