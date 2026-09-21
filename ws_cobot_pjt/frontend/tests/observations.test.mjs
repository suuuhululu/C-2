import assert from 'node:assert/strict';
import test from 'node:test';
import { observationQuality, measuredVector } from '../src/monitor/observations.ts';
import { executionConfirmationKey, preparationStages } from '../src/monitor/preparation.ts';

test('heartbeat가 계속 와도 실제 관측 시각이 오래되면 사용하지 않는다', () => {
  const now=Date.parse('2026-09-21T07:00:05Z');
  const old='2026-09-21T07:00:00Z', fresh='2026-09-21T07:00:04Z';
  assert.equal(observationQuality('VALID',old,true,now),'STALE');
  assert.equal(observationQuality('VALID',fresh,true,now),'VALID');
  assert.equal(observationQuality('VALID',fresh,false,now),'UNKNOWN');
  assert.equal(observationQuality('UNKNOWN',fresh,true,now),'UNKNOWN');
  assert.equal(observationQuality('UNSUPPORTED',null,true,now),'UNSUPPORTED');
  for (const stamp of [null, 'bad', '2026-09-21T07:01:00Z'])
    assert.equal(observationQuality('VALID',stamp,true,now),'UNKNOWN');
});

test('유효하지 않은 수치·차원·품질은 0이나 정상값으로 보이지 않는다', () => {
  assert.equal(measuredVector([0,1,2],3,'VALID'),'0.0000 / 1.0000 / 2.0000');
  for (const values of [null, [1,2], [1,null,3], [1,NaN,3], [1,Infinity,3]])
    assert.equal(measuredVector(values,3,'VALID'),'미확인');
  assert.equal(measuredVector([1,2,3],3,'STALE'),'미확인');
});

test('수동 ON은 경로·설정·준비·연결 세션·화면·공정 상태에 귀속된다', () => {
  const parts=['path',1,'hash','profile','profile-hash','preparation','SUCCEEDED','epoch','run','IDLE','prepare'];
  const key=executionConfirmationKey(parts,true);
  for (let i=0;i<parts.length;i++) {
    const next=[...parts]; next[i]='changed';
    assert.notEqual(executionConfirmationKey(next,true),key);
  }
  assert.equal(executionConfirmationKey(parts,false),'');
  assert.match(preparationStages.HOME_RECHECK,/재검사/);
});
