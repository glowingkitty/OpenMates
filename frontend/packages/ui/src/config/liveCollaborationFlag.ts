/**
 * Feature flag `live_collaboration`: on in CI builds (VITE_LIVE_COLLABORATION=true) and
 * switchable per browser with localStorage `om_live_collaboration=1`. It stays off on
 * dev and production until the owner's go; the old editors remain until then.
 */
export function isLiveCollaborationEnabled(): boolean {
	if (import.meta.env?.VITE_LIVE_COLLABORATION === 'true') return true;
	try {
		return typeof localStorage !== 'undefined' && localStorage.getItem('om_live_collaboration') === '1';
	} catch {
		return false;
	}
}
