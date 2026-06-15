// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersConnectedAccounts.test.ts
//
// Regression coverage for connected-account permission request handling.
// Approval cards must preserve backend-redacted request summaries and exact
// action scopes so the browser can show precise Calendar details while sending
// only opaque token refs back to the backend.
//
// Spec: docs/specs/calendar-permission-management/spec.yml

import { get } from 'svelte/store';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChatSynchronizationService } from '../chatSyncService';

const mocks = vi.hoisted(() => ({
	activeChatStore: {
		get: vi.fn(() => 'chat-1'),
		setActiveChat: vi.fn(),
		subscribe: vi.fn()
	},
	aiTypingStore: {
		subscribe: vi.fn((run: (value: { chatId: string | null; isTyping: boolean }) => void) => {
			run({ chatId: null, isTyping: false });
			return () => undefined;
		}),
		reset: vi.fn()
	},
	notificationStore: {
		addNotificationWithOptions: vi.fn(() => 'notification-1'),
		addNotification: vi.fn(),
		removeNotification: vi.fn()
	},
	chatDB: {
		updateMessageStatus: vi.fn(async () => undefined),
		saveMessage: vi.fn(async () => undefined)
	},
	listConnectedAccounts: vi.fn(async () => []),
	buildConnectedAccountSendContext: vi.fn(async () => ({ tokenRefInputs: [] })),
	createConnectedAccountTurnTokenRefs: vi.fn(async () => ['token-ref-1']),
	webSocketService: {
		sendMessage: vi.fn(async () => undefined)
	},
	chatKeyManager: {
		getKey: vi.fn(async () => null)
	},
	ensureChatKeySafeForWrite: vi.fn(async () => true),
	encryptWithChatKey: vi.fn(async () => 'encrypted-content')
}));

vi.mock('../../stores/activeChatStore', () => ({ activeChatStore: mocks.activeChatStore }));
vi.mock('../../stores/aiTypingStore', () => ({ aiTypingStore: mocks.aiTypingStore }));
vi.mock('../../stores/notificationStore', () => ({ notificationStore: mocks.notificationStore }));
vi.mock('../db', () => ({ chatDB: mocks.chatDB }));
vi.mock('../connectedAccountStorageService', () => ({
	listConnectedAccounts: mocks.listConnectedAccounts,
	buildConnectedAccountSendContext: mocks.buildConnectedAccountSendContext
}));
vi.mock('../connectedAccountTokenBrokerService', () => ({
	createConnectedAccountTurnTokenRefs: mocks.createConnectedAccountTurnTokenRefs
}));
vi.mock('../websocketService', () => ({ webSocketService: mocks.webSocketService }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: mocks.chatKeyManager }));
vi.mock('../chatKeyWriteGuard', () => ({
	ensureChatKeySafeForWrite: mocks.ensureChatKeySafeForWrite
}));
vi.mock('../encryption/MessageEncryptor', () => ({ encryptWithChatKey: mocks.encryptWithChatKey }));

import {
	approveConnectedAccountPermissionRequest,
	handleRequestConnectedAccountPermissionImpl
} from '../chatSyncServiceHandlersConnectedAccounts';
import {
	connectedAccountPermissionStore,
	currentConnectedAccountPermissionRequest
} from '../../stores/connectedAccountPermissionStore';

describe('chatSyncServiceHandlersConnectedAccounts', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		connectedAccountPermissionStore.clear();
		mocks.activeChatStore.get.mockReturnValue('chat-1');
		mocks.listConnectedAccounts.mockResolvedValue([]);
		mocks.buildConnectedAccountSendContext.mockResolvedValue({ tokenRefInputs: [] });
	});

	it('preserves redacted Calendar request summaries for the approval card', async () => {
		const service = {
			activeAITasks: new Map(),
			dispatchEvent: vi.fn()
		} as unknown as ChatSynchronizationService;
		const seenRequests: unknown[] = [];
		const listener = (event: Event) => {
			seenRequests.push((event as CustomEvent).detail);
		};
		window.addEventListener('showConnectedAccountPermissionRequest', listener);

		try {
			await handleRequestConnectedAccountPermissionImpl(service, {
				request_id: 'permission-1',
				chat_id: 'chat-1',
				message_id: 'message-1',
				app_id: 'calendar',
				skill_id: 'create-event',
				action: 'write',
				required_actions: ['write'],
				accounts: [
					{
						connected_account_id: 'acct-1',
						app_id: 'calendar',
						label: 'Work calendar',
						capabilities: ['read', 'write']
					}
				],
				requests: [
					{
						action_id: 'action-1',
						action: 'write',
						action_scope: { calendar_id: 'primary', event_id: 'event-1' },
						summary: {
							calendar_id: 'primary',
							event_title: 'Planning meeting',
							start: '2026-06-15T10:00:00Z',
							end: '2026-06-15T11:00:00Z'
						}
					}
				]
			});
		} finally {
			window.removeEventListener('showConnectedAccountPermissionRequest', listener);
		}

		expect(seenRequests).toHaveLength(1);
		expect(seenRequests[0]).toMatchObject({
			requestId: 'permission-1',
			requests: [
				{
					action_id: 'action-1',
					action: 'write',
					action_scope: { calendar_id: 'primary', event_id: 'event-1' },
					summary: {
						calendar_id: 'primary',
						event_title: 'Planning meeting',
						start: '2026-06-15T10:00:00Z',
						end: '2026-06-15T11:00:00Z'
					}
				}
			]
		});
	});

	it('passes exact action scopes when approving a Calendar permission request', async () => {
		connectedAccountPermissionStore.showRequest({
			requestId: 'permission-1',
			chatId: 'chat-1',
			messageId: 'message-1',
			appId: 'calendar',
			skillId: 'delete-event',
			action: 'delete',
			requiredActions: ['delete'],
			accounts: [
				{
					connected_account_id: 'acct-1',
					app_id: 'calendar',
					label: 'Work calendar',
					capabilities: ['read', 'delete']
				}
			],
			requests: [
				{
					action_id: 'action-1',
					action: 'delete',
					action_scope: { calendar_id: 'primary', event_id: 'event-1' },
					summary: { calendar_id: 'primary', event_id: 'event-1' }
				}
			],
			createdAt: Date.now()
		});
		mocks.listConnectedAccounts.mockResolvedValue([{ id: 'acct-1' }]);
		mocks.buildConnectedAccountSendContext.mockResolvedValue({ tokenRefInputs: [{ ref: 'input-1' }] });

		await approveConnectedAccountPermissionRequest();

		expect(mocks.buildConnectedAccountSendContext).toHaveBeenCalledWith({
			rows: [{ id: 'acct-1' }],
			appId: 'calendar',
			accountIds: ['acct-1'],
			allowedActionsOverride: ['delete'],
			actionScopesOverride: [{ calendar_id: 'primary', event_id: 'event-1' }]
		});
		expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
			'connected_account_permission_confirmed',
			expect.objectContaining({
				request_id: 'permission-1',
				chat_id: 'chat-1',
				approved: true,
				connected_account_token_refs: ['token-ref-1']
			})
		);
		expect(get(currentConnectedAccountPermissionRequest)).toBeNull();
	});
});
