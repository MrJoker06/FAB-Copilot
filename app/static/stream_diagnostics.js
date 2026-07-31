(function exposeStreamDiagnostics(global) {
  class FabStreamDiagnostics {
    constructor() {
      this.startedAt = this.now();
      this.lastReadAt = null;
      this.runId = '';
      this.readChunks = 0;
      this.progressEvents = 0;
      this.answerEvents = 0;
      this.answerChars = 0;
      this.maxReadGapMs = 0;
      this.maxBufferPending = 0;
      this.renderFrames = 0;
      this.maxRenderMs = 0;
      this.totalRenderMs = 0;
      this.hiddenResumes = 0;
      this.stableAppends = 0;
      this.tailReplacements = 0;
      this.streamResets = 0;
      this.maxTailChars = 0;
    }

    now() {
      return typeof performance !== 'undefined' ? performance.now() : Date.now();
    }

    markRead(at = this.now()) {
      if (this.lastReadAt !== null) this.maxReadGapMs = Math.max(this.maxReadGapMs, at - this.lastReadAt);
      this.lastReadAt = at;
      this.readChunks += 1;
    }

    markProgress(event) {
      this.progressEvents += 1;
      if (event?.event === 'run_started') this.runId = String(event.run_id || '');
      if (event?.event === 'answer_delta') {
        this.answerEvents += 1;
        this.answerChars += String(event.delta || '').length;
      }
    }

    markPending(length) {
      this.maxBufferPending = Math.max(this.maxBufferPending, Number(length) || 0);
    }

    markRender(durationMs) {
      const duration = Math.max(0, Number(durationMs) || 0);
      this.renderFrames += 1;
      this.maxRenderMs = Math.max(this.maxRenderMs, duration);
      this.totalRenderMs += duration;
    }

    markIncrementalRender(stableChars, tailChars, reset) {
      if (Number(stableChars) > 0) this.stableAppends += 1;
      this.tailReplacements += 1;
      if (reset) this.streamResets += 1;
      this.maxTailChars = Math.max(this.maxTailChars, Number(tailChars) || 0);
    }

    markVisibleResume() {
      this.hiddenResumes += 1;
    }

    finish(finalMatch, at = this.now()) {
      return {
        run_id: this.runId,
        read_chunks: this.readChunks,
        progress_events: this.progressEvents,
        answer_events: this.answerEvents,
        answer_chars: this.answerChars,
        max_read_gap_ms: Math.round(this.maxReadGapMs * 10) / 10,
        max_buffer_pending: this.maxBufferPending,
        render_frames: this.renderFrames,
        max_render_ms: Math.round(this.maxRenderMs * 10) / 10,
        total_render_ms: Math.round(this.totalRenderMs * 10) / 10,
        hidden_resumes: this.hiddenResumes,
        stable_appends: this.stableAppends,
        tail_replacements: this.tailReplacements,
        stream_resets: this.streamResets,
        max_tail_chars: this.maxTailChars,
        final_match: Boolean(finalMatch),
        duration_ms: Math.round((at - this.startedAt) * 10) / 10,
      };
    }
  }

  global.FabStreamDiagnostics = FabStreamDiagnostics;
  if (typeof module !== 'undefined' && module.exports) module.exports = {FabStreamDiagnostics};
})(typeof window === 'undefined' ? globalThis : window);
