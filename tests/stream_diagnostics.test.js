const test = require('node:test');
const assert = require('node:assert/strict');
const {FabStreamDiagnostics} = require('../app/static/stream_diagnostics.js');

test('stream diagnostics only reports aggregate delivery metrics', () => {
  const metrics = new FabStreamDiagnostics();
  metrics.startedAt = 100;
  metrics.markRead(120);
  metrics.markRead(180);
  metrics.markProgress({event: 'run_started', run_id: 'run-12345678'});
  metrics.markProgress({event: 'answer_delta', delta: '不能写入遥测的正文'});
  metrics.markPending(80);
  metrics.markRender(12.34);
  metrics.markVisibleResume();

  const payload = metrics.finish(true, 300);
  assert.deepEqual(payload, {
    run_id: 'run-12345678', read_chunks: 2, progress_events: 2, answer_events: 1,
    answer_chars: 9, max_read_gap_ms: 60, max_buffer_pending: 80, render_frames: 1,
    max_render_ms: 12.3, total_render_ms: 12.3, hidden_resumes: 1,
    final_match: true, duration_ms: 200,
  });
  assert.equal(JSON.stringify(payload).includes('不能写入遥测的正文'), false);
});
