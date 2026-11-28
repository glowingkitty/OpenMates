// frontend/packages/ui/src/services/connectedAccountOAuthReturn.ts
//
// Handles the page the provider sends the browser back to after sign-in
// (`?oauth_handoff_id=` or `?error=`). Two situations:
//  - popup: the opener tab waits for the result; this page posts it over the
//    BroadcastChannel, gets an acknowledgement and closes itself.
//  - same tab (popup was blocked): settings pages call
//    consumeConnectedAccountOAuthReturn() once the user profile is loaded; it
//    finalizes the handoff, cleans the URL and returns the outcome to show.

import {
	CONNECTED_ACCOUNT_OAUTH_CHANNEL,
	clearPendingConnectedAccountOAuth,
	completeConnectedAccountOAuth,
	readPendingConnectedAccountOAuth,
	type ConnectedAccountsChangedDetail
} from './connectedAccountOAuthService';

const PENDING_MAX_AGE_MS = 15 * 60 * 1000;
const OPENER_ACK_TIMEOUT_MS = 1500;
const RETURN_PARAMS = ['oauth_handoff_id', 'error', 'oauth_error', 'error_description'];

interface OAuthReturnParams {
	handoffId?: string;
	providerError?: string;
}

function readReturnParams(): OAuthReturnParams | null {
	const query = new URLSearchParams(window.location.search);
	const handoffId = query.get('oauth_handoff_id') ?? undefined;
	const providerError = query.get('oauth_error') ?? query.get('error') ?? undefined;
	return handoffId || providerError ? { handoffId, providerError } : null;
}

function removeReturnParams(): void {
	const url = new URL(window.location.href);
	for (const name of RETURN_PARAMS) url.searchParams.delete(name);
	window.history.replaceState(window.history.state, '', url.toString());
}

function freshPending() {
	const pending = readPendingConnectedAccountOAuth();
	if (!pending) return null;
	if (Date.now() - pending.startedAt > PENDING_MAX_AGE_MS) {
		clearPendingConnectedAccountOAuth();
		return null;
	}
	return pending;
}

/** Popup case. Returns true when the opener took the result and this window is closing. */
export async function routeConnectedAccountOAuthReturnToOpener(): Promise<boolean> {
	const params = typeof window === 'undefined' ? null : readReturnParams();
	const pending = params ? freshPending() : null;
	if (!params || pending?.mode !== 'popup') return false;
	const channel = new BroadcastChannel(CONNECTED_ACCOUNT_OAUTH_CHANNEL);
	const acknowledged = await new Promise<boolean>((resolve) => {
		const timer = setTimeout(() => resolve(false), OPENER_ACK_TIMEOUT_MS);
		channel.onmessage = (event: MessageEvent) => {
			if ((event.data as { type?: string } | null)?.type !== 'oauth-return-ack') return;
			clearTimeout(timer);
			resolve(true);
		};
		channel.postMessage({ type: 'oauth-return', handoffId: params.handoffId, error: params.providerError });
	});
	channel.close();
	if (acknowledged) window.close();
	return acknowledged;
}

let inFlight: Promise<ConnectedAccountsChangedDetail | null> | null = null;

/** Same-tab case: finalize a returned handoff (or report the provider error). Null when this is not an OAuth return. */
export function consumeConnectedAccountOAuthReturn(): Promise<ConnectedAccountsChangedDetail | null> {
	if (inFlight) return inFlight;
	const params = readReturnParams();
	if (!params) return Promise.resolve(null);
	const pending = freshPending();
	removeReturnParams();
	if (!pending) {
		// A return without a pending record cannot be tied to an account row: tell the user instead of hiding it.
		return Promise.resolve({ status: 'error', reason: 'finalize_failed' });
	}
	const completion = completeConnectedAccountOAuth(pending, params).finally(() => {
		inFlight = null;
	});
	inFlight = completion;
	return completion;
}
