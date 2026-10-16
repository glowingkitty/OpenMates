/** Only this tab's uncommitted initial send suppresses remote history. */
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';
import { registerWorkspaceCacheClear } from './workspaceCacheLifecycle';

export class InitialChatHistoryGate {
  private entries = new Map<string, { scope: string; messageId: string; turnId: string | null; repair?: () => void }>();
  constructor(private scope: () => string | null) {}
  register(chatId: string, messageId: string): void {
    const scope = this.scope();
    if (scope && !this.pending(chatId)) this.entries.set(chatId, { scope, messageId, turnId: null });
  }
  pending(chatId: string): boolean {
    const entry = this.entries.get(chatId);
    if (entry && entry.scope !== this.scope()) this.entries.delete(chatId);
    return this.entries.has(chatId);
  }
  bind(chatId: string, messageId: string, turnId: string): void {
    if (!this.pending(chatId)) return;
    const entry = this.entries.get(chatId)!;
    // Rebinding is an explicit same-message retry, never an acknowledgement.
    // Only the latest bound attempt can release the owned gate.
    if (entry.messageId === messageId) entry.turnId = turnId;
  }
  defer(chatId: string, repair: () => void): boolean {
    if (!this.pending(chatId)) return false;
    this.entries.get(chatId)!.repair = repair;
    return true;
  }
  acknowledge(chatId: string, messageId: string, turnId: string, scope: string | null): boolean {
    if (!this.pending(chatId)) return false;
    const entry = this.entries.get(chatId)!;
    if (!scope || entry.scope !== scope || entry.messageId !== messageId || entry.turnId !== turnId) return false;
    this.entries.delete(chatId);
    if (entry.repair) queueMicrotask(() => { if (this.scope() === scope) entry.repair?.(); });
    return true;
  }
  clear(): void { this.entries.clear(); }
}
export const initialChatHistoryGate = new InitialChatHistoryGate(getWorkspaceCacheIdentity);
registerWorkspaceCacheClear(() => initialChatHistoryGate.clear());
