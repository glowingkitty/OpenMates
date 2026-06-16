// frontend/packages/ui/src/services/__tests__/connectedAccountActionService.test.ts
//
// Regression coverage for connected-account undo token-ref creation.
// Undo remains client-mediated, so the browser must request the exact broker
// action needed by the journaled undo type instead of always requesting delete.
//
// Spec: docs/specs/calendar-permission-management/spec.yml

import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
	buildConnectedAccountSendContext: vi.fn(),
	createConnectedAccountTurnTokenRefs: vi.fn(),
	listConnectedAccounts: vi.fn()
}));

vi.mock('../../config/api', () => ({
	getApiEndpoint: (path: string) => `https://api.test${path}`
}));

vi.mock('../connectedAccountStorageService', () => ({
	buildConnectedAccountSendContext: mocks.buildConnectedAccountSendContext,
	listConnectedAccounts: mocks.listConnectedAccounts
}));

vi.mock('../connectedAccountTokenBrokerService', () => ({
	createConnectedAccountTurnTokenRefs: mocks.createConnectedAccountTurnTokenRefs
}));

import { connectedAccountUndoBrokerAction, undoConnectedAccountAction } from '../connectedAccountActionService';

describe('connectedAccountActionService', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
		vi.clearAllMocks();
		mocks.listConnectedAccounts.mockResolvedValue([{ id: 'acct-1' }]);
		mocks.buildConnectedAccountSendContext.mockResolvedValue({ tokenRefInputs: [{ ref: 'input-1' }] });
		mocks.createConnectedAccountTurnTokenRefs.mockResolvedValue([{ turn_token_ref: 'turn-ref-1' }]);
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => ({
				ok: true,
				json: async () => ({ action_id: 'act-1', status: 'undone', undo_type: 'restore_updated_event', events: [], receipt: {} })
			}))
		);
	});

	it('maps Calendar undo types to the required broker action', () => {
		expect(connectedAccountUndoBrokerAction('delete_created_event')).toBe('delete');
		expect(connectedAccountUndoBrokerAction('restore_updated_event')).toBe('update');
		expect(connectedAccountUndoBrokerAction('recreate_deleted_event')).toBe('write');
		expect(connectedAccountUndoBrokerAction(undefined)).toBe('delete');
	});

	it('creates token refs for restore-updated undo using update permission', async () => {
		await undoConnectedAccountAction({
			actionId: 'act-1',
			chatId: 'chat-1',
			messageId: 'msg-1',
			undoType: 'restore_updated_event'
		});

		expect(mocks.buildConnectedAccountSendContext).toHaveBeenCalledWith({
			rows: [{ id: 'acct-1' }],
			appId: 'calendar',
			allowedActionsOverride: ['update'],
			includeActionScope: false
		});
		expect(fetch).toHaveBeenCalledWith(
			'https://api.test/v1/connected-accounts/actions/act-1/undo',
			expect.objectContaining({ method: 'POST', credentials: 'include' })
		);
	});
});
