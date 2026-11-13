/**
 * Reads the `pii_mappings` the core stored inside a decrypted
 * `app_settings_memories_response` system message (decision D-5): placeholders
 * of anonymized Memory bodies, so answers echoing them restore. Read only.
 */
import type { PIIMapping } from '../../../types/chat';

export function memoryResponseMappings(content: unknown): PIIMapping[] {
  if (typeof content !== 'string' || !content.includes('app_settings_memories_response')) return [];
  try {
    const parsed = JSON.parse(content) as { type?: unknown; pii_mappings?: unknown };
    return parsed.type === 'app_settings_memories_response' && Array.isArray(parsed.pii_mappings)
      ? parsed.pii_mappings as PIIMapping[] : [];
  } catch {
    return [];
  }
}
