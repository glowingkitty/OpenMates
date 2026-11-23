/**
 * Sealed Project-file privacy mappings of the npm CLI (the explicit fallback
 * CLI); the web app and the native CLI keep them in the Rust core. Moved
 * unchanged from ui/src/services/projectFilePrivacyStorage.ts.
 */
import { ProjectFilePrivacy, type ProjectFilePrivacyOptions } from "../../ui/src/services/projectFilePrivacy.js";
import type { PIIMappingGeneric } from "../../ui/src/components/enter_message/services/piiDetectionService.js";

export async function loadProjectFilePrivacy(options: {
  chatId: string;
  projectId: string;
  key: Uint8Array;
  mappings: PIIMappingGeneric[];
  detection?: ProjectFilePrivacyOptions["detection"];
  enabled?: boolean;
  detectEnhanced?: ProjectFilePrivacyOptions["detectEnhanced"];
  read: () => Promise<string | null>;
  write: (ciphertext: string) => Promise<void>;
  encrypt: (text: string, key: Uint8Array) => Promise<string>;
  decrypt: (text: string, key: Uint8Array) => Promise<string | null>;
}): Promise<ProjectFilePrivacy> {
  const ciphertext = await options.read();
  let mappings: PIIMappingGeneric[] = [];
  if (ciphertext) {
    const plaintext = await options.decrypt(ciphertext, options.key);
    try {
      const saved = JSON.parse(plaintext ?? "null");
      if (saved?.chat_id !== options.chatId || saved?.project_id !== options.projectId || !Array.isArray(saved?.mappings)) throw new Error();
      mappings = saved.mappings;
    } catch { throw Object.assign(new Error(), { code: "pii_mapping_unavailable" }); }
  }
  return new ProjectFilePrivacy({
    detectEnhanced: options.detectEnhanced,
    mappings: [...mappings, ...options.mappings], detection: options.detection, enabled: options.enabled,
    save: async (current) => {
      const plaintext = JSON.stringify({ chat_id: options.chatId, project_id: options.projectId, mappings: current });
      if (new TextEncoder().encode(plaintext).byteLength > 2 * 1024 * 1024) throw Object.assign(new Error(), { code: "pii_mapping_limit" });
      await options.write(await options.encrypt(plaintext, options.key));
    },
  });
}
