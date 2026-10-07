/** Labels are supplied by callers so eventual product integration can use i18n. */
export function emitReconnect() {
  window.dispatchEvent(new CustomEvent('openmates-preview-reconnect'));
}
export default {
  state: 'reconnecting', label: 'Reconnecting to server',
  retryLabel: 'Tap to reconnect', onReconnect: emitReconnect,
};

export const variants = {
  offline: { state: 'offline', label: 'You are offline' },
  syncing: { state: 'syncing', label: 'Syncing chats' },
  idle: { state: 'idle', label: '' },
};
