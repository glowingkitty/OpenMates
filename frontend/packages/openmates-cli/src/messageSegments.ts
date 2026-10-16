/** Shared, pure parser for inline embed references in assistant messages. */
export type MessageSegment =
  | { type: "text"; value: string; rawLength: number }
  | { type: "embed"; value: string; meta?: Record<string, unknown>; rawLength: number };

/** Focus/tool continuations replace the stream prefix; their text starts anew. */
export function streamingTextDelta(previous: string, current: string): string {
  if (current.startsWith(previous)) return current.slice(previous.length);
  // Final source validation can remove/change link destinations while keeping
  // their labels. Compare that visible prose without reprinting it, and map a
  // genuinely appended suffix back to its original Markdown offsets.
  const before = canonicalStreamText(previous);
  const after = canonicalStreamText(current);
  if (after.text.startsWith(before.text)) {
    return current.slice(after.boundaries[before.text.length]);
  }
  return current; // A different focus/tool continuation starts a new phase.
}

function canonicalStreamText(raw: string): { text: string; boundaries: number[] } {
  let text = "";
  const boundaries = [0];
  const append = (value: string, offset: number) => {
    for (let index = 0; index < value.length; index++) {
      text += value[index];
      boundaries.push(offset + index + 1);
    }
  };
  let end = 0;
  // Complete inline links only; leave arbitrary prose, whitespace and partial
  // Markdown untouched. One balanced URL-parenthesis level is supported.
  for (const match of raw.matchAll(/(?<!!)\[([^\]\n]+)\]\((?:[^()\\\n]|\\.|\([^()\n]*\))*\)/g)) {
    const start = match.index!;
    append(raw.slice(end, start), end);
    append(match[1], start + 1);
    end = start + match[0].length;
    boundaries[boundaries.length - 1] = end;
  }
  append(raw.slice(end), end);
  return { text, boundaries };
}

export function parseMessageSegments(content: string, options: {preserveCodeFences?: boolean} = {}): MessageSegment[] {
  const segments: MessageSegment[] = [];
  const rows = content.match(/[^\n]*(?:\n|$)/g)?.filter(Boolean) ?? [];
  const offsets: number[] = [];
  let position = 0;
  for (const row of rows) {offsets.push(position);position += row.length;}
  let last = 0;
  for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
    const fence = /^ {0,3}(`{3,}|~{3,})([^`~]*)$/.exec(rows[rowIndex].replace(/\r?\n$/, ''));
    if (!fence) continue;
    const close = new RegExp(`^ {0,3}${fence[1][0]}{${fence[1].length},}[ \\t]*$`);
    let end = rowIndex + 1;
    while (end < rows.length && !close.test(rows[end].replace(/\r?\n$/, ''))) end++;
    if (end === rows.length) break;
    const language = fence[2].trim();
    const index = offsets[rowIndex], finish = offsets[end] + rows[end].replace(/\r?\n$/, '').length;
    const body = rows.slice(rowIndex + 1,end).join('');
    rowIndex = end; // Never scan examples inside an enclosing code fence as references.
    if (language !== 'json_embed' && language !== 'json') continue;
    const raw = content.slice(index,finish);
    if (index > last) {
      const value = content.slice(last, index);
      segments.push({type: "text", value, rawLength: value.length});
    }
    let reference = false;
    try {
      const parsed: unknown = JSON.parse(body.trim());
      if (parsed && typeof parsed === "object" && "embed_id" in parsed && typeof parsed.embed_id === "string" && parsed.embed_id) {
        segments.push({type: "embed", value: parsed.embed_id, meta: parsed as Record<string, unknown>, rawLength: raw.length});
        reference = true;
      }
    } catch { /* Ordinary or malformed code stays visible when requested. */ }
    if (!reference && options.preserveCodeFences) segments.push({type: "text", value: raw, rawLength: raw.length});
    last = finish;
  }
  if (last < content.length) {
    const value = content.slice(last);
    segments.push({type: "text", value, rawLength: value.length});
  }
  return segments;
}
