"""ROS 2 Jazzy /c2/generate_path Action 서버.

이 노드는 좌표 파일만 생성하며 로봇·그리퍼·두산 API를 호출하지 않는다.
"""
from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict

import rclpy
from c2_interfaces.action import GeneratePath
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor, ExternalShutdownException
from rclpy.node import Node

from .artifacts import ArtifactError, ManagedArtifactStore
from .pipeline import GenerationCanceled, PipelineError, success_message
from .worker import run_generation


def goal_values(request):
    return {
        "schema_version": request.schema_version,
        "request_id": request.request_id,
        "source_mode": request.source_mode,
        "asset_id": request.asset_id,
        "asset_sha256": request.asset_sha256,
        "width_mm": request.width_mm,
        "height_mm": request.height_mm,
        "offset_u_mm": request.offset_u_mm,
        "offset_v_mm": request.offset_v_mm,
        "rotation_deg": request.rotation_deg,
        "conversion_preset": request.conversion_preset,
        "tool_id": request.tool_id,
        "profile_snapshot_id": request.profile_snapshot_id,
        "profile_sha256": request.profile_sha256,
    }


def failed_result(code, message, *, svg_asset_id="", validation_report_id=""):
    result = GeneratePath.Result()
    result.success = False
    result.error_code = code
    result.message = message
    result.path_id = ""
    result.path_version = 0
    result.path_sha256 = ""
    result.svg_asset_id = svg_asset_id
    result.preview_asset_id = ""
    result.segment_count = 0
    result.cut_length_m = 0.0
    result.validation_passed = False
    result.validation_report_id = validation_report_id
    return result


class PathPlannerNode(Node):
    def __init__(self):
        super().__init__("path_planner_node")
        self.declare_parameter("managed_data_dir", os.environ.get("C2_MONITOR_DATA", ""))
        self.declare_parameter("source_mode", "SIMULATION")
        # 기본 false. true 로 명시했을 때만 REAL 요청을 받고, 그 경우도 스냅샷 /3(추정값·미리보기 전용)과 함께일 때만
        # 계산한다. 결과 경로는 test_only 라 어떤 경우에도 실행할 수 없다.
        self.declare_parameter("allow_real_preview", False)
        self.declare_parameter("generation_timeout_s", 120.0)
        self.declare_parameter("max_asset_bytes", 10 * 1024 * 1024)
        self.declare_parameter("action_name", "/c2/generate_path")
        self._state_lock = threading.Lock()
        self._active_request_id = None
        self._completed = OrderedDict()
        self._store = None
        self._store_error = ""
        self._initialize_store()
        self._group = ReentrantCallbackGroup()
        self._server = ActionServer(
            self,
            GeneratePath,
            self.get_parameter("action_name").value,
            execute_callback=self._execute,
            goal_callback=self._goal,
            cancel_callback=self._cancel,
            callback_group=self._group,
        )
        if self.get_parameter("allow_real_preview").value:
            self.get_logger().warning("/c2/generate_path 준비 완료(SIMULATION + REAL 추정값 미리보기 전용, test_only, 로봇 비구동)")
        else:
            self.get_logger().info("/c2/generate_path 준비 완료(SIMULATION/test_only, 로봇 비구동)")

    def _initialize_store(self):
        if self.get_parameter("source_mode").value != "SIMULATION":
            self._store_error = "현재 path_planner_node는 SIMULATION/test_only만 지원합니다."
            self.get_logger().error(self._store_error)
            return
        try:
            self._store = ManagedArtifactStore(
                self.get_parameter("managed_data_dir").value,
                self.get_parameter("max_asset_bytes").value,
            )
        except ArtifactError as exc:
            self._store_error = str(exc)
            self.get_logger().warning(f"관리 저장소 대기: {exc}")

    def _goal(self, _goal_request):
        # 잘못된 입력도 Result.error_code로 설명하기 위해 Goal 자체는 받아 execute에서 검증한다.
        return GoalResponse.ACCEPT

    def _cancel(self, _goal_handle):
        return CancelResponse.ACCEPT

    @staticmethod
    def _fingerprint(values):
        return json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def _remember(self, request_id, fingerprint, result):
        self._completed[request_id] = (fingerprint, result)
        self._completed.move_to_end(request_id)
        while len(self._completed) > 100:
            self._completed.popitem(last=False)

    def _feedback(self, goal_handle, request_id, stage, progress):
        message = GeneratePath.Feedback()
        message.request_id = request_id
        message.stage = stage
        message.progress = float(max(0.0, min(1.0, progress)))
        goal_handle.publish_feedback(message)

    def _execute(self, goal_handle):
        values = goal_values(goal_handle.request)
        try:
            fingerprint = self._fingerprint(values)
        except (TypeError, ValueError):
            result = failed_result("INVALID_INPUT", "요청에 직렬화할 수 없는 값이 있습니다.")
            goal_handle.abort()
            return result

        request_id = str(values.get("request_id", ""))
        with self._state_lock:
            cached = self._completed.get(request_id)
            if cached is not None:
                old_fingerprint, old_result = cached
                if old_fingerprint != fingerprint:
                    result = failed_result("REQUEST_CONFLICT", "같은 request_id에 다른 입력이 있습니다.")
                    goal_handle.abort()
                    return result
                if old_result.success:
                    goal_handle.succeed()
                else:
                    goal_handle.abort()
                return old_result
            if self._active_request_id is not None:
                result = failed_result("BUSY", "다른 경로 생성 요청이 진행 중입니다.")
                goal_handle.abort()
                return result
            self._active_request_id = request_id

        try:
            if self._store is None:
                result = failed_result("NOT_READY", self._store_error or "관리 저장소가 준비되지 않았습니다.")
                goal_handle.abort()
                return result
            generated = run_generation(
                self._store, values,
                timeout_s=self.get_parameter("generation_timeout_s").value,
                feedback=lambda stage, progress: self._feedback(
                    goal_handle, request_id, stage, progress
                ),
                canceled=lambda: goal_handle.is_cancel_requested or not rclpy.ok(),
                allow_real_preview=bool(self.get_parameter("allow_real_preview").value),
            )
            result = GeneratePath.Result()
            result.success = True
            result.error_code = "NONE"
            result.message = success_message(generated)
            result.path_id = generated.path_id
            result.path_version = generated.path_version
            result.path_sha256 = generated.path_sha256
            result.svg_asset_id = generated.svg_asset_id
            result.preview_asset_id = generated.preview_asset_id
            result.segment_count = generated.segment_count
            result.cut_length_m = generated.cut_length_m
            result.validation_passed = True
            result.validation_report_id = generated.validation_report_id
            goal_handle.succeed()
        except GenerationCanceled as exc:
            result = failed_result(exc.code, exc.message)
            goal_handle.canceled()
        except PipelineError as exc:
            result = failed_result(
                exc.code,
                exc.message,
                svg_asset_id=exc.svg_asset_id,
                validation_report_id=exc.validation_report_id,
            )
            goal_handle.abort()
        except ArtifactError as exc:
            result = failed_result("STORAGE_ERROR", f"관리 파일 저장 실패: {exc}")
            goal_handle.abort()
        except Exception as exc:  # 예외를 성공이나 빈 경로로 바꾸지 않는다.
            self.get_logger().error(f"경로 생성 내부 오류: {type(exc).__name__}: {exc}")
            result = failed_result("UNKNOWN", "경로 생성 내부 오류가 발생했습니다.")
            goal_handle.abort()
        finally:
            with self._state_lock:
                if "result" in locals():
                    self._remember(request_id, fingerprint, result)
                self._active_request_id = None
        return result

    def destroy_node(self):
        self._server.destroy()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PathPlannerNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
