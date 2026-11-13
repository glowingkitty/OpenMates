/**
 * Shared helpers for showing partially streamed code embeds visually.
 *
 * `createThrottle` limits how often a re-render runs (leading + trailing),
 * `buildProgressiveHtmlSrcdoc` builds a script-free, network-free document
 * from partial HTML for a sandbox without `allow-scripts`.
 */
import { INTERACTIVE_HTML_CSP } from './interactiveHtmlSandbox';

export const PROGRESSIVE_RENDER_INTERVAL_MS = 200;

export interface Throttle {
  schedule: (task: () => void) => void;
  cancel: () => void;
}

/** Run the most recent scheduled task at most once per `intervalMs`. */
export function createThrottle(intervalMs: number, now: () => number = Date.now): Throttle {
  let lastRun = Number.NEGATIVE_INFINITY;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending: (() => void) | null = null;

  const run = () => {
    timer = null;
    const task = pending;
    pending = null;
    if (!task) return;
    lastRun = now();
    task();
  };

  return {
    schedule(task) {
      pending = task;
      if (timer !== null) return;
      const wait = lastRun + intervalMs - now();
      if (wait <= 0) run();
      else timer = setTimeout(run, wait);
    },
    cancel() {
      if (timer !== null) clearTimeout(timer);
      timer = null;
      pending = null;
    }
  };
}

const SCRIPT_BLOCK_RE = /<script\b[^>]*>[\s\S]*?<\/script\s*>/gi;
const SCRIPT_UNTERMINATED_RE = /<script\b[\s\S]*$/i;
const DANGLING_TAG_RE = /<[a-zA-Z!/][^>]*$/;
const META_REFRESH_RE = /<meta\b[^>]*http-equiv\s*=\s*["']?\s*refresh[^>]*>/gi;

/** Remove every script element (also an unterminated trailing one) and a dangling partial tag. */
export function stripScriptsFromPartialHtml(source: string): string {
  let out = source.replace(SCRIPT_BLOCK_RE, '').replace(META_REFRESH_RE, '');
  out = out.replace(SCRIPT_UNTERMINATED_RE, '');
  // Re-run: removing a block can expose another "<script" prefix cut mid-name.
  out = out.replace(/<scri?p?t?$/i, '');
  return out.replace(DANGLING_TAG_RE, '');
}

/** Sandbox for progressive HTML: no tokens, so no scripts, forms, popups or same-origin. */
export const PROGRESSIVE_HTML_SANDBOX = '';

const PROGRESSIVE_CSP = INTERACTIVE_HTML_CSP.replace("script-src 'unsafe-inline'", "script-src 'none'");

/** Script-free document for the partial HTML, or null when nothing visible is there yet. */
export function buildProgressiveHtmlDocument(partial: string): string | null {
  const stripped = stripScriptsFromPartialHtml(partial);
  if (!stripped.trim()) return null;
  return [
    '<!doctype html>',
    `<meta http-equiv="Content-Security-Policy" content="${PROGRESSIVE_CSP}">`,
    '<meta name="referrer" content="no-referrer">',
    '<style>html, body { margin: 0; min-height: 100%; } body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; } img, svg, canvas, video { max-width: 100%; }</style>',
    stripped
  ].join('\n');
}
