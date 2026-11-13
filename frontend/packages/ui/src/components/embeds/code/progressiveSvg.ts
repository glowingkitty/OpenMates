/**
 * Progressive SVG rendering helpers for code embeds.
 *
 * While an assistant is still streaming SVG source, the source is incomplete:
 * the last tag, attribute or entity may be cut off and elements are still
 * open. `buildProgressiveSvg` turns such a partial string into a well-formed
 * document (cut at the last complete token, then close every open element).
 * Rendering always goes through an <img> with a data: URL, so scripts and
 * external resources can never execute or load (see svgToDataUrl).
 */

export interface SvgAspect {
  width: number;
  height: number;
}

const RAW_TEXT_ELEMENTS = new Set(['style', 'script']);

/** Result of scanning a tag that starts at `start` (which points at '<'). */
interface TagScan {
  end: number; // index just after '>'
  name: string;
  closing: boolean;
  selfClosing: boolean;
}

function scanTag(source: string, start: number): TagScan | null {
  let i = start + 1;
  const closing = source[i] === '/';
  if (closing) i += 1;
  const nameStart = i;
  while (i < source.length && /[^\s/>]/.test(source[i])) i += 1;
  const name = source.slice(nameStart, i);
  if (!name || !/^[A-Za-z_]/.test(name)) return null;
  let quote: string | null = null;
  for (; i < source.length; i += 1) {
    const ch = source[i];
    if (quote) {
      if (ch === quote) quote = null;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
    } else if (ch === '>') {
      return { end: i + 1, name, closing, selfClosing: !closing && source[i - 1] === '/' };
    }
  }
  return null;
}

function skipPast(source: string, from: number, terminator: string): number {
  const found = source.indexOf(terminator, from);
  return found === -1 ? -1 : found + terminator.length;
}

/**
 * Turn a (possibly partial) SVG source into a renderable document, or null
 * when no complete root `<svg ...>` open tag has arrived yet. A complete
 * document is returned unchanged.
 */
export function buildProgressiveSvg(source: string): string | null {
  const stack: string[] = [];
  let rootSeen = false;
  let rootClosed = false;
  let safeEnd = 0;
  let safeStack: string[] = [];
  let i = 0;

  const commit = (end: number) => {
    safeEnd = end;
    safeStack = stack.slice();
  };

  while (i < source.length && !rootClosed) {
    const lt = source.indexOf('<', i);
    if (lt === -1) break;
    let next: number;
    if (source.startsWith('<!--', lt)) {
      next = skipPast(source, lt + 4, '-->');
    } else if (source.startsWith('<![CDATA[', lt)) {
      next = skipPast(source, lt + 9, ']]>');
    } else if (source.startsWith('<?', lt)) {
      next = skipPast(source, lt + 2, '?>');
    } else if (source.startsWith('<!', lt)) {
      next = skipPast(source, lt + 2, '>');
    } else {
      const tag = scanTag(source, lt);
      if (!tag) break;
      next = tag.end;
      const lower = tag.name.toLowerCase();
      if (tag.closing) {
        const at = stack.lastIndexOf(tag.name);
        if (at === -1) {
          i = next;
          continue;
        }
        stack.length = at;
        if (rootSeen && stack.length === 0) rootClosed = true;
      } else if (!rootSeen && lower !== 'svg') {
        // Content before the root element other than svg is not renderable.
        break;
      } else {
        if (!tag.selfClosing) stack.push(tag.name);
        if (!rootSeen) {
          rootSeen = true;
          if (tag.selfClosing) rootClosed = true;
        }
        if (RAW_TEXT_ELEMENTS.has(lower) && !tag.selfClosing) {
          // Raw text content: only usable once its closing tag has arrived.
          const closeAt = source.toLowerCase().indexOf(`</${lower}`, next);
          if (closeAt === -1) {
            stack.pop();
            break;
          }
          const closeTag = scanTag(source, closeAt);
          if (!closeTag) {
            stack.pop();
            break;
          }
          stack.pop();
          next = closeTag.end;
        }
      }
    }
    if (next === -1) break;
    i = next;
    commit(i);
  }

  if (!rootSeen || safeEnd === 0 || safeStack.length === 0 && !rootClosed) return null;
  const head = source.slice(0, safeEnd);
  if (safeStack.length === 0) return source.slice(safeEnd).trim() === '' ? source : head;
  return head + safeStack.reverse().map((name) => `</${name}>`).join('');
}

function parseLength(value: string | undefined): number | null {
  if (!value) return null;
  const match = /^\s*([0-9]*\.?[0-9]+)\s*(px)?\s*$/i.exec(value);
  if (!match) return null;
  const n = Number(match[1]);
  return n > 0 ? n : null;
}

function readAttribute(tag: string, name: string): string | undefined {
  const re = new RegExp(`\\s${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)')`, 'i');
  const match = re.exec(tag);
  return match ? (match[1] ?? match[2]) : undefined;
}

/** Root `<svg ...>` open tag of a (possibly partial) source, if complete. */
function rootTag(source: string): string | null {
  const start = source.search(/<svg[\s>/]/i);
  if (start === -1) return null;
  const tag = scanTag(source, start);
  return tag ? source.slice(start, tag.end) : null;
}

/** Stable width/height ratio from width+height or viewBox; null if unknown. */
export function svgAspect(source: string): SvgAspect | null {
  const tag = rootTag(source);
  if (!tag) return null;
  const width = parseLength(readAttribute(tag, 'width'));
  const height = parseLength(readAttribute(tag, 'height'));
  if (width && height) return { width, height };
  const viewBox = readAttribute(tag, 'viewBox');
  if (viewBox) {
    const parts = viewBox.trim().split(/[\s,]+/).map(Number);
    if (parts.length === 4 && parts[2] > 0 && parts[3] > 0) return { width: parts[2], height: parts[3] };
  }
  return null;
}

/** True when code is a standalone `<svg ...>` document (xml declaration/comments/doctype may precede). */
export function isStandaloneSvg(code: string | null | undefined): boolean {
  if (!code) return false;
  const stripped = code
    .replace(/^\uFEFF/, '')
    .replace(/^(?:\s+|<\?[\s\S]*?\?>|<!--[\s\S]*?-->|<!DOCTYPE[^>]*>)+/i, '');
  return /^<svg[\s>/]/i.test(stripped);
}

/**
 * Encode an SVG as a data: URL for an <img>. Images never run scripts or load
 * external resources. The SVG namespace is added when the author omitted it,
 * because browsers refuse to render namespace-less SVG as an image.
 */
export function svgToDataUrl(svg: string): string {
  const tag = rootTag(svg);
  let doc = svg;
  if (tag && !/\sxmlns\s*=/.test(tag)) {
    doc = svg.replace(tag, tag.replace(/<svg/i, '<svg xmlns="http://www.w3.org/2000/svg"'));
  }
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(doc)}`;
}
