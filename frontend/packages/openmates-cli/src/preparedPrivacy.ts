/** RAM-only privacy preparation. A cached generation is never a send receipt. */
import { compileCliPrivacy, type CompiledCliPrivacy } from './privacyScan.js';
import type { DecryptedMemoryEntry } from './client.js';

export const PREPARED_PRIVACY_IDLE_MS = 2 * 60 * 60_000;
export type PreparedPrivacyBundle = {
  ownerKey: string;
  preferencesKey: string;
  generation: string;
  memories: DecryptedMemoryEntry[];
  privacy: CompiledCliPrivacy;
};

/** The timer releases decrypted values even when there is no further UI activity. */
export class PreparedPrivacyCache {
  private value: PreparedPrivacyBundle | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private lastUsedAt = 0;
  private readonly now: () => number;
  constructor(now: () => number = Date.now) { this.now = now; }

  set(ownerKey: string, preferencesKey: string, generation: string | null, memories: DecryptedMemoryEntry[]): void {
    this.clear();
    if (!generation) return;
    this.value = { ownerKey, preferencesKey, generation, memories, privacy: compileCliPrivacy(memories) };
    this.touch();
  }

  get(ownerKey: string, preferencesKey: string): PreparedPrivacyBundle | null {
    if (!this.value) return null;
    if (this.value.ownerKey !== ownerKey || this.value.preferencesKey !== preferencesKey
        || this.now() - this.lastUsedAt >= PREPARED_PRIVACY_IDLE_MS) {
      this.clear(); return null;
    }
    this.touch();
    return this.value;
  }

  clear(): void {
    this.value = null;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  private touch(): void {
    this.lastUsedAt = this.now();
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.clear(), PREPARED_PRIVACY_IDLE_MS);
    this.timer.unref?.();
  }
}
