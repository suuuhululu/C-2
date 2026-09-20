import assert from 'node:assert/strict';
import test from 'node:test';
import { cylinderPoint, cutStrokes, previewSegments, matchesPreview } from '../src/monitor/preview.ts';

test('c2_base의 원통 위치를 빼고 U=0을 앞면에 표시하되 경로를 변경하지 않는다', () => {
  const profile = { payload: { surface: { axis_origin_m: [.4218, .0001, .0834], u_origin_angle_deg: 0 } } };
  const point = [.45605, .0001, .1909];
  const shown = cylinderPoint(point, profile);
  assert.ok(Math.abs(shown[0]) < 1e-12);
  assert.ok(Math.abs(shown[1] + .03425) < 1e-12);
  assert.ok(Math.abs(shown[2] - .1075) < 1e-12);
  assert.deepEqual(point, [.45605, .0001, .1909]);
  assert.deepEqual(cylinderPoint(point, { payload: { surface: {} } }), point);
});

test('실제 preview의 절삭/비절삭·분리 구간을 보존하고 전개면에는 CUT만 선택한다', () => {
  const segments = [
    { segment_id: 'a', kind: 'APPROACH', points_m: [[1, 2, 3]], connect_to_next: false },
    { segment_id: 'b', kind: 'CUT', points_uv_mm: [[0, 100]], connect_to_next: false },
    { segment_id: 'c', kind: 'CUT', points_uv_mm: [[10, 100]], connect_to_next: false },
    { segment_id: 'd', kind: 'RETRACT', points_m: [[1, 2, 3]], connect_to_next: false },
  ];
  const path = { path_id: 'path', path_version: 1, path_sha256: 'hash', preview: {
    contract: 'c2-path-preview/1', path_id: 'path', path_version: 1, path_sha256: 'hash', segments,
  } };
  assert.deepEqual(previewSegments(path), segments);
  assert.deepEqual(cutStrokes(path).map(s => s.segment_id), ['b', 'c']);
  assert.equal(matchesPreview(path, 'c2-path-preview/1'), true);
  assert.equal(matchesPreview(path, 'mock-preview/1'), false);
  assert.equal(matchesPreview({ ...path, path_sha256: 'other' }, 'c2-path-preview/1'), false);
  assert.equal(matchesPreview({ ...path, preview: { ...path.preview, segments: [] } }, 'c2-path-preview/1'), false);
  assert.deepEqual(cutStrokes(null), []);
});

test('기존 mock-preview/1은 strokes 배열을 유지한다', () => {
  const strokes = [{ segment_id: 'mock', kind: 'CUT', points_uv_mm: [[1, 2]] }];
  assert.deepEqual(cutStrokes({ preview: { contract: 'mock-preview/1', strokes } }), strokes);
});
