// frontend/packages/ui/src/components/embeds/file/fileEmbedText.ts
//
// Plain-text representation of the generic, non-executable File embed.
// Export and clipboard surfaces receive metadata only and never interpret file
// contents or include signed download URLs.

import { str } from '../../../data/embedTextRenderers';

export function renderFile(content: Record<string, unknown>): string {
  const path = str(content.normalized_path) ?? str(content.path) ?? str(content.filename) ?? 'File';
  const metadata = [str(content.mime_type), typeof content.size_bytes === 'number' ? `${content.size_bytes} bytes` : null]
    .filter(Boolean)
    .join(' · ');
  return [`**${path}**`, metadata].filter(Boolean).join('\n');
}
