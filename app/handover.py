"""전달 개발 0단계 기능 목록. 설치된 드라이버를 실행하거나 자동 연결하지 않는다."""


def handover_capabilities(mode: str) -> dict:
    if mode not in ("FAKE", "REPLAY", "REAL"):
        raise ValueError("handover.mode: explicit FAKE, REPLAY or REAL required")
    simulated = mode == "FAKE"
    return dict(mode=mode, real_output_enabled=False,
        request_stop="available_fake" if simulated else "unavailable",
        confirm_stop="available_fake" if simulated else "unavailable",
        approach="unavailable", release="unavailable", confirm_release="unavailable",
        confirm_receipt="unavailable", read_force="unavailable",
        reason=None if simulated else "REPLAY_ADAPTER_PENDING" if mode == "REPLAY"
               else "REAL_HANDOVER_NOT_VALIDATED")
