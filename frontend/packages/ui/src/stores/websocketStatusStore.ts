// frontend/packages/ui/src/stores/websocketStatusStore.ts
/**
 * @file websocketStatusStore.ts
 * @description Svelte store for managing and broadcasting WebSocket connection status.
 */
import { writable } from 'svelte/store';

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error' | 'reconnecting';

export interface WebSocketState {
  status: WebSocketStatus;
  lastMessage: string | null; // For debugging or specific status messages
  error: string | null; // Details of the last error, if any
}

const initialState: WebSocketState = {
  status: 'disconnected',
  lastMessage: null,
  error: null,
};

const { subscribe, set, update } = writable<WebSocketState>(initialState);

export const websocketStatus = {
  subscribe,
  setStatus: (status: WebSocketStatus, message?: string) => {
    update((state) => {
      state.status = status;
      if (message) state.lastMessage = message;
      if (status !== 'error') state.error = null; // Clear error if status is not 'error'
      return state;
    });
  },
  setError: (errorMessage: string, status: WebSocketStatus = 'error') => {
    update((state) => {
      state.status = status;
      state.error = errorMessage;
      state.lastMessage = `Error: ${errorMessage}`;
      return state;
    });
  },
  reset: () => {
    set(initialState);
  },
};

// Example usage:
// import { websocketStatus } from './websocketStatusStore';
// websocketStatus.setStatus('connected');
// websocketStatus.setError('Connection failed due to network issues.');
//
// In a Svelte component:
// import { websocketStatus } from './websocketStatusStore';
// $: status = $websocketStatus.status;