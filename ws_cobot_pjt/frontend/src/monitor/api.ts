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
    label?: string;
    contract: string;
    tool_id: string;
    tool_label?: string;
    tcp_id: string;
    tcp_reference?: string;
    note?: string;
    frame_id: string;
    surface: {
      radius_mm: number;
      height_mm: number;
      u_range_mm?: number[];
      v_range_mm?: number[];
      valid_v_range_mm: number[];
      axis_origin_m?: number[];
      axis_direction?: number[];
      u_origin_angle_deg?: number;
      reachable_angle_deg?: number[];
    };
  };
};
export type WorkAreaPolicy = {
  id: string;
  sha256: string;
  payload: {
    contract: "hmi-work-area-policy/1";
    revision: string;
    top_exclusion_mm: number;
    bottom_exclusion_mm: number;
  };
};
export type Stroke = {
  stroke_id: string | null;
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
  test_only?: boolean;
  real_execution_allowed?: boolean;
  execution_precheck?: string;
  execution_blocked?: string | null;
  validation_not_checked?: string[];
  profile_snapshot?: Profile;
  preview: {
    contract: string;
    note?: string;
    strokes?: Stroke[];
    segments?: (Omit<Stroke, "points_uv_mm"> & { points_uv_mm?: number[][] })[];
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
  virtual_device?: boolean;
  source_mode: string;
  transport: string;
  connection: string;
  server_time: string;
  profile: Profile;
  preparation: PreparationState;
  work_area_policy?: WorkAreaPolicy;
  active_run: Run | null;
  execution_pending?: boolean;
  generation: Generation | null;
  storage_error: string | null;
  scenario: string | null;
  contract_status: string;
  path_generation: {
    preset: string;
    preview_contract: string;
    ready: boolean;
    execution_enabled: boolean;
    test_only_execution?: boolean;
    execution_block_reason: string;
    default_placement: Placement;
  };
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
    published_at?: string | null;
    joints?: (number | null)[] | null;
    joints_quality?: string;
    joints_measured_at?: string | null;
    tcp?: {
      header: { frame_id: string; stamp: string | null };
      pose: {
        position: { x: number; y: number; z: number };
        orientation: { x: number; y: number; z: number; w: number };
      };
    } | null;
    tcp_quality?: string;
    tcp_profile_id?: string;
    robot_connection_state?: string;
    robot_mode?: string;
    robot_quality?: string;
    robot_measured_at?: string | null;
    grip_quality?: string;
    grip_measured_at?: string | null;
    stop_state?: string;
  } | null;
};

export type PreparationFeedback = {
  preparation_id: string;
  measurement_id: string;
  sequence?: number;
  stage: string;
  status?: string;
  point_index?: number;
  total_points?: number;
  completed_side_points?: number;
  total_side_points?: number;
  message: string;
  measured_at?: string;
};
export type PreparationRecord = {
  request_id: string;
  state: string;
  stage: string;
  created_at: string;
  binding_status: string;
  message?: string;
  error_code?: string;
  payload?: { operator_confirmed_fixed_cell?: true };
  hardware_snapshot?: { id: string; sha256: string };
  goal: {
    preparation_id: string;
    measurement_id: string;
    source_mode?: string;
  };
  feedback: PreparationFeedback[];
  measurement_record?: { id: string; sha256: string };
  profile_snapshot?: Profile;
  result: {
    outcome: string;
    error_code: string;
    message: string;
    observed_state: {
      partial: boolean;
      stop_confirmed: boolean | null;
      measurement: {
        contact_indices?: number[];
        geometry_ready: boolean;
        validity: string;
        axis_xy_m: number[] | null;
        radius_m: number | null;
        top_z_m: number | null;
        bottom_z_m: number | null;
        height_m: number;
        measured_at: string | null;
      } | null;
    };
  } | null;
};
export type PreparationState = {
  supported: boolean;
  transport: string;
  reason: string;
  ready: boolean;
  preview_ready?: boolean;
  blocks_work: boolean;
  start_error?: string | null;
  hardware_inspection?: {
    id: string;
    sha256: string;
    payload: {
      state: "READY" | "NOT_READY" | "UNAVAILABLE";
      observed_at: string;
      errors: string[];
      observation: {
        robot_state: number;
        robot_mode: number;
        robot_system: number;
        motion_status: number;
        tcp_id: string;
        load_id: string;
        joints_deg: number[];
        controller_tcp_posx: number[];
      } | null;
    };
  } | null;
  input_config: {
    id: string;
    sha256: string;
    payload: {
      source_mode?: string;
      workcell: { height_m: number; height_source: string };
    };
  } | null;
  current: PreparationRecord | null;
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
    svg_asset_id?: string;
    validation_report_id?: string;
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

export async function request<T>(
  url: string,
  body?: unknown,
  timeoutMs = 7000,
): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
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
  CONVERTING: "중심선 SVG 변환",
  EXTRACTING_2D: "2D 경로 추출",
  OPTIMIZING_2D: "획 순서 정리",
  MAPPING_3D: "표면 배치",
  BUILDING_PATH: "3D 경로 생성",
  VALIDATING: "경로 기하 검사",
};
export const active = (run?: Run | null) =>
  !!run && ["ACCEPTED", "RUNNING", "STOPPING", "UNKNOWN"].includes(run.status);
