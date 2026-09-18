# clay_carving/scripts — 9/18 양초 실기용 보조 스크립트

패키지 진입점이 아니라 `python3 <파일>` 로 직접 실행한다 (ws_dsr·ws_cobot1 source 후, 브링업 켜진 상태). 전부 `GripperDA_v3` 선택·그리퍼 수직 자세를 전제로 하고, 좌표 상수(`CX, CY, ZTOP, R`)는 [docs/evidence/workcell_candle_0918.yaml](../../../../docs/evidence/workcell_candle_0918.yaml) 값이다. 양초를 옮기면 상수를 바꿔야 한다.

| 파일 | 하는 일 | 실기 |
|---|---|---|
| `fk.py <j1..j6 deg>` | URDF 정운동학으로 플랜지·v1·v3 위치와 A,B,C 출력. 서비스가 죽었을 때 `joint_states` 로 자세 읽기 | 홈 자세로 검증 (1.5 mm) |
| `goto_home2.py [--dry]` | 지금 자세 → 직선 상승 → 안전 높이 수평 이동 → 새 홈(축 위 30 mm, 수직) | 9/18 2회 정상 |
| `side_heart.py <open|close|turn|measure|draw|home> [--tag t] [--depth mm] [--width mm]` | 옆면 3점 터치로 도구 끝 원 맞춤(`measure`) → 곡률 따라 하트(`draw`). `turn` 은 수직축 180° 회전(반대 면) | 송곳·드릴 하트 각 1회 성공 |
| `orbit_wave.py <unwind|touch|wave|all>` | 도구가 축을 향하게 돌며 4각 터치 → 원 맞춤 → 360° 물결. J6 범위 검사·`unwind` 포함 | **9/18 실패(J6 감김·거짓 접촉) 후 수정, 미검증** |

시행착오와 대응은 [docs/LESSONS_ROBOT.md](../../../../docs/LESSONS_ROBOT.md).
