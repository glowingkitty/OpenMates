// frontend/packages/ui/src/services/connectedAccountActionService.ts
//
// Client helpers for connected-account action follow-ups such as undo.
// Undo remains client-mediated: the browser decrypts the stored refresh-token
// envelope locally, creates fresh opaque token refs, and sends only refs to the
// backend action route.
//
// Spec: docs/specs/calendar-permission-management/spec.yml

import { getApiEndpoint } from '../config/api';
import { buildConnectedAccountSendContext, listConnectedAccounts } from './connectedAccountStorageService';
import { createConnectedAccountTurnTokenRefs } from './connectedAccountTokenBrokerService';

interface UndoConnectedAccountActionResult {
	action_id: string;
	status: string;
	undo_type: string;
	events: Array<Record<string, string>>;
	receipt: Record<string, unknown>;
}

export type ConnectedAccountUndoType = 'delete_created_event' | 'restore_updated_event' | 'recreate_deleted_event' | string;

export async function undoConnectedAccountAction(params: {
	actionId: string;
	chatId: string;
	messageId: string;
	undoType?: ConnectedAccountUndoType;
}): Promise<UndoConnectedAccountActionResult> {
	const rows = await listConnectedAccounts();
	const context = await buildConnectedAccountSendContext({
		rows,
		appId: 'calendar',
		allowedActionsOverride: [connectedAccountUndoBrokerAction(params.undoType)],
		includeActionScope: false
	});
	if (!context?.tokenRefInputs?.length) {
		throw new Error('No connected calendar account is available for undo');
	}

	const tokenRefs = await createConnectedAccountTurnTokenRefs({
		chatId: params.chatId,
		messageId: params.messageId,
		refs: context.tokenRefInputs
	});
	if (tokenRefs.length === 0) {
		throw new Error('Could not create connected-account token refs for undo');
	}

	let lastError: Error | undefined;
	for (const tokenRef of tokenRefs) {
		try {
			const response = await fetch(
				getApiEndpoint(`/v1/connected-accounts/actions/${encodeURIComponent(params.actionId)}/undo`),
				{
					method: 'POST',
					credentials: 'include',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						turn_token_ref: tokenRef.turn_token_ref,
						chat_id: params.chatId,
						message_id: params.messageId
					})
				}
			);
			if (response.ok) {
				return (await response.json()) as UndoConnectedAccountActionResult;
			}
			lastError = new Error(`Connected-account undo failed (HTTP ${response.status})`);
			if (response.status !== 403) break;
		} catch (error) {
			lastError = error instanceof Error ? error : new Error(String(error));
		}
	}

	throw lastError ?? new Error('Connected-account undo failed');
}

export function connectedAccountUndoBrokerAction(undoType: ConnectedAccountUndoType | undefined): 'delete' | 'update' | 'write' {
	if (undoType === 'restore_updated_event') return 'update';
	if (undoType === 'recreate_deleted_event') return 'write';
	return 'delete';
}
