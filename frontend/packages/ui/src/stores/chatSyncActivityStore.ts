import { writable } from "svelte/store";

export interface ChatSyncActivityState {
  active: boolean;
  teamId: string | null;
  contextEpoch: number | null;
}

const idle: ChatSyncActivityState = {
  active: false,
  teamId: null,
  contextEpoch: null,
};
const OFFLINE_SYNC_ACTIVITY_TIMEOUT_MS = 30_000;

function createChatSyncActivity() {
  const { subscribe, set } = writable<ChatSyncActivityState>(idle);
  let attempt = 0;
  let phasedContext: { teamId: string | null; epoch: number } | null = null;
  let offlineAttempt = 0;
  let offlineActive = false;
  let offlineTimeout: ReturnType<typeof setTimeout> | null = null;

  const publish = (): void => {
    set({
      active: phasedContext !== null || offlineActive,
      teamId: phasedContext?.teamId ?? null,
      contextEpoch: phasedContext?.epoch ?? null,
    });
  };

  const clearOfflineTimeout = (): void => {
    if (offlineTimeout !== null) clearTimeout(offlineTimeout);
    offlineTimeout = null;
  };

  return {
    subscribe,
    /** A phased sync request is about to be sent for this team context. */
    begin(context: { teamId: string | null; epoch: number }): number {
      attempt++;
      phasedContext = context;
      publish();
      return attempt;
    },
    /** Only the server's completion for the active full request ends activity. */
    complete(payload: { phase: string; team_id?: string | null; context_epoch?: number }): void {
      if (
        phasedContext === null ||
        payload.phase !== "all" ||
        (payload.team_id ?? null) !== phasedContext.teamId ||
        payload.context_epoch !== phasedContext.epoch
      ) return;
      attempt++;
      phasedContext = null;
      publish();
    },
    /** Offline replay has no server request ID; the next ACK ends the current send. */
    beginOffline(): number {
      offlineAttempt++;
      offlineActive = true;
      clearOfflineTimeout();
      const token = offlineAttempt;
      offlineTimeout = setTimeout(() => {
        if (token !== offlineAttempt) return;
        offlineActive = false;
        offlineTimeout = null;
        publish();
      }, OFFLINE_SYNC_ACTIVITY_TIMEOUT_MS);
      publish();
      return token;
    },
    completeOffline(): void {
      if (!offlineActive) return;
      offlineAttempt++;
      offlineActive = false;
      clearOfflineTimeout();
      publish();
    },
    /** A disconnect, timeout, error, logout, or team change ends this attempt. */
    clear(): void {
      attempt++;
      phasedContext = null;
      offlineAttempt++;
      offlineActive = false;
      clearOfflineTimeout();
      set(idle);
    },
    /** Ignore an older failed send after a newer sync request has started. */
    clearAttempt(token: number): void {
      if (token !== attempt) return;
      attempt++;
      phasedContext = null;
      publish();
    },
    clearOfflineAttempt(token: number): void {
      if (token !== offlineAttempt) return;
      offlineAttempt++;
      offlineActive = false;
      clearOfflineTimeout();
      publish();
    },
  };
}

export const chatSyncActivity = createChatSyncActivity();
