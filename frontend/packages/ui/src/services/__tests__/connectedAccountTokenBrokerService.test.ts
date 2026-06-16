// frontend/packages/ui/src/services/__tests__/connectedAccountTokenBrokerService.test.ts
//
// Regression coverage for active-turn connected-account token broker payloads.
// These tests keep refresh-token envelopes out of chat sends while preserving
// redacted account directory data needed for permission dialogs when broker
// pre-submission fails before the backend can execute a skill.
//
// Spec: docs/specs/calendar-permission-management/spec.yml

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../config/api', () => ({
	getApiUrl: () => 'https://api.test'
}));

import { prepareConnectedAccountSendContext } from '../connectedAccountTokenBrokerService';

describe('connectedAccountTokenBrokerService', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
		vi.clearAllMocks();
	});

	it('preserves redacted directory when token-ref creation fails', async () => {
		vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(JSON.stringify({ detail: 'unavailable' }), {
				status: 503,
				headers: { 'Content-Type': 'application/json' }
			})
		);
		const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

		const context = await prepareConnectedAccountSendContext({
			chatId: 'chat-1',
			messageId: 'message-1',
			context: {
				directory: [
					{
						connected_account_id: 'acct-1',
						app_id: 'calendar',
						account_ref: 'calendar-work',
						label: 'Work calendar',
						capabilities: ['read'],
						runtime_modes: { read: 'allow_automatically' }
					}
				],
				tokenRefInputs: [
					{
						connected_account_id: 'acct-1',
						app_id: 'calendar',
						allowed_actions: ['read'],
						refresh_token_envelope: { refresh_token: 'secret-refresh', provider: 'google' },
						action_scope: { calendar_id: 'primary' }
					}
				]
			}
		});

		expect(context?.directory).toEqual([
			{
				connected_account_id: 'acct-1',
				app_id: 'calendar',
				account_ref: 'calendar-work',
				label: 'Work calendar',
				capabilities: ['read'],
				runtime_modes: { read: 'allow_automatically' }
			}
		]);
		expect(context?.tokenRefs).toEqual([]);
		expect(JSON.stringify(context)).not.toContain('secret-refresh');
		expect(warnSpy).toHaveBeenCalledWith(
			'[ConnectedAccountTokenBroker] Token-ref creation failed; sending redacted directory only.',
			expect.any(Error)
		);
	});
});
