// frontend/packages/ui/src/services/chatSyncServiceHandlersConnectedAccounts.ts
//
// WebSocket handlers and confirmation helpers for connected-account action
// approvals. The browser is responsible for decrypting account rows and sending
// only opaque turn-token refs back to the backend continuation handler.
//
// Spec: docs/specs/calendar-permission-management/spec.yml

import { get } from 'svelte/store';
import { activeChatStore } from '../stores/activeChatStore';
import { aiTypingStore } from '../stores/aiTypingStore';
import {
	connectedAccountPermissionStore,
	type ConnectedAccountPermissionAccount,
	type ConnectedAccountPermissionRequest
} from '../stores/connectedAccountPermissionStore';
import { notificationStore } from '../stores/notificationStore';
import type { ChatSynchronizationService } from './chatSyncService';
import { listConnectedAccounts, buildConnectedAccountSendContext } from './connectedAccountStorageService';
import { createConnectedAccountTurnTokenRefs } from './connectedAccountTokenBrokerService';
import { chatDB } from './db';
import { webSocketService } from './websocketService';

interface RequestConnectedAccountPermissionPayload {
	request_id: string;
	chat_id: string;
	message_id?: string;
	app_id: string;
	skill_id: string;
	action: string;
	required_actions?: string[];
	accounts?: ConnectedAccountPermissionAccount[];
}

const connectedAccountPermissionNotifications = new Map<string, string>();
const connectedAccountPermissionNotificationUnsubs = new Map<string, () => void>();

export async function handleRequestConnectedAccountPermissionImpl(
	serviceInstance: ChatSynchronizationService,
	payload: RequestConnectedAccountPermissionPayload
): Promise<void> {
	const { request_id, chat_id, app_id, skill_id, action } = payload;
	if (!request_id || !chat_id || !app_id || !skill_id || !action) {
		console.error('[ChatSyncService:ConnectedAccounts] Invalid permission request payload:', payload);
		return;
	}

	const accounts = Array.isArray(payload.accounts) ? payload.accounts : [];
	if (accounts.length === 0) {
		console.warn('[ChatSyncService:ConnectedAccounts] Request has no approvable accounts:', payload);
		return;
	}

	const request: ConnectedAccountPermissionRequest = {
		requestId: request_id,
		chatId: chat_id,
		messageId: payload.message_id,
		appId: app_id,
		skillId: skill_id,
		action,
		requiredActions: payload.required_actions?.length ? payload.required_actions : [action],
		accounts,
		createdAt: Date.now()
	};

	clearConnectedAccountProcessingState(serviceInstance, chat_id, payload.message_id);

	if (typeof window !== 'undefined') {
		window.dispatchEvent(
			new CustomEvent('showConnectedAccountPermissionRequest', {
				detail: request
			})
		);
	}

	if (activeChatStore.get() !== chat_id) {
		const notificationId = notificationStore.addNotificationWithOptions('info', {
			message: 'A conversation is waiting for connected-account approval',
			duration: 0,
			dismissible: true,
			actionLabel: 'View',
			onAction: () => {
				activeChatStore.setActiveChat(chat_id);
				dismissConnectedAccountPermissionNotification(request_id);
			}
		});
		connectedAccountPermissionNotifications.set(request_id, notificationId);

		const unsubscribe = activeChatStore.subscribe((currentChatId) => {
			if (currentChatId === chat_id) {
				dismissConnectedAccountPermissionNotification(request_id);
			}
		});
		connectedAccountPermissionNotificationUnsubs.set(request_id, unsubscribe);
	}
}

export async function approveConnectedAccountPermissionRequest(): Promise<void> {
	const request = connectedAccountPermissionStore.getCurrentRequest();
	const selectedAccountId = connectedAccountPermissionStore.getSelectedAccountId();
	if (!request || !selectedAccountId) return;

	connectedAccountPermissionStore.setLoading(true);
	try {
		const rows = await listConnectedAccounts();
		const context = await buildConnectedAccountSendContext({
			rows,
			appId: request.appId,
			accountIds: [selectedAccountId],
			allowedActionsOverride: request.requiredActions
		});
		if (!context?.tokenRefInputs?.length) {
			throw new Error('No connected account token ref inputs were available for approval');
		}

		const tokenRefs = await createConnectedAccountTurnTokenRefs({
			chatId: request.chatId,
			messageId: request.messageId ?? request.requestId,
			refs: context.tokenRefInputs
		});

		await webSocketService.sendMessage('connected_account_permission_confirmed', {
			request_id: request.requestId,
			chat_id: request.chatId,
			approved: true,
			connected_account_token_refs: tokenRefs
		});

		dismissConnectedAccountPermissionNotification(request.requestId);
		connectedAccountPermissionStore.clear();
		notificationStore.addNotification('success', 'Connected account approved for this action', 3000);
	} catch (error) {
		console.error('[ChatSyncService:ConnectedAccounts] Failed to approve request:', error);
		connectedAccountPermissionStore.setLoading(false);
		notificationStore.addNotification('error', 'Could not approve connected account access', 5000);
	}
}

export async function rejectConnectedAccountPermissionRequest(): Promise<void> {
	const request = connectedAccountPermissionStore.getCurrentRequest();
	if (!request) return;

	connectedAccountPermissionStore.setLoading(true);
	try {
		await webSocketService.sendMessage('connected_account_permission_confirmed', {
			request_id: request.requestId,
			chat_id: request.chatId,
			approved: false,
			connected_account_token_refs: []
		});
		dismissConnectedAccountPermissionNotification(request.requestId);
		connectedAccountPermissionStore.clear();
	} catch (error) {
		console.error('[ChatSyncService:ConnectedAccounts] Failed to reject request:', error);
		connectedAccountPermissionStore.setLoading(false);
		notificationStore.addNotification('error', 'Could not reject connected account access', 5000);
	}
}

function clearConnectedAccountProcessingState(
	serviceInstance: ChatSynchronizationService,
	chatId: string,
	messageId?: string
): void {
	const typingStatus = get(aiTypingStore);
	if (typingStatus.chatId === chatId && typingStatus.isTyping) {
		aiTypingStore.reset();
	}

	const taskInfo = serviceInstance.activeAITasks.get(chatId);
	if (taskInfo) {
		serviceInstance.activeAITasks.delete(chatId);
		serviceInstance.dispatchEvent(
			new CustomEvent('aiTaskEnded', {
				detail: {
					chatId,
					taskId: taskInfo.taskId,
					status: 'waiting_for_connected_account_permission'
				}
			})
		);
	}

	if (messageId) {
		chatDB.updateMessageStatus(messageId, 'waiting_for_user').catch((error) => {
			console.warn('[ChatSyncService:ConnectedAccounts] Could not update waiting message status:', error);
		});
	}
}

function dismissConnectedAccountPermissionNotification(requestId: string): void {
	const notificationId = connectedAccountPermissionNotifications.get(requestId);
	if (notificationId) {
		notificationStore.removeNotification(notificationId);
		connectedAccountPermissionNotifications.delete(requestId);
	}
	const unsubscribe = connectedAccountPermissionNotificationUnsubs.get(requestId);
	if (unsubscribe) {
		unsubscribe();
		connectedAccountPermissionNotificationUnsubs.delete(requestId);
	}
}
