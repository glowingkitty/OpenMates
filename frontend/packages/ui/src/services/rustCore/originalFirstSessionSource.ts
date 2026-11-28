/** Fixed provider boundary. An unpackaged build resolves the physical stub. */
export { readOriginalFirstSessionCheck, takeOriginalFirstSessionWorker } from './firstSessionPlatform';

export interface OriginalFirstSessionInput {
  endpoint: string;
  appOrigin: string;
  sessionId: string;
  deviceSignals: Record<string, string | null>;
  signal: AbortSignal;
  deadlineEpochMs: number;
  isCurrent(): boolean;
}

export interface OriginalFirstSessionData {
  httpStatus: number | null;
  data: import('../../stores/authTypes').SessionCheckResult | null;
}

export interface OriginalFirstSessionScope {
  readonly owner: string;
  readonly sessionId: string;
  readonly scope: string;
  readonly loginGeneration: number;
}

/** A recorded definitive server denial applies only to that original scope. */
export function assertLocalReadAfterFirstSession(
  attempt: (OriginalFirstSessionScope & { failure: 'session_expired' | 'unavailable' }) | null,
  current: OriginalFirstSessionScope,
): void {
  if (attempt?.failure === 'session_expired' && attempt.owner === current.owner &&
      attempt.sessionId === current.sessionId && attempt.scope === current.scope &&
      attempt.loginGeneration === current.loginGeneration) throw new Error('session_expired');
}

export interface OriginalFirstSessionWorker {
  host: import('./workerHost').BrowserCoreWorkerHost;
  close(): void;
  confirmHandover(): void;
  witness: import('./secondDeviceSavedChatSession').ExistingSavedChatProfile;
}
