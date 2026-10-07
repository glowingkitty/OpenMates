/** Small, terminal-safe Markdown renderer for chat text. No browser or ANSI input is trusted. */
import {cells, terminalText, type TuiLine, type TuiSpan} from './tuiText.js';
import {isInteractiveQuestionPayload, type InteractiveQuestionPayload, type InteractiveQuestionAnswer} from './interactiveQuestions.js';

export type TuiResultsViewBlock = {
  type: 'results-view';
  title: string;
  embeds: string[];
  sources: string[];
  highlight: string[];
};
export type TuiMarkdownBlock = {type: 'line'; line: TuiLine} | TuiResultsViewBlock
  | {type:'question';payload:InteractiveQuestionPayload} | {type:'response';payload:InteractiveQuestionAnswer};
export type TuiMarkdownOptions = {resolveEmbedAlias?: (canonicalId: string) => string | undefined;questionBlocks?:boolean};

const ACCENT = '#80caff';
const LINK = '#85c9e8';
const CODE = '#b8b8b8';
const segmenter = new Intl.Segmenter(undefined, {granularity: 'grapheme'});
type Styled = TuiSpan;

function append(out: Styled[], value: string, style: Omit<Styled, 'text'> = {}): void {
  const text = terminalText(value);
  if (!text) return;
  const last = out.at(-1);
  if (last && last.bold === style.bold && last.color === style.color && last.background === style.background &&
    JSON.stringify(last.action) === JSON.stringify(style.action)) last.text += text;
  else out.push({text, bold: style.bold, color: style.color, background: style.background, action:style.action});
}

function closing(source: string, from: number, delimiter: string): number {
  for (let i = from; i <= source.length - delimiter.length; i++) {
    if (source[i] === '\\') { i++; continue; }
    if (source.startsWith(delimiter, i)) return i;
  }
  return -1;
}

function linkAt(source: string, start: number): {label: string; target: string; end: number} | undefined {
  if (source[start] !== '[') return;
  let depth = 1, endLabel = -1;
  for (let i = start + 1; i < source.length; i++) {
    if (source[i] === '\\') {i++; continue;}
    if (source[i] === '[') depth++;
    if (source[i] === ']' && --depth === 0) {endLabel = i; break;}
  }
  if (endLabel < 0 || source[endLabel + 1] !== '(') return;
  depth = 1;
  for (let i = endLabel + 2; i < source.length; i++) {
    if (source[i] === '\\') {i++; continue;}
    if (source[i] === '(') depth++;
    if (source[i] === ')' && --depth === 0) {
      return {label: source.slice(start + 1, endLabel), target: source.slice(endLabel + 2, i), end: i + 1};
    }
  }
}

function safeReference(value: string): boolean {return /^[\p{L}\p{N}_.:()-]+$/u.test(value) && value.length <= 300;}
function inline(source: string, options: TuiMarkdownOptions, base: Omit<Styled, 'text'> = {}): Styled[] {
  const out: Styled[] = [];
  for (let i = 0; i < source.length;) {
    if (source[i] === '\\' && i + 1 < source.length) {append(out, source[i + 1], base); i += 2; continue;}
    if (source[i] === '`') {
      const ticks = /^`+/.exec(source.slice(i))![0];
      const end = closing(source, i + ticks.length, ticks);
      if (end >= 0) {append(out, source.slice(i + ticks.length, end), {...base, color: CODE}); i = end + ticks.length; continue;}
    }
    const link = linkAt(source, i);
    if (link) {
      const target = link.target.trim();
      const label = link.label === '!' ? 'Embed' : link.label;
      const embed = target.startsWith('embed:') ? target.slice(6) : '';
      const wiki = target.startsWith('wiki:') ? target.slice(5) : '';
      let action = '';
      if (embed && safeReference(embed)) {
        const alias = options.resolveEmbedAlias?.(embed) || embed;
        action = safeReference(alias) ? `/embed ${alias}` : `/embed ${embed}`;
      } else if (wiki && safeReference(wiki)) action = `/wiki ${wiki}`;
      else if (/^https?:\/\/\S+$/i.test(target)) action = target;
      if (action) {
        const pointerAction = embed || wiki ? {kind:'command' as const,command:action} : undefined;
        append(out, label || (embed ? 'Embed' : target), {...base, color: LINK, action:pointerAction});
        if (action !== label) append(out, ` (${action})`, {color: CODE,action:pointerAction});
      } else append(out, source.slice(i, link.end), base);
      i = link.end; continue;
    }
    const delimiter = source.startsWith('**', i) || source.startsWith('__', i) ? source.slice(i, i + 2)
      : source[i] === '*' || source[i] === '_' ? source[i] : '';
    if (delimiter && source[i + delimiter.length] && !/\s/.test(source[i + delimiter.length])) {
      const end = closing(source, i + delimiter.length, delimiter);
      if (end > i + delimiter.length && !/\s/.test(source[end - 1])) {
        for (const span of inline(source.slice(i + delimiter.length, end), options, {...base, bold: delimiter.length === 2 || base.bold})) append(out, span.text, span);
        i = end + delimiter.length; continue;
      }
    }
    append(out, source[i], base); i++;
  }
  return out;
}

function wrapped(spans: Styled[], width: number, lineStyle: {bold?: boolean; color?: string} = {}): TuiLine[] {
  const rows: TuiLine[] = [];
  let parts: Styled[] = [], used = 0;
  const flush = () => {
    rows.push({text: parts.map(part => part.text).join(''), spans: parts, ...lineStyle});
    parts = []; used = 0;
  };
  for (const span of spans) for (const {segment} of segmenter.segment(span.text)) {
    const size = cells(segment);
    if (used && used + size > width) flush();
    if (size > width) {append(parts, '?', span); used += 1; continue;}
    append(parts, segment, span); used += size;
  }
  flush();
  return rows;
}

function resultView(lines: string[]): TuiResultsViewBlock {
  const fields = new Map<string, string>();
  for (const row of lines) {
    const match = /^\s*(title|embeds|sources|highlight)\s*:\s*(.*?)\s*$/i.exec(row);
    if (match && match[2]) fields.set(match[1].toLowerCase(), terminalText(match[2]));
  }
  const refs = (key: string) => [...new Set((fields.get(key) || '').split(',').map(value => value.trim()).filter(safeReference))];
  return {type: 'results-view', title: fields.get('title') || 'Results view', embeds: refs('embeds'), sources: refs('sources'), highlight: refs('highlight')};
}

/** Parse chat Markdown into fixed-cell terminal lines and typed results-view blocks. */
export function parseTuiMarkdown(content: string, width: number, options: TuiMarkdownOptions = {}): TuiMarkdownBlock[] {
  width = Math.max(1, Math.floor(width));
  const output: TuiMarkdownBlock[] = [];
  const rows = content.replace(/\r\n?/g, '\n').split('\n');
  for (let index = 0; index < rows.length; index++) {
    const row = rows[index];
    const fence = /^\s{0,3}(`{3,}|~{3,})([^`~]*)$/.exec(row);
    if (fence) {
      const language = fence[2].trim().split(/\s+/, 1)[0].toLowerCase();
      const body: string[] = [];
      let next = index + 1;
      const close = new RegExp(`^\\s{0,3}${fence[1][0]}{${fence[1].length},}\\s*$`);
      while (next < rows.length && !close.test(rows[next])) body.push(rows[next++]);
      if(next<rows.length&&(language==='interactive_question'||language==='interactive_response')){
        try{
          const payload:unknown=JSON.parse(body.join('\n'));
          if(language==='interactive_question'&&options.questionBlocks!==false&&isInteractiveQuestionPayload(payload)){
            output.push({type:'question',payload});index=next;continue;
          }
          if(language==='interactive_response'&&payload&&typeof payload==='object'&&!Array.isArray(payload)&&typeof (payload as Record<string,unknown>).id==='string'){
            output.push({type:'response',payload:payload as InteractiveQuestionAnswer});index=next;continue;
          }
        }catch{/* Malformed protocol remains readable as a literal code block. */}
      }
      if (language === 'embeds_results_view' || language === 'embeds_map_view') {
        output.push(resultView(body)); index = next; continue;
      }
      // Ordinary and malformed code fences stay literal, including their delimiters.
      for (const line of rows.slice(index, Math.min(next + 1, rows.length)))
        output.push(...wrapped([{text: terminalText(line), color: CODE}], width).map(line => ({type: 'line' as const, line})));
      index = next; continue;
    }
    const heading = /^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/.exec(row);
    if (heading && output.length && output.at(-1)?.type === 'line' && (output.at(-1) as {line:TuiLine}).line !== '') {
      const previous = output.at(-1) as {line:TuiLine};
      if ((typeof previous.line === 'string' ? previous.line : previous.line.text) !== '') output.push({type:'line',line:''});
    }
    const source = heading ? heading[1] : row;
    const spans = inline(source, options, heading ? {bold:true,color:ACCENT} : {});
    output.push(...wrapped(spans, width, heading ? {bold:true,color:ACCENT} : {}).map(line => ({type:'line' as const,line})));
  }
  return output;
}

export function renderTuiMarkdownLines(content: string, width: number, options: TuiMarkdownOptions = {}): TuiLine[] {
  return parseTuiMarkdown(content, width, options).flatMap(block => block.type === 'line' ? [block.line] : []);
}
