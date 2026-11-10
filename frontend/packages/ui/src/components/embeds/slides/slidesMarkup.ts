/**
 * frontend/packages/ui/src/components/embeds/slides/slidesMarkup.ts
 *
 * Client parser for the `slides_markup` field of a `deck` embed (grammar:
 * docs/architecture/apps/slides-format.md). It mirrors the whitelist of
 * backend/shared/python_utils/slides_markup.py on purpose: shared and uploaded
 * decks never pass through the backend normaliser, so the client must not
 * trust the string.
 *
 * Security contract (assertion slides.security.host-rendered-and-isolated):
 * - the markup is parsed with DOMParser into an inert document (no browsing
 *   context, nothing loads or runs) and a typed model is built from whitelisted
 *   elements and attributes only;
 * - the model holds no HTML; callers render it as Svelte nodes and must never
 *   assign deck-derived strings to innerHTML / {@html};
 * - every URL except `embed:` refs, `youtube:`/`vimeo:` ids and the https href
 *   of `<link>` is dropped; `on*`, `style` and unknown attributes never reach
 *   the model;
 * - `<block>` bodies are extracted before parsing and kept as opaque strings
 *   for the sandboxed frame.
 */

export const CANVAS_WIDTH = 1920;
export const ASPECT_HEIGHTS = { '16:9': 1080, '16:10': 1200, '4:3': 1440 } as const;
export type SlideAspect = keyof typeof ASPECT_HEIGHTS;
export const DEFAULT_ASPECT: SlideAspect = '16:9';
export const DEFAULT_TEMPLATE = 'builtin:plain';

export const MAX_SOURCE_CHARS = 1_000_000;
export const MAX_SLIDES = 200;
export const MAX_ELEMENTS_PER_SLIDE = 200;
export const MAX_NOTE_CHARS = 5000;

const COLOR_TOKENS = new Set(['background', 'foreground', 'accent', 'accent-2', 'muted', 'surface']);
const SAFE_FONTS = new Map(
  [
    'Arial', 'Helvetica', 'Georgia', 'Times New Roman', 'Courier New', 'Verdana',
    'Trebuchet MS', 'system-ui', 'serif', 'sans-serif', 'monospace'
  ].map((font) => [font.toLowerCase(), font])
);
const FONT_ROLES = new Set(['heading', 'body']);
const TEXT_ROLES = ['title', 'subtitle', 'body', 'caption', 'quote'] as const;
const ALIGNS = ['left', 'center', 'right', 'justify'] as const;
const SHAPE_KINDS = ['rect', 'ellipse', 'line', 'triangle'] as const;
const ANIMATIONS = ['fade', 'slide-in', 'appear'] as const;
const TRANSITIONS = ['none', 'fade', 'slide'] as const;
const FITS = ['cover', 'contain'] as const;
const INLINE_TAGS = new Set(['b', 'i', 'u', 's', 'br', 'ul', 'ol', 'li']);
const ELEMENT_TAGS = new Set(['text', 'image', 'video', 'shape', 'notepad', 'todo', 'link', 'block']);
/** Elements the backend treats as void (never hold children). */
const VOID_ELEMENTS = new Set(['image', 'video', 'shape']);
/** Names the HTML parser would otherwise rewrite (`image`) or treat as void (`link`). */
const RENAMED_ELEMENTS = new Set(['image', 'link']);
const DANGEROUS_TAGS = new Set([
  'script', 'style', 'iframe', 'object', 'embed', 'template', 'noscript', 'svg',
  'math', 'frame', 'frameset', 'applet'
]);

const ID_RE = /^[a-z][a-z0-9-]{0,31}$/;
const LAYOUT_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;
const TEMPLATE_RE = /^(builtin|library):[A-Za-z0-9._-]{1,64}$/;
const EMBED_REF_RE = /^[A-Za-z0-9._-]{1,128}$/;
const YOUTUBE_RE = /^[A-Za-z0-9_-]{6,20}$/;
const VIMEO_RE = /^[0-9]{3,12}$/;
const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
const INT_RE = /^-?[0-9]{1,6}(?:\.[0-9]+)?$/;
const BLOCK_START_RE = /<block(?=[\s/>])/gi;
const BLOCK_END_RE = /<\/block\s*>/gi;
const BLOCK_MARK = 'data-om-block-index';

export type TextRole = (typeof TEXT_ROLES)[number];
export type SlideAnimation = (typeof ANIMATIONS)[number];
export type SlideTransition = (typeof TRANSITIONS)[number];

/** Inline text tree: real nodes are rebuilt by the renderer, never HTML strings. */
export type InlineNode =
  | { kind: 'text'; text: string }
  | { kind: 'br' }
  | { kind: 'tag'; tag: 'b' | 'i' | 'u' | 's' | 'ul' | 'ol' | 'li'; children: InlineNode[] };

export interface ElementBox {
  x?: number;
  y?: number;
  w?: number;
  h?: number;
}

interface ElementBase {
  id: string;
  box: ElementBox;
  animate?: SlideAnimation;
  /** Build step: 0 shows with the slide, n > 0 appears on the nth advance. */
  step: number;
}

export interface TextElement extends ElementBase {
  type: 'text';
  role?: TextRole;
  font?: string;
  size?: number;
  color?: string;
  align?: (typeof ALIGNS)[number];
  weight?: string;
  content: InlineNode[];
}
export interface ImageElement extends ElementBase {
  type: 'image';
  /** Embed ref without the `embed:` prefix. */
  ref: string;
  alt: string;
  fit: (typeof FITS)[number];
}
export interface VideoElement extends ElementBase {
  type: 'video';
  provider: 'embed' | 'youtube' | 'vimeo';
  ref: string;
  alt: string;
}
export interface ShapeElement extends ElementBase {
  type: 'shape';
  kind: (typeof SHAPE_KINDS)[number];
  fill?: string;
  stroke?: string;
}
export interface NotepadElement extends ElementBase {
  type: 'notepad';
  title: string;
  /** Plain-text body (newlines kept); empty when nothing was typed. */
  text: string;
  /** Hidden elements keep their content but are not rendered. */
  hidden: boolean;
}
export interface TodoElement extends ElementBase {
  type: 'todo';
  title: string;
  hidden: boolean;
  items: { done: boolean; label: string }[];
}
export interface LinkElement extends ElementBase {
  type: 'link';
  href: string;
  label: string;
}
export interface BlockElement extends ElementBase {
  type: 'block';
  title: string;
  /** Opaque verbatim body; only the sandboxed frame may interpret it. */
  body: string;
}
export type SlideElement =
  | TextElement | ImageElement | VideoElement | ShapeElement | NotepadElement
  | TodoElement | LinkElement | BlockElement;

export interface Slide {
  id: string;
  layout?: string;
  transition: SlideTransition;
  elements: SlideElement[];
  notes: string;
}

export interface Deck {
  title: string;
  aspect: SlideAspect;
  width: number;
  height: number;
  template: string;
  slides: Slide[];
}

export type ParseResult = { ok: true; deck: Deck } | { ok: false; reason: 'empty' | 'too-large' | 'no-slide' };

export interface ParseOptions {
  /** Streaming: keep only slides whose closing tag has arrived. */
  partial?: boolean;
}

// ------------------------------------------------------------ value cleaners

function cleanInt(value: string | null, low: number, high: number): number | undefined {
  if (value === null || !INT_RE.test(value.trim())) return undefined;
  return Math.max(low, Math.min(high, Math.trunc(Number(value))));
}

function cleanLabel(value: string, max = 300): string {
  return value.replace(/\s+/g, ' ').trim().slice(0, max);
}

/** Notepad body, same rules as the backend `_clean_note`. */
function cleanNote(value: string): string {
  // eslint-disable-next-line no-control-regex -- control characters are exactly what is dropped
  return value.replace(/[\x00-\x08\x0b-\x1f\x7f]/g, '').trim().slice(0, MAX_NOTE_CHARS).trimEnd();
}

function cleanHidden(value: string | null): boolean {
  return (value ?? '').trim().toLowerCase() === 'true';
}

function cleanColor(value: string | null): string | undefined {
  if (value === null) return undefined;
  const trimmed = value.trim();
  if (COLOR_TOKENS.has(trimmed.toLowerCase())) return trimmed.toLowerCase();
  return HEX_RE.test(trimmed) ? trimmed.toLowerCase() : undefined;
}

function cleanFont(value: string | null): string | undefined {
  if (value === null) return undefined;
  const lower = value.trim().toLowerCase();
  return FONT_ROLES.has(lower) ? lower : SAFE_FONTS.get(lower);
}

function cleanWeight(value: string | null): string | undefined {
  if (value === null) return undefined;
  const lower = value.trim().toLowerCase();
  if (lower === 'normal' || lower === 'bold') return lower;
  return /^[1-9]00$/.test(lower) ? lower : undefined;
}

function cleanChoice<T extends string>(value: string | null, options: readonly T[]): T | undefined {
  if (value === null) return undefined;
  const lower = value.trim().toLowerCase();
  return options.find((option) => option === lower);
}

function cleanEmbedRef(value: string | null): string | undefined {
  const trimmed = value?.trim() ?? '';
  if (!trimmed.startsWith('embed:')) return undefined;
  const ref = trimmed.slice('embed:'.length);
  return EMBED_REF_RE.test(ref) ? ref : undefined;
}

function hasControlChar(value: string): boolean {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code <= 0x1f || code === 0x7f) return true;
  }
  return false;
}

/** https only, no credentials, no whitespace/control/markup characters. */
export function cleanHttpsUrl(value: string | null): string | undefined {
  const trimmed = value?.trim() ?? '';
  if (!trimmed || trimmed.length > 2000 || /[\s<>"']/.test(trimmed) || hasControlChar(trimmed)) return undefined;
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return undefined;
  }
  return parsed.protocol === 'https:' && parsed.host && !parsed.username && !parsed.password
    ? trimmed
    : undefined;
}

function cleanVideoSrc(value: string | null): Pick<VideoElement, 'provider' | 'ref'> | undefined {
  const trimmed = value?.trim() ?? '';
  const embedRef = cleanEmbedRef(trimmed);
  if (embedRef) return { provider: 'embed', ref: embedRef };
  if (trimmed.startsWith('youtube:') && YOUTUBE_RE.test(trimmed.slice(8))) {
    return { provider: 'youtube', ref: trimmed.slice(8) };
  }
  if (trimmed.startsWith('vimeo:') && VIMEO_RE.test(trimmed.slice(6))) {
    return { provider: 'vimeo', ref: trimmed.slice(6) };
  }
  return undefined;
}

// --------------------------------------------------------------- tokenizing

/**
 * Replace every `<block>` with an empty marked tag; return the new source and
 * the verbatim bodies. Mirrors `_extract_blocks` in the backend normaliser:
 * quote-aware start tag, body up to the first `</block>`, unterminated blocks
 * (and everything after) dropped.
 */
function extractBlocks(source: string): { stripped: string; blocks: { attrs: string; body: string }[] } {
  const out: string[] = [];
  const blocks: { attrs: string; body: string }[] = [];
  let pos = 0;
  for (;;) {
    BLOCK_START_RE.lastIndex = pos;
    const match = BLOCK_START_RE.exec(source);
    if (!match) {
      out.push(source.slice(pos));
      break;
    }
    out.push(source.slice(pos, match.index));
    let i = match.index + match[0].length;
    const attrStart = i;
    let quote = '';
    while (i < source.length) {
      const ch = source[i];
      if (quote) {
        if (ch === quote) quote = '';
      } else if (ch === '"' || ch === "'") {
        quote = ch;
      } else if (ch === '>') {
        break;
      }
      i += 1;
    }
    if (i >= source.length) break;
    let attrs = source.slice(attrStart, i);
    pos = i + 1;
    let body = '';
    if (attrs.trimEnd().endsWith('/')) {
      attrs = attrs.trimEnd().slice(0, -1);
    } else {
      BLOCK_END_RE.lastIndex = pos;
      const end = BLOCK_END_RE.exec(source);
      if (!end) break;
      body = source.slice(pos, end.index);
      pos = end.index + end[0].length;
    }
    blocks.push({ attrs, body });
    out.push(`<block ${BLOCK_MARK}="${blocks.length - 1}" ${attrs}></block>`);
  }
  return { stripped: out.join(''), blocks };
}

/**
 * Make the HTML parser see the grammar the way the backend does: `image` and
 * `link` are renamed (the parser rewrites `<image>` to `<img>` and `<link>` is
 * void), self-closing tags become explicit pairs and void deck elements never
 * swallow their following siblings. Quote-aware so attribute values are never
 * touched.
 */
function prepareForHtmlParser(source: string): string {
  const out: string[] = [];
  let pos = 0;
  while (pos < source.length) {
    const lt = source.indexOf('<', pos);
    if (lt === -1) {
      out.push(source.slice(pos));
      break;
    }
    out.push(source.slice(pos, lt));
    const nameMatch = /^<(\/?)([A-Za-z][A-Za-z0-9-]*)/.exec(source.slice(lt, lt + 80));
    if (!nameMatch) {
      out.push('<');
      pos = lt + 1;
      continue;
    }
    let i = lt + nameMatch[0].length;
    let quote = '';
    while (i < source.length) {
      const ch = source[i];
      if (quote) {
        if (ch === quote) quote = '';
      } else if (ch === '"' || ch === "'") {
        quote = ch;
      } else if (ch === '>') {
        break;
      }
      i += 1;
    }
    if (i >= source.length) {
      out.push(source.slice(lt));
      break;
    }
    const closing = nameMatch[1] === '/';
    const lower = nameMatch[2].toLowerCase();
    const name = RENAMED_ELEMENTS.has(lower) ? `om-${lower}` : nameMatch[2];
    let attrText = source.slice(lt + nameMatch[0].length, i);
    const selfClosing = !closing && attrText.trimEnd().endsWith('/');
    if (selfClosing) attrText = attrText.trimEnd().slice(0, -1);
    out.push(`<${closing ? '/' : ''}${name}${attrText}>`);
    if (!closing && (selfClosing || VOID_ELEMENTS.has(lower)) && lower !== 'br') {
      out.push(`</${name}>`);
    }
    pos = i + 1;
  }
  return out.join('');
}

// ----------------------------------------------------------- model building

type ParsedNode = Element | Text;

function isText(node: ParsedNode): node is Text {
  return node.nodeType === 3;
}

function tagOf(node: Element): string {
  const name = node.localName.toLowerCase();
  return name.startsWith('om-') ? name.slice(3) : name;
}

function childNodes(node: Element): ParsedNode[] {
  const out: ParsedNode[] = [];
  for (const child of Array.from(node.childNodes)) {
    if (child.nodeType === 1) out.push(child as Element);
    else if (child.nodeType === 3) out.push(child as Text);
  }
  return out;
}

function plainText(node: Element): string {
  let text = '';
  for (const child of childNodes(node)) {
    if (isText(child)) text += child.data;
    else if (!DANGEROUS_TAGS.has(tagOf(child as Element))) text += plainText(child as Element);
  }
  return text;
}

function richText(node: Element): InlineNode[] {
  const out: InlineNode[] = [];
  for (const child of childNodes(node)) {
    if (isText(child)) {
      const text = child.data.replace(/\s+/g, ' ');
      if (text) out.push({ kind: 'text', text });
      continue;
    }
    const tag = tagOf(child as Element);
    if (DANGEROUS_TAGS.has(tag)) continue;
    if (tag === 'br') out.push({ kind: 'br' });
    else if (INLINE_TAGS.has(tag)) {
      out.push({ kind: 'tag', tag: tag as 'b', children: richText(child as Element) });
    } else out.push(...richText(child as Element));
  }
  return tidyInline(out);
}

/** Drop whitespace-only text around list structure and trim the edges. */
function tidyInline(nodes: InlineNode[]): InlineNode[] {
  const listy = (node: InlineNode | undefined) =>
    node?.kind === 'tag' && (node.tag === 'ul' || node.tag === 'ol' || node.tag === 'li');
  const kept = nodes.filter((node, index) => {
    if (node.kind !== 'text' || node.text.trim() !== '') return true;
    return !(listy(nodes[index - 1]) || listy(nodes[index + 1]) || index === 0 || index === nodes.length - 1);
  });
  const first = kept[0];
  if (first?.kind === 'text') kept[0] = { kind: 'text', text: first.text.trimStart() };
  const last = kept[kept.length - 1];
  if (last?.kind === 'text') kept[kept.length - 1] = { kind: 'text', text: last.text.trimEnd() };
  return kept.filter((node) => node.kind !== 'text' || node.text !== '');
}

function collect(node: Element, tag: string): Element[] {
  const found: Element[] = [];
  for (const child of childNodes(node)) {
    if (child.nodeType !== 1) continue;
    const name = tagOf(child as Element);
    if (DANGEROUS_TAGS.has(name)) continue;
    if (name === tag) found.push(child as Element);
    else found.push(...collect(child as Element, tag));
  }
  return found;
}

function slideChildren(slide: Element): Element[] {
  const found: Element[] = [];
  for (const child of childNodes(slide)) {
    if (child.nodeType !== 1) continue;
    const name = tagOf(child as Element);
    if (DANGEROUS_TAGS.has(name)) continue;
    if (ELEMENT_TAGS.has(name) || name === 'notes') found.push(child as Element);
    else if (name !== 'slide' && name !== 'deck') found.push(...slideChildren(child as Element));
  }
  return found;
}

function findDeck(root: Element): Element {
  for (const child of childNodes(root)) {
    if (child.nodeType !== 1) continue;
    const name = tagOf(child as Element);
    if (DANGEROUS_TAGS.has(name)) continue;
    if (name === 'deck') return child as Element;
    const nested = findDeck(child as Element);
    if (tagOf(nested) === 'deck') return nested;
  }
  return root;
}

class IdAllocator {
  private used = new Set<string>();
  private counters = { s: 0, e: 0 };
  constructor(private reserved: Set<string>) {}

  take(prefix: 's' | 'e', wanted: string | null): string {
    if (wanted && ID_RE.test(wanted) && !this.used.has(wanted)) {
      this.used.add(wanted);
      return wanted;
    }
    for (;;) {
      this.counters[prefix] += 1;
      const candidate = `${prefix}${this.counters[prefix]}`;
      if (!this.used.has(candidate) && !this.reserved.has(candidate)) {
        this.used.add(candidate);
        return candidate;
      }
    }
  }
}

function allIds(node: Element, into: Set<string>): Set<string> {
  const id = node.getAttribute('id');
  if (id) into.add(id);
  for (const child of childNodes(node)) if (child.nodeType === 1) allIds(child as Element, into);
  return into;
}

function readBox(node: Element, height: number): ElementBox {
  const box: ElementBox = {
    x: cleanInt(node.getAttribute('x'), 0, CANVAS_WIDTH - 1),
    y: cleanInt(node.getAttribute('y'), 0, 4000),
    w: cleanInt(node.getAttribute('w'), 1, CANVAS_WIDTH),
    h: cleanInt(node.getAttribute('h'), 1, 4000)
  };
  if (box.x !== undefined) box.x = Math.min(box.x, CANVAS_WIDTH - 1);
  if (box.y !== undefined) box.y = Math.min(box.y, height - 1);
  if (box.w !== undefined) box.w = Math.min(box.w, CANVAS_WIDTH - (box.x ?? 0));
  if (box.h !== undefined) box.h = Math.min(box.h, height - (box.y ?? 0));
  return Object.fromEntries(Object.entries(box).filter(([, value]) => value !== undefined)) as ElementBox;
}

function buildElement(
  node: Element,
  blocks: { attrs: string; body: string }[],
  ids: IdAllocator,
  height: number
): SlideElement | undefined {
  let tag = tagOf(node);
  let videoLinkHref: string | undefined;
  if (tag === 'video') {
    const raw = node.getAttribute('src') ?? '';
    if (!cleanVideoSrc(raw)) {
      videoLinkHref = cleanHttpsUrl(raw);
      if (!videoLinkHref) return undefined;
      tag = 'link';
    }
  }
  let blockIndex = -1;
  if (tag === 'block') {
    const raw = node.getAttribute(BLOCK_MARK) ?? '';
    blockIndex = /^[0-9]+$/.test(raw) ? Number(raw) : -1;
    if (blockIndex < 0 || blockIndex >= blocks.length) return undefined;
  }
  const base: ElementBase = {
    id: ids.take('e', node.getAttribute('id')),
    box: readBox(node, height),
    animate: cleanChoice(node.getAttribute('animate'), ANIMATIONS),
    step: cleanInt(node.getAttribute('step'), 0, 99) ?? 0
  };
  switch (tag) {
    case 'text':
      return {
        ...base, type: 'text',
        role: cleanChoice(node.getAttribute('role'), TEXT_ROLES),
        font: cleanFont(node.getAttribute('font')),
        size: cleanInt(node.getAttribute('size'), 8, 400),
        color: cleanColor(node.getAttribute('color')),
        align: cleanChoice(node.getAttribute('align'), ALIGNS),
        weight: cleanWeight(node.getAttribute('weight')),
        content: richText(node)
      };
    case 'image': {
      const ref = cleanEmbedRef(node.getAttribute('src'));
      if (!ref) return undefined;
      return {
        ...base, type: 'image', ref,
        alt: cleanLabel(node.getAttribute('alt') ?? ''),
        fit: cleanChoice(node.getAttribute('fit'), FITS) ?? 'cover'
      };
    }
    case 'video': {
      const src = cleanVideoSrc(node.getAttribute('src'));
      if (!src) return undefined;
      return { ...base, type: 'video', ...src, alt: cleanLabel(node.getAttribute('alt') ?? '') };
    }
    case 'shape':
      return {
        ...base, type: 'shape',
        kind: cleanChoice(node.getAttribute('kind'), SHAPE_KINDS) ?? 'rect',
        fill: cleanColor(node.getAttribute('fill')),
        stroke: cleanColor(node.getAttribute('stroke'))
      };
    case 'notepad':
      return {
        ...base, type: 'notepad', title: cleanLabel(node.getAttribute('title') ?? ''),
        text: cleanNote(plainText(node)), hidden: cleanHidden(node.getAttribute('hidden'))
      };
    case 'todo':
      return {
        ...base, type: 'todo', title: cleanLabel(node.getAttribute('title') ?? ''),
        hidden: cleanHidden(node.getAttribute('hidden')),
        items: collect(node, 'item').map((item) => ({
          done: (item.getAttribute('done') ?? '').trim().toLowerCase() === 'true',
          label: cleanLabel(plainText(item))
        }))
      };
    case 'link': {
      const href = videoLinkHref ?? cleanHttpsUrl(node.getAttribute('href'));
      if (!href) return undefined;
      const label = videoLinkHref ? cleanLabel(node.getAttribute('alt') ?? '') : cleanLabel(plainText(node));
      return { ...base, type: 'link', href, label: label || href };
    }
    case 'block': {
      const blockAttrs = new DOMParser().parseFromString(`<block ${blocks[blockIndex].attrs}>`, 'text/html')
        .getElementsByTagName('block')[0];
      return {
        ...base, type: 'block',
        title: cleanLabel(blockAttrs?.getAttribute('title') ?? ''),
        body: blocks[blockIndex].body
      };
    }
    default:
      return undefined;
  }
}

/** Cut a streaming source after the last complete `</slide>`. */
function completedSlidesOnly(stripped: string): string {
  const closes = [...stripped.matchAll(/<\/slide\s*>/gi)];
  const last = closes[closes.length - 1];
  return last ? stripped.slice(0, last.index + last[0].length) : '';
}

/**
 * Parse `slides_markup` into a typed deck model. Never throws on hostile
 * input: invalid pieces are dropped exactly as the backend normaliser does.
 */
export function parseSlidesMarkup(source: unknown, options: ParseOptions = {}): ParseResult {
  if (typeof source !== 'string' || !source.trim()) return { ok: false, reason: 'empty' };
  if (source.length > MAX_SOURCE_CHARS) return { ok: false, reason: 'too-large' };
  const normalised = source.replace(/\r\n?/g, '\n');
  const extracted = extractBlocks(normalised);
  const stripped = options.partial ? completedSlidesOnly(extracted.stripped) : extracted.stripped;
  const parsed = new DOMParser().parseFromString(prepareForHtmlParser(stripped), 'text/html');
  const deckNode = findDeck(parsed.documentElement);
  const slideNodes = collect(deckNode, 'slide').slice(0, MAX_SLIDES);
  if (slideNodes.length === 0 && !options.partial) return { ok: false, reason: 'no-slide' };

  const requestedAspect = (deckNode.getAttribute('aspect') ?? '').trim();
  const aspect = (requestedAspect in ASPECT_HEIGHTS ? requestedAspect : DEFAULT_ASPECT) as SlideAspect;
  const height = ASPECT_HEIGHTS[aspect];
  const template = (deckNode.getAttribute('template') ?? '').trim();
  const reserved = allIds(deckNode, new Set());
  const ids = new IdAllocator(reserved);

  const slides: Slide[] = slideNodes.map((slideNode) => {
    const layout = (slideNode.getAttribute('layout') ?? '').trim().toLowerCase();
    let notes = '';
    const elements: SlideElement[] = [];
    let count = 0;
    for (const child of slideChildren(slideNode)) {
      if (tagOf(child) === 'notes') {
        notes = notes || plainText(child).trim().slice(0, 5000);
        continue;
      }
      count += 1;
      if (count > MAX_ELEMENTS_PER_SLIDE) break;
      const element = buildElement(child, extracted.blocks, ids, height);
      if (element) elements.push(element);
    }
    return {
      id: ids.take('s', slideNode.getAttribute('id')),
      layout: LAYOUT_RE.test(layout) ? layout : undefined,
      transition: cleanChoice(slideNode.getAttribute('transition'), TRANSITIONS) ?? 'none',
      elements,
      notes
    };
  });

  return {
    ok: true,
    deck: {
      title: cleanLabel(deckNode.getAttribute('title') ?? '', 200),
      aspect,
      width: CANVAS_WIDTH,
      height,
      template: TEMPLATE_RE.test(template) ? template : DEFAULT_TEMPLATE,
      slides
    }
  };
}

/** Highest build step of a slide (0 when nothing builds in). */
export function maxStep(slide: Slide): number {
  return slide.elements.reduce((max, element) => Math.max(max, element.step), 0);
}

/** Plain-text rendering of inline content (copy text, thumbnails alt text). */
export function inlineToPlainText(nodes: InlineNode[]): string {
  return nodes
    .map((node) => {
      if (node.kind === 'text') return node.text;
      if (node.kind === 'br') return '\n';
      const inner = inlineToPlainText(node.children);
      return node.tag === 'li' ? `- ${inner}\n` : inner;
    })
    .join('')
    .trim();
}
