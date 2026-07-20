(function exposeSmoothTextBuffer(global) {
  class FabSmoothTextBuffer {
    constructor() {
      this.received = '';
      this.visible = '';
      this.pending = [];
      this.pendingOffset = 0;
      this.complete = false;
      this.drainFramesRemaining = null;
    }

    append(delta) {
      const text = String(delta || '');
      if (!text) return;
      this.received += text;
      this.pending.push(...Array.from(text));
    }

    finish(finalText = '') {
      const finalAnswer = String(finalText || '');
      if (finalAnswer && finalAnswer !== this.received) {
        if (finalAnswer.startsWith(this.received)) {
          this.append(finalAnswer.slice(this.received.length));
        } else if (finalAnswer.startsWith(this.visible)) {
          this.received = finalAnswer;
          this.pending = Array.from(finalAnswer.slice(this.visible.length));
          this.pendingOffset = 0;
        } else {
          this.received = finalAnswer;
          this.visible = '';
          this.pending = Array.from(finalAnswer);
          this.pendingOffset = 0;
        }
      }
      this.complete = true;
      this.drainFramesRemaining = null;
    }

    takeNext({targetFrames, minChars = 8, maxChars = 384} = {}) {
      const backlog = this.pendingLength;
      if (!backlog) return this.visible;
      const frames = Math.max(1, Number(targetFrames) || (this.complete ? 3 : 6));
      if (this.complete && this.drainFramesRemaining === null) {
        this.drainFramesRemaining = Math.max(frames, Math.ceil(backlog / maxChars));
      }
      const remainingFrames = this.complete ? Math.max(1, this.drainFramesRemaining) : frames;
      const count = Math.min(backlog, Math.max(minChars, Math.min(maxChars, Math.ceil(backlog / remainingFrames))));
      this.visible += this.pending.slice(this.pendingOffset, this.pendingOffset + count).join('');
      this.pendingOffset += count;
      if (this.complete) this.drainFramesRemaining = Math.max(0, this.drainFramesRemaining - 1);
      if (this.pendingOffset > 2048 && this.pendingOffset > this.pending.length / 2) {
        this.pending = this.pending.slice(this.pendingOffset);
        this.pendingOffset = 0;
      }
      return this.visible;
    }

    get pendingLength() {
      return this.pending.length - this.pendingOffset;
    }

    get done() {
      return this.complete && this.pendingLength === 0;
    }
  }

  global.FabSmoothTextBuffer = FabSmoothTextBuffer;
  if (typeof module !== 'undefined' && module.exports) module.exports = {FabSmoothTextBuffer};
})(typeof window === 'undefined' ? globalThis : window);
