/*
 * OpenMates VS Code reconnect policy.
 *
 * Purpose: make explicit that the extension is a UI client, not the owner of
 * long-running OpenMates AI jobs or remote-access daemon work.
 * Architecture: backend jobs and CLI remote-access daemons persist independently
 * and the webview reloads state from OpenMates after reconnect.
 * Security: no hidden local worker state is used as authority for project access.
 */

export interface ReconnectPolicy {
  ownsLongRunningWork: boolean;
  reloadsFromOpenMates: boolean;
  cancelsRemoteAccessOnDisconnect: boolean;
}

export function getReconnectPolicy(): ReconnectPolicy {
  return {
    ownsLongRunningWork: false,
    reloadsFromOpenMates: true,
    cancelsRemoteAccessOnDisconnect: false,
  };
}
