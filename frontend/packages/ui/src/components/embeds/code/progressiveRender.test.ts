import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildProgressiveSvg, isStandaloneSvg, svgAspect, svgToDataUrl } from './progressiveSvg';
import {
  buildProgressiveHtmlDocument,
  createThrottle,
  PROGRESSIVE_HTML_SANDBOX,
  stripScriptsFromPartialHtml
} from './progressiveRender';
import { resolveCodePreviewKind } from './interactiveHtmlSandbox';

describe('buildProgressiveSvg', () => {
  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('returns null before a complete svg open tag exists', () => {
    expect(buildProgressiveSvg('')).toBeNull();
    expect(buildProgressiveSvg('<sv')).toBeNull();
    expect(buildProgressiveSvg('<svg viewBox="0 0 10')).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('closes the root when only the open tag has arrived', () => {
    expect(buildProgressiveSvg('<svg viewBox="0 0 10 10">')).toBe('<svg viewBox="0 0 10 10"></svg>');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('drops a dangling partial tag', () => {
    expect(buildProgressiveSvg('<svg><rect width="1"/><circ')).toBe('<svg><rect width="1"/></svg>');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('drops an attribute cut mid-string, even when it contains ">"', () => {
    expect(buildProgressiveSvg('<svg><path d="M0 0 L1 1"/><text x="1" y="a>b')).toBe('<svg><path d="M0 0 L1 1"/></svg>');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('closes unclosed nested groups in order', () => {
    expect(buildProgressiveSvg('<svg><g id="a"><g id="b"><rect/>')).toBe('<svg><g id="a"><g id="b"><rect/></g></g></svg>');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('drops trailing partial text and entity', () => {
    expect(buildProgressiveSvg('<svg><text>Tom &am')).toBe('<svg><text></text></svg>');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('ignores an unfinished comment and CDATA', () => {
    expect(buildProgressiveSvg('<svg><rect/><!-- note <g>')).toBe('<svg><rect/></svg>');
    expect(buildProgressiveSvg('<svg><rect/><![CDATA[ x')).toBe('<svg><rect/></svg>');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('keeps a complete comment and does not close self-closing tags', () => {
    expect(buildProgressiveSvg('<svg><!-- a > b --><g><use href="#x"/>')).toBe('<svg><!-- a > b --><g><use href="#x"/></g></svg>');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('ignores an unfinished style element but keeps a finished one', () => {
    expect(buildProgressiveSvg('<svg><rect/><style>.a{fill:red')).toBe('<svg><rect/></svg>');
    expect(buildProgressiveSvg('<svg><style>.a>b{fill:red}</style><g>')).toBe('<svg><style>.a>b{fill:red}</style><g></g></svg>');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('returns a finished document untouched', () => {
    const doc = '<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"><g><rect/></g></svg>\n';
    expect(buildProgressiveSvg(doc)).toBe(doc);
  });
});

describe('svg helpers', () => {
  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('reads the aspect from width/height or viewBox', () => {
    expect(svgAspect('<svg width="200px" height="100">')).toEqual({ width: 200, height: 100 });
    expect(svgAspect('<svg viewBox="0 0 30, 10">')).toEqual({ width: 30, height: 10 });
    expect(svgAspect('<svg width="100%">')).toBeNull();
    expect(svgAspect('<svg viewBox="0 0')).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('detects standalone svg documents', () => {
    expect(isStandaloneSvg('<?xml version="1.0"?>\n<!-- c -->\n<svg></svg>')).toBe(true);
    expect(isStandaloneSvg('<note><svg/></note>')).toBe(false);
    expect(isStandaloneSvg(null)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('builds an image data URL and adds the namespace when missing', () => {
    const url = svgToDataUrl('<svg viewBox="0 0 1 1"></svg>');
    expect(url.startsWith('data:image/svg+xml')).toBe(true);
    expect(decodeURIComponent(url)).toContain('xmlns="http://www.w3.org/2000/svg"');
    expect(decodeURIComponent(svgToDataUrl('<svg xmlns="http://www.w3.org/2000/svg"></svg>')).match(/xmlns/g)).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('resolves svg preview kind by language, extension or xml content', () => {
    expect(resolveCodePreviewKind('svg')).toBe('svg');
    expect(resolveCodePreviewKind('', 'logo.svg')).toBe('svg');
    expect(resolveCodePreviewKind('xml', null, '<svg></svg>')).toBe('svg');
    expect(resolveCodePreviewKind('xml', null, '<a/>')).toBe('html');
  });
});

describe('progressive html', () => {
  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('strips complete, unterminated and half-typed script tags', () => {
    expect(stripScriptsFromPartialHtml('<p>a</p><script>x()</script><p>b</p>')).toBe('<p>a</p><p>b</p>');
    expect(stripScriptsFromPartialHtml('<p>a</p><script>let x = "</p>')).toBe('<p>a</p>');
    expect(stripScriptsFromPartialHtml('<p>a</p><scr')).toBe('<p>a</p>');
    expect(stripScriptsFromPartialHtml('<p>a</p><div class="x')).toBe('<p>a</p>');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('builds a script-free document under a token-less sandbox', () => {
    const doc = buildProgressiveHtmlDocument('<h1>Hi</h1><script>alert(1)')!;
    expect(doc).toContain('<h1>Hi</h1>');
    expect(doc).not.toContain('alert');
    expect(doc).toContain("script-src 'none'");
    expect(PROGRESSIVE_HTML_SANDBOX).toBe('');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('returns null when nothing is visible yet', () => {
    expect(buildProgressiveHtmlDocument('')).toBeNull();
    expect(buildProgressiveHtmlDocument('<script>x')).toBeNull();
  });
});

describe('createThrottle', () => {
  afterEach(() => vi.useRealTimers());

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('runs first task immediately, coalesces later ones to the latest', () => {
    vi.useFakeTimers();
    const throttle = createThrottle(200, () => Date.now());
    const calls: number[] = [];
    throttle.schedule(() => calls.push(1));
    throttle.schedule(() => calls.push(2));
    throttle.schedule(() => calls.push(3));
    expect(calls).toEqual([1]);
    vi.advanceTimersByTime(200);
    expect(calls).toEqual([1, 3]);
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.vector-image-and-progressive-streaming
  it('cancel drops the pending task', () => {
    vi.useFakeTimers();
    const throttle = createThrottle(200, () => Date.now());
    const calls: number[] = [];
    throttle.schedule(() => calls.push(1));
    throttle.schedule(() => calls.push(2));
    throttle.cancel();
    vi.advanceTimersByTime(500);
    expect(calls).toEqual([1]);
  });
});
