import assert from 'node:assert/strict';
import test from 'node:test';
import { activePreparation, measurementPoints, preparationLabel } from '../src/monitor/preparation.ts';

test('점 완료는 해당 점 SUCCEEDED만 사용하고 순서가 지난 이벤트는 버린다', () => {
  const event = (sequence, stage, status, point_index=0) => ({sequence, stage, status, point_index, total_points:8});
  const points=measurementPoints([
    event(1,'SIDE_TOUCH','RUNNING',1), event(2,'SIDE_TOUCH','SUCCEEDED',1),
    event(1,'SIDE_TOUCH','RUNNING',1), event(3,'SIDE_TOUCH','RUNNING',2),
    event(4,'COMPLETE','SUCCEEDED'), event(5,'SIDE_TOUCH','SUCCEEDED',9),
  ]);
  assert.deepEqual(points,['SUCCEEDED','RUNNING',...Array(6).fill('PENDING')]);
});

test('최종 성공과 재준비·종료 미확인을 구분한다', () => {
  assert.match(preparationLabel('SUCCEEDED',false), /다시 준비/);
  assert.match(preparationLabel('SUCCEEDED',true), /SIM 준비·측정·등록 완료/);
  assert.match(preparationLabel('UNKNOWN'), /다음 작업 차단/);
});

test('ROS 완료 개수만으로 개별 접촉을 성공 처리하지 않는다', () => {
  assert.deepEqual(measurementPoints([{stage:'COMPLETE', completed_side_points:8, total_side_points:8}]), Array(8).fill('PENDING'));
});

test('상단 정지 요청은 로봇이 움직일 수 있는 준비 상태에서 활성화한다', () => {
  for (const state of ['ACCEPTED', 'RUNNING', 'CANCELING'])
    assert.equal(activePreparation(state), true);
  for (const state of [undefined, 'SUCCEEDED', 'FAILED', 'STOPPED', 'UNKNOWN'])
    assert.equal(activePreparation(state), false);
});
