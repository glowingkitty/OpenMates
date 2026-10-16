/** Reconstruct the visible text rows from the CLI's synchronized ANSI paints. */
function terminalRowsAtCheckpoint(transcript: string): string[] {
  const source = transcript.slice(Math.max(0, transcript.lastIndexOf('\x1b[?1049h')));
  // eslint-disable-next-line no-control-regex -- Match synchronized ANSI paint boundaries.
  const frames = source.matchAll(/\x1b\[\?2026h([\s\S]*?)\x1b\[\?2026l/g);
  const rows: string[] = [];
  let found = false;
  let previousEnd = 0;
  for (const frame of frames) {
    found = true;
    if (source.slice(previousEnd, frame.index).includes('\x1b[2J')) rows.length = 0;
    applyPaint(frame[1], rows);
    previousEnd = frame.index + frame[0].length;
  }
  if (!found) throw new Error('No complete terminal frame at checkpoint');
  return Array.from({length: rows.length}, (_, index) => plain(rows[index] ?? ''));
}

function applyPaint(paint: string, rows: string[]): void {
  // Only row-addressed clears and erase-to-end alter text. SGR styling stays
  // with each row until the screen is reconstructed, then is stripped once.
  // eslint-disable-next-line no-control-regex -- Parse intentional ANSI control sequences.
  const controls = /\x1b\[[0-?]*[ -/]*[@-~]/g;
  let offset = 0;
  let row = 0;
  let writing = false;
  let content = '';
  const finishRow = () => {
    if (writing && row > 0) rows[row - 1] = content;
    writing = false;
    content = '';
  };
  for (const match of paint.matchAll(controls)) {
    const code = match[0];
    if (writing) content += paint.slice(offset, match.index);
    // eslint-disable-next-line no-control-regex -- Match ANSI cursor row addresses.
    const address = /^\x1b\[(\d+);(\d+)H$/.exec(code);
    if (address) {
      finishRow();
      row = Number(address[1]);
      if (Number(address[2]) !== 1) row = 0;
    } else if (code === '\x1b[2K' && row > 0) {
      writing = true;
      content = '';
    } else if (code === '\x1b[J' && row > 0) {
      finishRow();
      rows.length = row - 1;
      row = 0;
    } else if (code === '\x1b[2J') {
      finishRow();
      rows.length = 0;
      row = 0;
    } else if (writing) {
      content += code;
    }
    offset = match.index + code.length;
  }
  if (writing) content += paint.slice(offset);
  finishRow();
}

function plain(text: string): string {
  // eslint-disable-next-line no-control-regex -- Terminal control bytes are intentional.
  return text.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '').replace(/\r/g, '');
}

module.exports = {terminalRowsAtCheckpoint};
