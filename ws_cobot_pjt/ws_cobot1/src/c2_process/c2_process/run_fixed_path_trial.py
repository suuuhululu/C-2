"""호환용 얇은 wrapper. 실제 구현은 engraving.execute_fixed_depth_path 로 옮겼다.

fixed_depth 는 조각 실행의 한 갈래이므로 본체는 engraving.py 가 소유한다.
이 모듈은 기존 import 경로(FIXED_PATH_EXECUTION.md, 기존 시험 코드)만 유지한다.
새 코드는 engraving.execute_fixed_depth_path 를 직접 쓴다.
"""
from .engraving import execute_fixed_depth_path as execute_path

__all__ = ['execute_path']
