/** Text-only renderer for generated music embeds. */

import { str, trunc } from '../../../data/embedTextRenderers';

export function renderMusicGenerate(c: Record<string, unknown>): string {
  const prompt = str(c.prompt) ?? '';
  const mode = str(c.mode) ?? '';
  const model = str(c.model) ?? '';
  const lines = ['**Generated Music**'];
  if (mode) lines.push(`Mode: ${mode}`);
  if (model) lines.push(`Model: ${model}`);
  if (prompt) lines.push(trunc(prompt, 200));
  return lines.join('\n');
}
