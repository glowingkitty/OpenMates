/** Browser-only validation and composition helpers for canonical HTML/SVG diagrams. */
import { LEXEND_FONT_FACE } from './diagramHtmlFont';
export interface DiagramHtmlContent {
  title: string;
  diagramKind: string;
  htmlSource: string;
  renderWidth: number;
  renderHeight: number;
  schemaVersion: number;
  versionNumber: number;
  status: 'processing' | 'finished' | 'error' | 'cancelled';
}

const forbiddenTags = new Set(['script', 'iframe', 'frame', 'frameset', 'object', 'embed', 'applet', 'foreignobject', 'form', 'input', 'button', 'textarea', 'select', 'base', 'link', 'img', 'image', 'video', 'audio', 'source', 'track', 'template', 'portal', 'animate', 'animatemotion', 'animatetransform', 'set', 'discard', 'feimage', 'math', 'noscript']);
const externalValue = /(?:https?:|javascript:|vbscript:|file:|blob:|data:|\/\/)/i;
const unsafeCssDirective = /@\s*(?:import|namespace|document)\b|image-set\s*\(|expression\s*\(|-moz-binding\s*:|behavior\s*:/i;
const cssUrl = /url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*))\s*\)/gi;

function validateCss(value: string): void {
  const css = value.replace(/\/\*[\s\S]*?\*\//g, '');
  // CSS escapes can spell executable directives or external URLs without the
  // literal bytes below. Generated diagrams do not need escaped CSS tokens.
  if (css.includes('\\') || unsafeCssDirective.test(css)) throw new Error('Unsafe diagram CSS');
  const withoutUrls = [...css];
  for (const match of css.matchAll(cssUrl)) {
    const target = (match[1] ?? match[2] ?? match[3] ?? '').trim();
    if (!/^#[a-z_][a-z0-9_.:-]{0,119}$/i.test(target)) {
      const font = /^data:font\/woff2;base64,([A-Za-z0-9+/]+={0,2})$/i.exec(target);
      const faceStart = css.toLowerCase().lastIndexOf('@font-face', match.index);
      const previousClose = css.lastIndexOf('}', match.index);
      const faceOpen = faceStart >= 0 ? css.indexOf('{', faceStart + 10) : -1;
      if (!font || faceStart <= previousClose || faceOpen < 0 || faceOpen >= match.index || font[1].length > 350_000) throw new Error('External diagram resources are not allowed');
      let decoded: string;
      try { decoded = atob(font[1]); } catch { throw new Error('Invalid diagram font'); }
      if (!decoded.startsWith('wOF2') || decoded.length > 256 * 1024) throw new Error('Invalid diagram font');
    }
    withoutUrls.fill(' ', match.index, match.index + match[0].length);
  }
  if (/url\s*\(/i.test(withoutUrls.join('')) || externalValue.test(withoutUrls.join(''))) throw new Error('External diagram resources are not allowed');
}

export function normalizeDiagramHtmlContent(value: Record<string, unknown>): DiagramHtmlContent {
  const status = value.status;
  return {
    title: typeof value.title === 'string' && value.title ? value.title : 'Diagram',
    diagramKind: typeof value.diagram_kind === 'string' && value.diagram_kind ? value.diagram_kind : 'diagram',
    htmlSource: typeof value.html_source === 'string' ? value.html_source : '',
    renderWidth: dimension(value.render_width, 1200),
    renderHeight: dimension(value.render_height, 900),
    schemaVersion: value.schema_version === 1 ? 1 : 1,
    versionNumber: typeof value.version_number === 'number' && value.version_number >= 1 ? value.version_number : 1,
    status: status === 'finished' || status === 'error' || status === 'cancelled' ? status : 'processing'
  };
}

function dimension(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 200 && value <= 4096 ? value : fallback;
}

/** Reject active/external content before srcdoc; the iframe CSP is a second boundary. */
export function validateDiagramHtml(source: string): Document {
  if (!source || new TextEncoder().encode(source).length > 1024 * 1024 || /<!ENTITY|<!DOCTYPE[^>]*\[/i.test(source)) throw new Error('Invalid diagram source');
  if (!/^\s*(?:<!doctype html>\s*)?<html\b/i.test(source) || !/<head\b[^>]*>[\s\S]*?<\/head\s*>/i.test(source) || !/<body\b[^>]*>[\s\S]*?<\/body\s*>/i.test(source) || !/<\/html\s*>\s*$/i.test(source)) throw new Error('Complete HTML diagram document required');
  const document = new DOMParser().parseFromString(source, 'text/html');
  if (!document.title.trim() || document.title.trim().length > 160) throw new Error('Diagram title is missing');
  const primaryDiagrams = document.querySelectorAll('svg[data-om-diagram]');
  if (primaryDiagrams.length !== 1 || !primaryDiagrams[0].hasAttribute('viewBox')) throw new Error('A single primary diagram SVG is required');
  const components = new Set<string>();
  const edges: Array<[string, string]> = [];
  for (const element of Array.from(document.querySelectorAll('*'))) {
    const tag = element.localName.toLowerCase();
    if (forbiddenTags.has(tag) && !(tag === 'meta' && (element.hasAttribute('charset') || element.getAttribute('name')?.toLowerCase() === 'viewport'))) {
      throw new Error(`Unsupported diagram element: ${tag}`);
    }
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      const value = attribute.value.trim();
      if (name.startsWith('on') || ['srcdoc', 'http-equiv', 'src', 'srcset', 'poster', 'data', 'action', 'formaction', 'background', 'cite', 'longdesc', 'profile', 'manifest', 'codebase', 'archive', 'usemap'].includes(name)) throw new Error('Active diagram attributes are not allowed');
      if (name.startsWith('data-om-') && value.length > 120) throw new Error('Diagram edit metadata is too long');
      if (['src', 'srcset', 'href', 'xlink:href', 'action', 'formaction', 'poster'].includes(name) && (externalValue.test(value) || (!value.startsWith('#') && value !== ''))) {
        throw new Error('External diagram resources are not allowed');
      }
      if (name === 'href' || name === 'xlink:href') {
        if (!/^#[a-z_][a-z0-9_.:-]{0,119}$/i.test(value)) throw new Error('External diagram links are not allowed');
      }
      if (name === 'style' || /url\s*\(/i.test(value)) validateCss(value);
    }
    if (tag === 'style') {
      validateCss(element.textContent ?? '');
    }
    if (tag === 'g') {
      const componentId = element.getAttribute('data-om-component');
      if (componentId) {
        if (components.has(componentId)) throw new Error('Duplicate diagram component');
        components.add(componentId);
      }
      if (element.hasAttribute('data-om-edge')) {
        const from = element.getAttribute('data-om-from') || '';
        const to = element.getAttribute('data-om-to') || '';
        const fromSide = element.getAttribute('data-om-from-side') || '';
        const toSide = element.getAttribute('data-om-to-side') || '';
        if (!from || !to || !['left', 'right', 'top', 'bottom'].includes(fromSide) || !['left', 'right', 'top', 'bottom'].includes(toSide)) throw new Error('Invalid diagram edge');
        edges.push([from, to]);
      }
    }
    if (tag === 'path' && element.hasAttribute('data-om-path')) {
      const path = element.getAttribute('d') || '';
      if (!/^[MmLlHhVvCcSsQqTtAaZz0-9eE.,+\-\s]+$/.test(path) || !/^\s*[Mm]/.test(path)) throw new Error('Invalid editable edge path');
    }
  }
  if (edges.some(([from, to]) => !components.has(from) || !components.has(to))) throw new Error('Diagram edge references a missing component');
  return document;
}

export function buildDiagramSrcdoc(source: string, trustedRuntime?: string): string {
  const document = validateDiagramHtml(source);
  return buildValidatedDiagramSrcdoc(document, trustedRuntime);
}

/** The wrapper color is visual metadata; the canonical HTML is never rewritten. */
export function diagramBackgroundColor(source: string): string {
  return backgroundColorFromDocument(validateDiagramHtml(source));
}

export function buildDiagramFrame(source: string, trustedRuntime?: string): { srcdoc: string; backgroundColor: string } {
  const document = validateDiagramHtml(source);
  const backgroundColor = backgroundColorFromDocument(document);
  return { srcdoc: buildValidatedDiagramSrcdoc(document, trustedRuntime), backgroundColor };
}

function isOpaqueLiteralColor(document: Document, value: string): boolean {
  // Only a single resolved color token is allowed. The detached style parser
  // checks actual browser support without adding markup to the document.
  const literal = /^(?:#[0-9a-f]{3}|#[0-9a-f]{6}|[a-z][a-z-]*|(?:rgb|hsl|lab|lch|oklab|oklch|color)\([a-z0-9.%+\-,\s]+\))$/i;
  if (!literal.test(value) || /^(?:transparent|currentcolor|inherit|initial|unset|revert|revert-layer)$/i.test(value)) return false;
  const probe = document.createElement('span');
  probe.style.backgroundColor = value;
  return probe.style.backgroundColor !== '';
}

function backgroundColorFromDocument(document: Document): string {
  const declared = document.documentElement.getAttribute('data-om-background')?.trim() ?? '';
  if (isOpaqueLiteralColor(document, declared)) return declared;

  // Older exports have a body background derived from :root variables. Read
  // only literal declarations from validated CSS; never inspect the iframe.
  const css = Array.from(document.head.querySelectorAll('style')).map((style) => style.textContent ?? '').join('\n').replace(/\/\*[\s\S]*?\*\//g, '');
  const variables = new Map<string, string>();
  let background = '';
  for (const rule of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selector = rule[1].trim();
    if (!selector.split(',').some((part) => [':root', 'html', 'body'].includes(part.trim()))) continue;
    for (const declaration of rule[2].split(';')) {
      const colon = declaration.indexOf(':');
      if (colon < 0) continue;
      const property = declaration.slice(0, colon).trim().toLowerCase();
      const value = declaration.slice(colon + 1).trim().replace(/\s*!important\s*$/i, '');
      if (property.startsWith('--')) variables.set(property, value);
      if ((selector.includes('body') || !background) && (property === 'background' || property === 'background-color')) background = value;
    }
  }
  const inline = document.body.style.backgroundColor || document.body.style.background;
  if (inline) background = inline;
  for (let depth = 0; depth < 4; depth++) {
    const variable = /^var\(\s*(--[a-z0-9-]+)\s*\)$/i.exec(background);
    if (!variable) break;
    background = variables.get(variable[1].toLowerCase()) ?? '';
  }
  return isOpaqueLiteralColor(document, background) ? background : '#ffffff';
}

function buildValidatedDiagramSrcdoc(document: Document, trustedRuntime?: string): string {
  const nonce = crypto.randomUUID().replace(/-/g, '');
  const csp = document.createElement('meta');
  csp.setAttribute('http-equiv', 'Content-Security-Policy');
  csp.setAttribute('content', `default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'; script-src 'nonce-${nonce}'; connect-src 'none'; form-action 'none'; base-uri 'none'`);
  document.head.prepend(csp);
  const font = document.createElement('style');
  font.setAttribute('data-om-runtime', 'true');
  font.textContent = LEXEND_FONT_FACE;
  document.head.append(font);
  if (trustedRuntime) {
    const script = document.createElement('script');
    script.setAttribute('nonce', nonce);
    script.setAttribute('data-om-runtime', 'true');
    script.textContent = trustedRuntime.replace(/<\/script/gi, '<\\/script');
    document.body.append(script);
  }
  return `<!DOCTYPE html>\n${document.documentElement.outerHTML}`;
}

export function renderDiagramText(value: Record<string, unknown>, full = false): string {
  const content = normalizeDiagramHtmlContent(value);
  const lines = [`**Diagram** — ${content.title}`, content.diagramKind, `status: ${content.status}`];
  if (full && content.htmlSource) lines.push('', '```html', content.htmlSource, '```');
  return lines.join('\n');
}
