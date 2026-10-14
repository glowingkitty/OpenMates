import MarkdownIt from 'markdown-it';

const markdownParser = new MarkdownIt();

/** Preserve each authored blank line as a TipTap paragraph outside code. */
export function preserveUserBlankLines(markdown: string): string {
  markdown = markdown.replace(/\r\n?/g, '\n');
  // Use Markdown's own block ranges so nested, tilde, long and indented code
  // retains its original whitespace without internal paragraph markers. Keep
  // all lists/quotes intact too: a top-level marker would split their structure.
  const blocks = markdownParser.parse(markdown, {});
  const codeRanges = blocks
    .filter(token => (token.type === 'fence' || token.type === 'code_block') && token.map)
    .map(token => token.map!);
  const lines = markdown.split('\n');
  const protectedRanges = codeRanges.concat(blocks
    .filter(token => token.map && ['bullet_list_open', 'ordered_list_open', 'blockquote_open'].includes(token.type))
    .map((token): [number, number] => {
      const [start, rangeEnd] = token.map!;
      let end = rangeEnd;
      while (end > start && !lines[end - 1].trim()) end--;
      return [start, end];
    }));
  const separators = /\n(?:[ \t]*\n)+/g;
  let output = '';
  let cursor = 0;
  let lineIndex = 0;

  for (const match of markdown.matchAll(separators)) {
    const section = markdown.slice(cursor, match.index);
    output += section;
    lineIndex += (section.match(/\n/g) ?? []).length;
    const separator = match[0];
    const newlineCount = (separator.match(/\n/g) ?? []).length;
    const firstBlankLine = lineIndex + 1;
    const lastBlankLine = lineIndex + newlineCount - 1;
    const insideCode = protectedRanges.some(([start, end]) => firstBlankLine < end && lastBlankLine >= start);
    output += insideCode
      ? separator
      : `\n\n${Array.from({ length: newlineCount - 1 }, () => '<!-- EMPTY_PARAGRAPH -->').join('\n\n')}\n\n`;
    lineIndex += newlineCount;
    cursor = (match.index ?? 0) + separator.length;
  }

  return output + markdown.slice(cursor);
}
