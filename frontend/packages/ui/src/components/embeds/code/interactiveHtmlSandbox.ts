/**
 * Interactive HTML sandbox for code embeds.
 *
 * HTML code embeds (assistant-generated visuals, animations, explainers, or
 * uploaded .html files) render live with their inline CSS and JavaScript.
 * Isolation comes from three independent layers, so no single bypass exposes
 * the app or the device:
 *
 * 1. The iframe sandbox grants only `allow-scripts`. Without
 *    `allow-same-origin` the document runs in an opaque origin: it cannot read
 *    the app's cookies, storage, IndexedDB, keys or DOM. Without
 *    `allow-forms`, `allow-popups`, `allow-top-navigation`, `allow-modals` and
 *    `allow-downloads` it cannot submit, open windows, navigate the app,
 *    show dialogs or download files.
 * 2. A Content-Security-Policy meta element is the first node of the document,
 *    before any author markup, so it applies to every author script. It blocks
 *    all network fetches (scripts, styles, images, fonts, media, XHR/fetch,
 *    WebSocket, workers, frames, form targets). Only inline code and data:/blob:
 *    media are allowed. A CSP delivered this way can only be tightened later,
 *    never relaxed, even if author script removes the element.
 * 3. The author document is nested inside a wrapper document that carries the
 *    same policy. Browsers check every navigation of a frame, including one
 *    the frame starts itself (location.href = ...), against its parent's
 *    frame-src. With frame-src 'none' in the wrapper, the visual can never load
 *    another page, so navigation cannot be used to send data out. (The
 *    Navigation API cannot do this: Chromium does not fire `navigate` for
 *    cross-origin navigations of an opaque-origin frame.)
 * 4. A guard script before author markup ignores link activation (so a click
 *    does not end on the browser's blocked-page screen) and removes WebRTC
 *    constructors, which CSP connect-src does not cover.
 *
 * The renderer additionally tears the frame down if the wrapper ever loads a
 * second document (see InteractiveHtmlFrame.svelte).
 */

export const INTERACTIVE_HTML_SANDBOX = 'allow-scripts';

export const INTERACTIVE_HTML_CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline'",
  "style-src 'unsafe-inline'",
  'img-src data: blob:',
  'media-src data: blob:',
  'font-src data:',
  "connect-src 'none'",
  "frame-src 'none'",
  "child-src 'none'",
  "worker-src 'none'",
  "object-src 'none'",
  "manifest-src 'none'",
  "base-uri 'none'",
  "form-action 'none'"
].join('; ');

const HTML_LANGUAGES = new Set(['html', 'htm', 'xhtml']);
const HTML_EXTENSIONS = new Set(['.html', '.htm']);

const META_REFRESH_RE = /<meta\b[^>]*http-equiv\s*=\s*["']?\s*refresh[^>]*>/gi;

/**
 * Guard runs before any author script. A listener registered first on window
 * in the capture phase runs before author listeners, and preventDefault from
 * any listener cancels the default action.
 */
const GUARD_SCRIPT = `(function () {
  window.addEventListener('click', function (event) {
    var target = event.target;
    var link = target && target.closest ? target.closest('a[href],area[href]') : null;
    if (!link) return;
    var href = link.getAttribute('href') || '';
    if (href.charAt(0) !== '#') event.preventDefault();
  }, true);
  ['RTCPeerConnection', 'webkitRTCPeerConnection', 'RTCDataChannel', 'RTCIceCandidate'].forEach(function (name) {
    if (name in window) {
      Object.defineProperty(window, name, { value: undefined, writable: false, configurable: false });
    }
  });
})();`;

const BASE_STYLE = `html, body { margin: 0; min-height: 100%; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
img, svg, canvas, video { max-width: 100%; }`;

function extensionOf(filename: string | null | undefined): string {
  if (!filename) return '';
  const dot = filename.lastIndexOf('.');
  return dot >= 0 ? filename.slice(dot).toLowerCase() : '';
}

/** True when a code embed holds HTML that should render as a live visual. */
export function isInteractiveHtmlCode(language: string | null | undefined, filename?: string | null): boolean {
  if (HTML_LANGUAGES.has((language || '').trim().toLowerCase())) return true;
  return HTML_EXTENSIONS.has(extensionOf(filename));
}

function escapeAttribute(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

/**
 * Build the author document. The security preamble is placed before the
 * author markup; the HTML parser keeps it in <head>, merges a later author
 * <html>/<head> into the same elements and ignores a second doctype, so
 * author markup can never precede the policy.
 */
export function buildInteractiveHtmlDocument(source: string): string {
  const authored = source.replace(META_REFRESH_RE, '');
  return [
    '<!doctype html>',
    `<meta http-equiv="Content-Security-Policy" content="${INTERACTIVE_HTML_CSP}">`,
    '<meta http-equiv="x-dns-prefetch-control" content="off">',
    '<meta name="referrer" content="no-referrer">',
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    `<script>${GUARD_SCRIPT}</script>`,
    `<style data-openmates-interactive-base>${BASE_STYLE}</style>`,
    authored
  ].join('\n');
}

/**
 * Build the srcdoc for the sandboxed iframe: a script-free wrapper with the
 * same policy whose only child frame holds the author document.
 */
export function buildInteractiveHtmlSrcdoc(source: string): string {
  return [
    '<!doctype html>',
    `<meta http-equiv="Content-Security-Policy" content="${INTERACTIVE_HTML_CSP}">`,
    '<meta name="referrer" content="no-referrer">',
    '<style>html, body { margin: 0; height: 100%; overflow: hidden; } iframe { display: block; width: 100%; height: 100%; border: 0; }</style>',
    `<iframe sandbox="${INTERACTIVE_HTML_SANDBOX}" allow="" referrerpolicy="no-referrer" title="visual" srcdoc="${escapeAttribute(buildInteractiveHtmlDocument(source))}"></iframe>`
  ].join('\n');
}

export type CodePreviewKind = 'markdown' | 'interactive-html' | 'html' | null;

const MARKDOWN_LANGUAGES = new Set(['markdown', 'md']);
const MARKDOWN_EXTENSIONS = new Set(['.md', '.markdown']);

/**
 * Which rendered preview a code embed supports: markdown (inline, sanitized),
 * interactive-html (live sandboxed visual), static html (XML/other markup
 * shown inert) or none.
 */
export function resolveCodePreviewKind(language: string | null | undefined, filename?: string | null): CodePreviewKind {
  const lang = (language || '').trim().toLowerCase();
  const ext = extensionOf(filename);
  if (MARKDOWN_LANGUAGES.has(lang) || MARKDOWN_EXTENSIONS.has(ext)) return 'markdown';
  if (isInteractiveHtmlCode(lang, filename)) return 'interactive-html';
  if (lang === 'xml') return 'html';
  return null;
}
