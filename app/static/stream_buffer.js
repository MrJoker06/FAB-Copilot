(function exposeSmoothTextBuffer(global) {
  class FabSmoothTextBuffer {
    constructor() {
      this.received = '';
      this.visible = '';
      this.pending = [];
      this.complete = false;
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
        } else {
          this.received = finalAnswer;
          this.visible = '';
          this.pending = Array.from(finalAnswer);
        }
      }
      this.complete = true;
    }

    takeNext() {
      const backlog = this.pending.length;
      if (!backlog) return this.visible;
      const count = backlog > 600 ? 16 : backlog > 240 ? 10 : backlog > 80 ? 6 : backlog > 24 ? 4 : 2;
      this.visible += this.pending.splice(0, count).join('');
      return this.visible;
    }

    get pendingLength() {
      return this.pending.length;
    }

    get done() {
      return this.complete && this.pending.length === 0;
    }
  }

  global.FabSmoothTextBuffer = FabSmoothTextBuffer;
  if (typeof module !== 'undefined' && module.exports) module.exports = {FabSmoothTextBuffer};
})(typeof window === 'undefined' ? globalThis : window);
