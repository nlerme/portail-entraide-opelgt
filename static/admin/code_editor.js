(() => {
  'use strict';

  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));

  function stringMask(text) {
    const mask = new Uint8Array(text.length);
    let quote = null;
    let escaped = false;
    for (let i = 0; i < text.length; i += 1) {
      const char = text[i];
      if (quote) {
        mask[i] = 1;
        if (escaped) escaped = false;
        else if (char === '\\') escaped = true;
        else if (char === quote) quote = null;
      } else if (char === '"' || char === "'") {
        quote = char;
        mask[i] = 1;
      }
    }
    return mask;
  }

  function matchingBrackets(text, caret) {
    const opening = { '(': ')', '[': ']', '{': '}' };
    const closing = { ')': '(', ']': '[', '}': '{' };
    const mask = stringMask(text);
    let index = -1;
    if (caret < text.length && (opening[text[caret]] || closing[text[caret]]) && !mask[caret]) index = caret;
    else if (caret > 0 && (opening[text[caret - 1]] || closing[text[caret - 1]]) && !mask[caret - 1]) index = caret - 1;
    if (index < 0) return new Set();

    const char = text[index];
    if (opening[char]) {
      const target = opening[char];
      let depth = 0;
      for (let i = index + 1; i < text.length; i += 1) {
        if (mask[i]) continue;
        if (text[i] === char) depth += 1;
        else if (text[i] === target) {
          if (depth === 0) return new Set([index, i]);
          depth -= 1;
        }
      }
    } else {
      const target = closing[char];
      let depth = 0;
      for (let i = index - 1; i >= 0; i -= 1) {
        if (mask[i]) continue;
        if (text[i] === char) depth += 1;
        else if (text[i] === target) {
          if (depth === 0) return new Set([index, i]);
          depth -= 1;
        }
      }
    }
    return new Set([index]);
  }

  function tokenizeJson(text, matches) {
    let output = '';
    let i = 0;
    const emit = (chunk, cssClass = '') => {
      const start = i;
      const escaped = [...chunk].map((char, offset) => {
        const value = escapeHtml(char);
        return matches.has(start + offset) ? `<mark class="code-bracket-match">${value}</mark>` : value;
      }).join('');
      output += cssClass ? `<span class="${cssClass}">${escaped}</span>` : escaped;
      i += chunk.length;
    };

    while (i < text.length) {
      const rest = text.slice(i);
      if (text[i] === '"') {
        let end = i + 1;
        let escaped = false;
        while (end < text.length) {
          const char = text[end];
          if (escaped) escaped = false;
          else if (char === '\\') escaped = true;
          else if (char === '"') { end += 1; break; }
          end += 1;
        }
        const token = text.slice(i, end);
        const after = text.slice(end).match(/^\s*:/);
        emit(token, after ? 'tok-key' : 'tok-string');
        continue;
      }
      const number = rest.match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
      if (number) { emit(number[0], 'tok-number'); continue; }
      const literal = rest.match(/^(?:true|false|null)\b/);
      if (literal) { emit(literal[0], 'tok-literal'); continue; }
      const char = text[i];
      emit(char, '{}[],:'.includes(char) ? 'tok-punctuation' : '');
    }
    return output || '\n';
  }

  function tokenizeLog(text, matches) {
    const lines = text.split('\n');
    let absolute = 0;
    return lines.map((line) => {
      let rendered = escapeHtml(line)
        .replace(/^(\d{4}-\d{2}-\d{2}[T ][^ ]*)/, '<span class="tok-date">$1</span>')
        .replace(/\b(ERROR|CRITICAL|FATAL|FAILED|ÉCHEC)\b/gi, '<span class="tok-error">$1</span>')
        .replace(/\b(WARN(?:ING)?|AVERTISSEMENT)\b/gi, '<span class="tok-warning">$1</span>')
        .replace(/\b(INFO|SUCCESS|OK|SUCCÈS)\b/gi, '<span class="tok-info">$1</span>')
        .replace(/\b(DEBUG|TRACE)\b/gi, '<span class="tok-debug">$1</span>');
      if ([...matches].some((index) => index >= absolute && index < absolute + line.length)) {
        let raw = '';
        for (let offset = 0; offset < line.length; offset += 1) {
          const char = escapeHtml(line[offset]);
          raw += matches.has(absolute + offset) ? `<mark class="code-bracket-match">${char}</mark>` : char;
        }
        rendered = raw;
      }
      absolute += line.length + 1;
      return rendered;
    }).join('\n') || '\n';
  }

  class CodeEditorLite {
    constructor(host, options = {}) {
      this.host = host;
      this.language = options.language || host.dataset.language || 'text';
      this.readOnly = Boolean(options.readOnly || host.dataset.readonly === 'true');
      this.label = options.label || host.getAttribute('aria-label') || 'Éditeur de code';
      this.host.classList.add('code-editor-shell');
      this.host.innerHTML = `
        <div class="code-editor-grid">
          <pre class="code-line-numbers" aria-hidden="true"></pre>
          <div class="code-editor-stage">
            <div class="code-current-line" aria-hidden="true"></div>
            <pre class="code-highlight" aria-hidden="true"><code></code></pre>
            <textarea class="code-input" spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="${escapeHtml(this.label)}"></textarea>
          </div>
        </div>
        <div class="code-status" aria-live="polite"><span>Ln 1, Col 1</span><span>${escapeHtml(this.language.toUpperCase())}</span></div>`;
      this.gutter = this.host.querySelector('.code-line-numbers');
      this.stage = this.host.querySelector('.code-editor-stage');
      this.currentLine = this.host.querySelector('.code-current-line');
      this.highlight = this.host.querySelector('.code-highlight code');
      this.input = this.host.querySelector('.code-input');
      this.status = this.host.querySelector('.code-status span');
      this.input.readOnly = this.readOnly;
      if (this.readOnly) this.host.classList.add('is-readonly');
      this.bind();
      this.setValue(options.value || '');
    }

    bind() {
      ['input', 'keyup', 'click', 'select'].forEach((eventName) => this.input.addEventListener(eventName, () => this.render()));
      this.input.addEventListener('scroll', () => this.syncScroll());
      this.input.addEventListener('keydown', (event) => {
        if (this.readOnly || event.key !== 'Tab') return;
        event.preventDefault();
        const start = this.input.selectionStart;
        const end = this.input.selectionEnd;
        this.input.setRangeText('  ', start, end, 'end');
        this.render();
      });
      if (typeof ResizeObserver !== 'undefined') {
        this.resizeObserver = new ResizeObserver(() => this.updateLineMetrics());
        this.resizeObserver.observe(this.input);
      }
    }

    getValue() { return this.input.value; }

    setValue(value) {
      this.input.value = String(value ?? '');
      this.input.scrollTop = 0;
      this.input.scrollLeft = 0;
      this.render();
    }

    focus() { this.input.focus(); }

    render() {
      const text = this.input.value;
      const matches = matchingBrackets(text, this.input.selectionStart);
      this.highlight.innerHTML = this.language === 'json' ? tokenizeJson(text, matches) : tokenizeLog(text, matches);
      const lineCount = Math.max(1, text.split('\n').length);
      this.gutter.textContent = Array.from({ length: lineCount }, (_, index) => index + 1).join('\n');
      this.updateLineMetrics();
      this.syncScroll();
      this.updateCaretStatus();
    }

    updateLineMetrics() {
      const style = getComputedStyle(this.input);
      const lineHeight = Number.parseFloat(style.lineHeight) || 22;
      const paddingTop = Number.parseFloat(style.paddingTop) || 0;
      const beforeCaret = this.input.value.slice(0, this.input.selectionStart);
      const lineIndex = beforeCaret.split('\n').length - 1;
      this.currentLine.style.height = `${lineHeight}px`;
      this.currentLine.style.top = `${paddingTop + (lineIndex * lineHeight) - this.input.scrollTop}px`;
      const minimum = this.readOnly ? 180 : 420;
      const contentHeight = Math.max(minimum, paddingTop * 2 + (Math.max(1, this.input.value.split('\n').length) * lineHeight));
      this.highlight.parentElement.style.minHeight = `${contentHeight}px`;
    }

    syncScroll() {
      this.highlight.parentElement.style.transform = `translate(${-this.input.scrollLeft}px, ${-this.input.scrollTop}px)`;
      this.gutter.style.transform = `translateY(${-this.input.scrollTop}px)`;
      this.updateLineMetrics();
    }

    updateCaretStatus() {
      const before = this.input.value.slice(0, this.input.selectionStart);
      const pieces = before.split('\n');
      this.status.textContent = `Ln ${pieces.length}, Col ${pieces.at(-1).length + 1}`;
    }
  }

  window.CodeEditorLite = CodeEditorLite;
})();
