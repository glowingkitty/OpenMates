/** Delayed, transient profile feedback; independent of chat UI-readiness flags. */
import { writable } from 'svelte/store';
import type { WebSocketStatus } from './websocketStatusStore';

export type ConnectionFeedbackState = 'idle' | 'offline' | 'reconnecting' | 'syncing';
export interface ConnectionFeedback {
  state: ConnectionFeedbackState;
  reason: 'offline' | 'reconnecting' | 'server_updating';
}
export interface ConnectionFeedbackInputs {
  online: boolean;
  authenticated: boolean;
  checkingAuth: boolean;
  websocketStatus: WebSocketStatus;
  syncing: boolean;
}

const idle: ConnectionFeedback = { state: 'idle', reason: 'reconnecting' };
const initialInputs: ConnectionFeedbackInputs = {
  online: true, authenticated: false, checkingAuth: false,
  websocketStatus: 'disconnected', syncing: false,
};

export function createConnectionFeedbackStore() {
  const { subscribe, set } = writable<ConnectionFeedback>(idle);
  let inputs = initialInputs;
  let disconnected = false;
  let authStuck = false;
  let syncing = false;
  let resumed = false;
  let serverUpdating = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let syncTimer: ReturnType<typeof setTimeout> | undefined;
  let authTimer: ReturnType<typeof setTimeout> | undefined;
  let resumeTimer: ReturnType<typeof setTimeout> | undefined;

  function publish() {
    const reconnecting = inputs.authenticated && (disconnected || authStuck);
    set({
      state: !inputs.online ? 'offline' : !inputs.authenticated ? 'idle' : reconnecting ? 'reconnecting' : syncing ? 'syncing' : 'idle',
      reason: !inputs.online ? 'offline' : serverUpdating ? 'server_updating' : 'reconnecting',
    });
  }

  function update(next: ConnectionFeedbackInputs) {
    inputs = next;
    if (!next.authenticated || next.websocketStatus === 'connected') {
      clearTimeout(reconnectTimer);
      reconnectTimer = undefined;
      disconnected = false;
      if (next.websocketStatus === 'connected') {
        clearTimeout(resumeTimer);
        resumeTimer = undefined;
        resumed = false;
        serverUpdating = false;
      }
    } else if (next.online && !resumed && !disconnected && reconnectTimer === undefined) {
      reconnectTimer = setTimeout(() => {
        reconnectTimer = undefined;
        disconnected = true;
        publish();
      }, 3000);
    }

    if (next.online && next.checkingAuth) {
      if (!authStuck && authTimer === undefined) {
        authTimer = setTimeout(() => {
          authTimer = undefined;
          authStuck = true;
          publish();
        }, 12000);
      }
    } else {
      clearTimeout(authTimer);
      authTimer = undefined;
      authStuck = false;
    }

    if (next.online && next.authenticated && next.websocketStatus === 'connected' && next.syncing) {
      if (!syncing && syncTimer === undefined) {
        syncTimer = setTimeout(() => {
          syncTimer = undefined;
          syncing = true;
          publish();
        }, 600);
      }
    } else {
      clearTimeout(syncTimer);
      syncTimer = undefined;
      syncing = false;
    }
    publish();
  }

  return {
    subscribe,
    update,
    resume() {
      clearTimeout(resumeTimer);
      clearTimeout(reconnectTimer);
      reconnectTimer = undefined;
      resumed = true;
      disconnected = false;
      resumeTimer = setTimeout(() => {
        resumeTimer = undefined;
        resumed = false;
        disconnected = inputs.authenticated && inputs.websocketStatus !== 'connected';
        publish();
      }, 10000);
      publish();
    },
    serverUpdating() {
      serverUpdating = true;
      publish();
    },
    reset() {
      for (const timer of [reconnectTimer, syncTimer, authTimer, resumeTimer]) clearTimeout(timer);
      reconnectTimer = syncTimer = authTimer = resumeTimer = undefined;
      inputs = initialInputs;
      disconnected = authStuck = syncing = resumed = serverUpdating = false;
      set(idle);
    },
  };
}

export const connectionFeedback = createConnectionFeedbackStore();
