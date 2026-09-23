import assert from 'node:assert/strict';
import test from 'node:test';
import { phaseNames, preparedPhaseOrder } from '../src/monitor/api.ts';

test('prepared 공정 순서와 HMI 표시를 같은 phase 문자열로 유지한다', () => {
  assert.deepEqual(preparedPhaseOrder, [
    'PRECHECK', 'ENTRY', 'ENGRAVE', 'RETURN_HOME', 'FINISH',
  ]);
  assert.equal(phaseNames.ENTRY, '조각 경로 진입');
  assert.equal(phaseNames.RETURN_HOME, 'HOME 복귀');
});

test('과거 실행 기록의 phase 이름은 계속 표시한다', () => {
  assert.equal(phaseNames.TOOL_CHECK, '드릴 보정 확인');
  assert.equal(phaseNames.APPROACH, '표면 접근');
  assert.equal(phaseNames.RETRACT, '표면 이탈');
});
