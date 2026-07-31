(function exposeIncrementalMarkdown(global) {
  function stableMarkdownBoundary(markdown) {
    const text = String(markdown || '');
    let boundary = 0;
    let offset = 0;
    let fence = '';
    const lines = text.match(/[^\n]*(?:\n|$)/g) || [];
    for (const segment of lines) {
      if (!segment) continue;
      const line = segment.endsWith('\n') ? segment.slice(0, -1) : segment;
      const marker = line.match(/^\s*(`{3,}|~{3,})/);
      if (marker) {
        if (!fence) fence = marker[1][0];
        else if (marker[1][0] === fence) fence = '';
      } else if (!fence && !line.trim() && segment.endsWith('\n')) {
        boundary = offset + segment.length;
      }
      offset += segment.length;
    }
    return boundary;
  }

  class FabIncrementalMarkdown {
    constructor() {
      this.committedLength = 0;
      this.lastText = '';
    }

    update(markdown) {
      const text = String(markdown || '');
      let reset = !text.startsWith(this.lastText) || this.committedLength > text.length;
      if (reset) this.committedLength = 0;
      const boundary = stableMarkdownBoundary(text);
      if (boundary < this.committedLength) {
        reset = true;
        this.committedLength = 0;
      }
      const stableDelta = text.slice(this.committedLength, boundary);
      this.committedLength = boundary;
      this.lastText = text;
      return {reset, stableDelta, tail: text.slice(boundary), text};
    }
  }

  global.FabIncrementalMarkdown = FabIncrementalMarkdown;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {FabIncrementalMarkdown, stableMarkdownBoundary};
  }
})(typeof window === 'undefined' ? globalThis : window);
