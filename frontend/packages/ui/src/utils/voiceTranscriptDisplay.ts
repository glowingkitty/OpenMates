/** Hide the exact legacy status suffix without rewriting saved ciphertext. */
export function voiceTranscriptDisplayText(content: string, role: string): string {
  if (role !== "assistant") return content;
  return content.replace(/\r?\n\s*\r?\n_\(\(?(?:interrupted|unterbrochen)\)?\)_\s*$/i, "");
}
