import assert from 'node:assert/strict';
import test from 'node:test';
import { policyWorkArea, profileWorkArea, sameWorkArea, topToBottom } from '../src/monitor/workArea.ts';

const profile = (height = 150, range = [10, 140]) => ({ payload: { surface: { height_mm: height, valid_v_range_mm: range } } });
const policy = (top = 10, bottom = 10) => ({ payload: { contract: 'hmi-work-area-policy/1', top_exclusion_mm: top, bottom_exclusion_mm: bottom } });

test('상하 10mm 제외 기준은 높이 스냅샷에서 계산하고 원본을 바꾸지 않는다', () => {
  const p = profile();
  const original = JSON.stringify(p);
  const area = policyWorkArea(p, policy());
  assert.deepEqual(area.bottomRange, [10, 140]);
  assert.deepEqual(area.topRange, [10, 140]);
  assert.equal(area.usableHeight, 130);
  assert.equal(sameWorkArea(area, profileWorkArea(p)), true);
  assert.deepEqual(policyWorkArea(profile(200, [10, 190]), policy()).bottomRange, [10, 190]);
  assert.equal(JSON.stringify(p), original);
});

test('비대칭 구간으로 v 아래방향과 V 위방향을 뒤집어 검증한다', () => {
  const area = policyWorkArea(profile(), policy(10, 20));
  assert.deepEqual(area.topRange, [10, 130]);
  assert.deepEqual(area.bottomRange, [20, 140]);
  assert.equal(topToBottom(150, 30), 120);
  assert.equal(topToBottom(150, topToBottom(150, 30)), 30);
});

test('현재 ROS 85~130mm를 새 합의본으로 오인하지 않는다', () => {
  const p = profile(150, [84.99999999999999, 130]);
  assert.equal(sameWorkArea(profileWorkArea(p), policyWorkArea(p, policy())), false);
  assert.equal(sameWorkArea(profileWorkArea(profile(150, [10, 140 + 1e-8])), policyWorkArea(p, policy())), true);
  assert.equal(policyWorkArea(p, undefined), null);
  assert.equal(profileWorkArea(undefined), null);
});

test('잘못된 높이·범위는 미확인으로 반환하며 임의 기본 범위를 채우지 않는다', () => {
  for (const p of [profile(0), profile(NaN), profile(150, [140, 10]), profile(150, [-1, 140]), profile(150, [10, 160]), profile(150, [10])]) {
    assert.equal(profileWorkArea(p), null);
  }
  assert.equal(policyWorkArea(profile(), policy(150, 10)), null);
  assert.equal(policyWorkArea(profile(), policy(-10, 10)), null);
});
