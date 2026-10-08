/** Request terminal clipboard delivery. OSC 52 has no portable acknowledgement. */
export function requestTerminalClipboard(text: string, output: Pick<NodeJS.WriteStream, 'write'|'isTTY'> = process.stdout): boolean {
  if (!text || !output.isTTY || process.env.TERM === 'dumb') return false;
  // Keep the escape sequence bounded; terminals often silently discard larger OSC 52 payloads.
  const encoded = Buffer.from(text, 'utf8').toString('base64');
  if (encoded.length > 100_000) return false;
  output.write(`\x1b]52;c;${encoded}\x07`);
  return false;
}
