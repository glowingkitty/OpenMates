/** Local ciphertext cache of the core-sealed Project-file privacy mappings; no server receives PII originals. */
export const PROJECT_FILE_PRIVACY_PREFIX = "openmates_project_file_privacy:";

export function clearProjectFilePrivacyStorage(): void {
  if (typeof localStorage === "undefined") return;
  for (const key of Object.keys(localStorage)) {
    if (key.startsWith(PROJECT_FILE_PRIVACY_PREFIX)) localStorage.removeItem(key);
  }
}
