// frontend/packages/ui/src/services/chatSyncPhasedRetry.ts
// Silent bounded retry for the server's typed `phased_sync_retryable_error`
// (CMS timeout / deletion-fence lookup unavailable during startup sync).
// Already-delivered Phase 1 data and the cached chat list stay in IndexedDB and
// are never cleared; only the request is repeated. After the retry budget is
// spent we show one non-alarming message and unblock the sync indicator.
import type { ChatSynchronizationService } from "./chatSyncService";
import { phasedSyncState } from "../stores/phasedSyncStateStore";
import { notificationStore } from "../stores/notificationStore";

export interface PhasedSyncRetryablePayload {
  code?: string;
  retryable?: boolean;
  retry_after_ms?: number;
  sync_phase?: string;
  team_id?: string | null;
  context_epoch?: number;
}

export const PHASED_SYNC_RETRY_MAX_ATTEMPTS = 5;
const DEFAULT_RETRY_AFTER_MS = 3000;
const MAX_BACKOFF_MS = 30000;
const RETRY_DEDUPE_KEY = "phased-sync-degraded";

let attempt = 0;
let timer: ReturnType<typeof setTimeout> | null = null;
/** Opt-in shared Rust core build: the decision runs in the shared Worker `sync` unit. */
// Measurement-only opt-out (`openmates_rust_core_sync` = 'ts'), read once per page load.
const RUST_SYNC_BUILD: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === "1"
  && !(typeof localStorage !== "undefined" && localStorage.getItem("openmates_rust_core_sync") === "ts");
function rustSyncPolicy() {
  return import("./rustCore/sync/rustChatSyncPolicy");
}
let retryGeneration = 0;
/** Live view of this module's retry state for the flag-on adapter. */
const rustRetryState = {
  get attempt() { return attempt; },
  set attempt(value: number) { attempt = value; },
  get timer() { return timer; },
  set timer(value: ReturnType<typeof setTimeout> | null) { timer = value; },
  get generation() { return retryGeneration; },
};

export function computePhasedSyncRetryDelayMs(attemptNumber: number, retryAfterMs?: number): number {
  const base = Number.isFinite(retryAfterMs) && (retryAfterMs as number) > 0
    ? (retryAfterMs as number)
    : DEFAULT_RETRY_AFTER_MS;
  return Math.min(base * 2 ** Math.max(0, attemptNumber - 1), MAX_BACKOFF_MS);
}

export function resetPhasedSyncRetry(): void {
  if (RUST_SYNC_BUILD) retryGeneration += 1;
  attempt = 0;
  if (timer) clearTimeout(timer);
  timer = null;
}

export function handlePhasedSyncRetryableErrorImpl(
  service: ChatSynchronizationService,
  payload: PhasedSyncRetryablePayload,
): void {
  if (RUST_SYNC_BUILD) {
    void rustSyncPolicy().then((policy) => policy.handlePhasedSyncRetryableError(service, payload, rustRetryState, {
      markSyncCompleted: () => phasedSyncState.markSyncCompleted(),
      notifyDegraded: () => notificationStore.info(
        "Some chats may be out of date. We'll keep trying in the background.", 6000, true, RETRY_DEDUPE_KEY,
      ),
    }));
    return;
  }
  if (payload.retryable !== true) return;
  service.clearPhasedSyncTimeout();
  if (timer) return;
  if (attempt >= PHASED_SYNC_RETRY_MAX_ATTEMPTS) {
    console.warn("[ChatSyncService] Phased sync retry budget exhausted; keeping cached chats");
    resetPhasedSyncRetry();
    phasedSyncState.markSyncCompleted();
    service.dispatchEvent(new CustomEvent("phasedSyncComplete", {
      detail: { status: "completed_via_error", synthetic: true, reason: "error" },
    }));
    notificationStore.info(
      "Some chats may be out of date. We'll keep trying in the background.",
      6000,
      true,
      RETRY_DEDUPE_KEY,
    );
    return;
  }
  attempt += 1;
  const delay = computePhasedSyncRetryDelayMs(attempt, payload.retry_after_ms);
  console.info(
    `[ChatSyncService] Phased sync dependency unavailable; retry ${attempt}/${PHASED_SYNC_RETRY_MAX_ATTEMPTS} in ${delay}ms`,
  );
  timer = setTimeout(() => {
    timer = null;
    if (!service.webSocketConnected_FOR_SENDERS_ONLY) return;
    void service.startPhasedSync();
  }, delay);
}
