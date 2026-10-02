/** Local ciphertext cache; no server receives Project-file PII originals. */
import { ProjectFilePrivacy, type ProjectFilePrivacyOptions } from "./projectFilePrivacy";
import type { PIIMappingGeneric } from "../components/enter_message/services/piiDetectionService";

export const PROJECT_FILE_PRIVACY_PREFIX = "openmates_project_file_privacy:";

export async function loadProjectFilePrivacy(options: {
  chatId: string;
  projectId: string;
  key: Uint8Array;
  mappings: PIIMappingGeneric[];
  detection?: ProjectFilePrivacyOptions["detection"];
  enabled?: boolean;
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
    mappings: [...mappings, ...options.mappings], detection: options.detection, enabled: options.enabled,
    save: async (current) => {
      const plaintext = JSON.stringify({ chat_id: options.chatId, project_id: options.projectId, mappings: current });
      if (new TextEncoder().encode(plaintext).byteLength > 2 * 1024 * 1024) throw Object.assign(new Error(), { code: "pii_mapping_limit" });
      await options.write(await options.encrypt(plaintext, options.key));
    },
  });
}

export function clearProjectFilePrivacyStorage(): void {
  if (typeof localStorage === "undefined") return;
  for (const key of Object.keys(localStorage)) {
    if (key.startsWith(PROJECT_FILE_PRIVACY_PREFIX)) localStorage.removeItem(key);
  }
}
