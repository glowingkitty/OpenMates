// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import {
  buildInteractiveHtmlDocument,
  buildInteractiveHtmlSrcdoc,
  INTERACTIVE_HTML_CSP,
  INTERACTIVE_HTML_SANDBOX,
  isInteractiveHtmlCode,
  resolveCodePreviewKind
} from './interactiveHtmlSandbox';

function parse(srcdoc: string): Document {
  return new DOMParser().parseFromString(srcdoc, 'text/html');
}

/** Parse the author document nested inside the wrapper srcdoc. */
function parseInner(source: string): Document {
  const wrapper = parse(buildInteractiveHtmlSrcdoc(source));
  return parse(wrapper.querySelector('iframe')?.getAttribute('srcdoc') ?? '');
}

describe('interactive HTML sandbox', () => {
  // contract-test: supporting surface=gui.web assertions=interactive-html.security.isolated-and-offline
  it('grants scripts only, never same-origin, forms, popups, navigation or downloads', () => {
    expect(INTERACTIVE_HTML_SANDBOX).toBe('allow-scripts');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.security.isolated-and-offline
  it('blocks every network destination in the policy', () => {
    for (const directive of [
      "default-src 'none'",
      "connect-src 'none'",
      "frame-src 'none'",
      "worker-src 'none'",
      "form-action 'none'",
      "base-uri 'none'",
      'img-src data: blob:',
      'font-src data:'
    ]) {
      expect(INTERACTIVE_HTML_CSP).toContain(directive);
    }
    expect(INTERACTIVE_HTML_CSP).not.toMatch(/https?:|\*/);
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.security.isolated-and-offline
  it('nests the visual in a script-free wrapper whose frame-src blocks every navigation', () => {
    const wrapper = parse(buildInteractiveHtmlSrcdoc('<p>x</p><script>location.href="https://example.com"</script>'));
    expect(wrapper.head.children[0].getAttribute('content')).toBe(INTERACTIVE_HTML_CSP);
    expect(INTERACTIVE_HTML_CSP).toContain("frame-src 'none'");
    expect(wrapper.querySelectorAll('script')).toHaveLength(0);
    const frames = wrapper.querySelectorAll('iframe');
    expect(frames).toHaveLength(1);
    expect(frames[0].getAttribute('sandbox')).toBe(INTERACTIVE_HTML_SANDBOX);
    expect(frames[0].getAttribute('srcdoc')).toBe(buildInteractiveHtmlDocument('<p>x</p><script>location.href="https://example.com"</script>'));
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.security.isolated-and-offline
  it('puts the policy and guard before author markup, even when the author has a full document', () => {
    const doc = parseInner(
      (
        '<!DOCTYPE html><html lang="en"><head><script>window.a=1</script><style>body{color:red}</style></head><body><canvas></canvas></body></html>'
      )
    );
    const head = doc.head.children;
    expect(head[0].tagName).toBe('META');
    expect(head[0].getAttribute('http-equiv')).toBe('Content-Security-Policy');
    expect(head[0].getAttribute('content')).toBe(INTERACTIVE_HTML_CSP);
    const scripts = Array.from(doc.querySelectorAll('script'));
    expect(scripts[0].textContent).toContain('RTCPeerConnection');
    expect(scripts[1].textContent).toBe('window.a=1');
    expect(doc.documentElement.getAttribute('lang')).toBe('en');
    expect(doc.querySelector('canvas')).not.toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.live-preview-and-code-switch
  it('keeps inline CSS and JavaScript of a bare fragment', () => {
    const doc = parseInner(('<style>.a{animation:spin 1s}</style><div class="a"></div><script>go()</script>'));
    expect(doc.querySelector('style:not([data-openmates-interactive-base])')?.textContent).toContain('animation');
    expect(Array.from(doc.querySelectorAll('script')).at(-1)?.textContent).toBe('go()');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.security.isolated-and-offline
  it('removes meta refresh navigation', () => {
    const srcdoc = buildInteractiveHtmlDocument('<meta http-equiv="refresh" content="0;url=https://example.com/?x=1"><p>hi</p>');
    expect(srcdoc).not.toMatch(/refresh/i);
    expect(srcdoc).toContain('<p>hi</p>');
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.live-preview-and-code-switch
  it('detects HTML code by language or filename', () => {
    expect(isInteractiveHtmlCode('html')).toBe(true);
    expect(isInteractiveHtmlCode('HTML ')).toBe(true);
    expect(isInteractiveHtmlCode('', 'solar-system.html')).toBe(true);
    expect(isInteractiveHtmlCode('javascript', 'app.js')).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=interactive-html.render.live-preview-and-code-switch
  it('resolves preview kinds', () => {
    expect(resolveCodePreviewKind('markdown')).toBe('markdown');
    expect(resolveCodePreviewKind('', 'README.md')).toBe('markdown');
    expect(resolveCodePreviewKind('html')).toBe('interactive-html');
    expect(resolveCodePreviewKind('xml')).toBe('html');
    expect(resolveCodePreviewKind('python', 'main.py')).toBeNull();
  });
});
