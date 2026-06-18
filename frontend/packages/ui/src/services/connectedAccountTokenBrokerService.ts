// frontend/packages/ui/src/services/connectedAccountTokenBrokerService.ts
//
// Browser client for active-turn connected-account token broker refs.
// It sends refresh-token envelopes only to the token broker endpoint and returns
// opaque refs suitable for chat send payloads.
//
// Spec: docs/specs/calendar-permission-management/spec.yml

import { getApiUrl } from '../config/api';

export interface ConnectedAccountDirectoryEntry {
	connected_account_id: string;
	app_id: string;
	account_ref: string;
	label: string;
	capabilities: string[];
	runtime_modes?: Record<string, string>;
}

export interface ConnectedAccountTurnTokenRefInput {
	connected_account_id: string;
	app_id: string;
	allowed_actions: string[];
	refresh_token_envelope: Record<string, unknown>;
	action_scope?: Record<string, unknown>;
}

export interface ConnectedAccountTurnTokenRef {
	connected_account_id: string;
	app_id: string;
	turn_token_ref: string;
	allowed_actions: string[];
	action_scope?: Record<string, unknown>;
	expires_at: number;
}

export interface ConnectedAccountSendContext {
	directory?: ConnectedAccountDirectoryEntry[];
	tokenRefs?: ConnectedAccountTurnTokenRef[];
	tokenRefInputs?: ConnectedAccountTurnTokenRefInput[];
}

export interface PreparedConnectedAccountSendContext {
	directory?: ConnectedAccountDirectoryEntry[];
	tokenRefs?: ConnectedAccountTurnTokenRef[];
}

const CONNECTED_ACCOUNT_FORBIDDEN_FIELDS = [
	'refresh_token',
	'access_token',
	'provider_email',
	'email',
	'account_email',
	'provider_account_id',
	'provider_account_email',
	'oauth_scopes',
	'scopes'
];

export function assertNoConnectedAccountSecretLeak(value: unknown): void {
	const serialized = JSON.stringify(value ?? {});
	for (const key of CONNECTED_ACCOUNT_FORBIDDEN_FIELDS) {
		if (serialized.includes(`"${key}"`)) {
			throw new Error(`Connected account payload contains forbidden field: ${key}`);
		}
	}
}

export async function createConnectedAccountTurnTokenRefs(params: {
	chatId: string;
	messageId: string;
	refs: ConnectedAccountTurnTokenRefInput[];
}): Promise<ConnectedAccountTurnTokenRef[]> {
	if (params.refs.length === 0) return [];
	const response = await fetch(`${getApiUrl()}/v1/token-broker/turn-token-refs`, {
		method: 'POST',
		credentials: 'include',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
			chat_id: params.chatId,
			message_id: params.messageId,
			refs: params.refs
		})
	});
	if (!response.ok) {
		throw new Error(`Failed to create connected-account token refs (HTTP ${response.status})`);
	}
	const payload = (await response.json()) as {
		refs?: Array<{
			connected_account_id: string;
			app_id: string;
			turn_token_ref: string;
			expires_at: number;
		}>;
	};
	if (!Array.isArray(payload.refs)) {
		throw new Error('Token broker response did not include refs');
	}
	return payload.refs.map((ref) => {
		const input = params.refs.find(
			(item) => item.connected_account_id === ref.connected_account_id && item.app_id === ref.app_id
		);
		return {
			connected_account_id: ref.connected_account_id,
			app_id: ref.app_id,
			turn_token_ref: ref.turn_token_ref,
			expires_at: ref.expires_at,
			allowed_actions: input?.allowed_actions ?? [],
			action_scope: input?.action_scope
		};
	});
}

export async function prepareConnectedAccountSendContext(params: {
	chatId: string;
	messageId: string;
	context?: ConnectedAccountSendContext;
}): Promise<PreparedConnectedAccountSendContext | undefined> {
	if (!params.context) return undefined;
	const tokenRefs = [...(params.context.tokenRefs ?? [])];
	if (params.context.directory?.length) {
		assertNoConnectedAccountSecretLeak(params.context.directory);
	}
	if (params.context.tokenRefInputs?.length) {
		try {
			tokenRefs.push(
				...(await createConnectedAccountTurnTokenRefs({
					chatId: params.chatId,
					messageId: params.messageId,
					refs: params.context.tokenRefInputs
				}))
			);
		} catch (error) {
			console.warn(
				'[ConnectedAccountTokenBroker] Token-ref creation failed; sending redacted directory only.',
				error
			);
		}
	}
	if (tokenRefs.length) {
		assertNoConnectedAccountSecretLeak(tokenRefs);
	}
	return {
		directory: params.context.directory,
		tokenRefs
	};
}
