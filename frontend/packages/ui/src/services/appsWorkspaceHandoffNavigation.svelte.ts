import type { AppsRequestHandoff } from './appsWorkspaceContext';
import { phasedSyncState, NEW_CHAT_SENTINEL } from '../stores/phasedSyncStateStore';

/** Reactive navigation ownership must retain the exact one-use queue object. */
export function createAppsWorkspaceHandoffNavigation() {
  let request = $state.raw<AppsRequestHandoff | null>(null);
  return {
    get request() { return request; },
    set request(value: AppsRequestHandoff | null) {
      if (value) {
        // An Apps handoff is an explicit user destination even when the
        // already-clean welcome surface needs no reset. Late initial sync must
        // not replace that destination after the local user row appears.
        phasedSyncState.setCurrentActiveChatId(value.context?.chat_id ?? NEW_CHAT_SENTINEL);
        phasedSyncState.markUserMadeExplicitChoice();
      }
      request = value;
    },
  };
}
