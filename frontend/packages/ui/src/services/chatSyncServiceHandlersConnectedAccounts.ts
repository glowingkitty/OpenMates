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
import { ensureChatKeySafeForWrite } from './chatKeyWriteGuard';
import { chatKeyManager } from './encryption/ChatKeyManager';
import type { ChatSynchronizationService } from './chatSyncService';
import { listConnectedAccounts, buildConnectedAccountSendContext } from './connectedAccountStorageService';
import { createConnectedAccountTurnTokenRefs } from './connectedAccountTokenBrokerService';
import { chatDB } from './db';
import { encryptWithChatKey } from './encryption/MessageEncryptor';
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
	requests?: ConnectedAccountPermissionRequest['requests'];
}

interface ConnectedAccountActionReceiptPayload {
	chat_id: string;
	message_id?: string;
	action_id: string;
	receipt: {
		app_id?: string;
		skill_id?: string;
		action?: string;
		decision?: string;
		result_count?: number;
		undo_available?: boolean;
	};
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
		requests: Array.isArray(payload.requests) ? payload.requests : undefined,
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
	const requestedActions = request.requests ?? [];
	const selectedActionIds = requestedActions.length
		? connectedAccountPermissionStore.getSelectedActionIds()
		: [];
	const selectedRequests = requestedActions.length
		? requestedActions.filter((item) => selectedActionIds.includes(item.action_id))
		: [];
	if (requestedActions.length && selectedRequests.length === 0) return;

	connectedAccountPermissionStore.setLoading(true);
	try {
		const rows = await listConnectedAccounts();
		const tokenRefInputs = requestedActions.length
			? (
				await Promise.all(
					selectedRequests.map(async (item) => {
						const accountId = connectedAccountPermissionStore.getSelectedAccountIdForAction(item.action_id);
						if (!accountId) return [];
						const context = await buildConnectedAccountSendContext({
							rows,
							appId: request.appId,
							accountIds: [accountId],
							allowedActionsOverride: [item.action],
							actionScopesOverride: item.action_scope ? [item.action_scope] : undefined
						});
						return context?.tokenRefInputs ?? [];
					})
				)
			).flat()
			: (
				await buildConnectedAccountSendContext({
					rows,
					appId: request.appId,
					accountIds: [selectedAccountId],
					allowedActionsOverride: request.requiredActions
				})
			)?.tokenRefInputs ?? [];
		if (!tokenRefInputs.length) {
			throw new Error('No connected account token ref inputs were available for approval');
		}

		const tokenRefs = await createConnectedAccountTurnTokenRefs({
			chatId: request.chatId,
			messageId: request.messageId ?? request.requestId,
			refs: tokenRefInputs
		});

		await webSocketService.sendMessage('connected_account_permission_confirmed', {
			request_id: request.requestId,
			chat_id: request.chatId,
			approved: true,
			approved_action_ids: selectedRequests.map((item) => item.action_id),
			action_account_selections: Object.fromEntries(
				selectedRequests.map((item) => [
					item.action_id,
					connectedAccountPermissionStore.getSelectedAccountIdForAction(item.action_id)
				])
			),
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

export async function handleConnectedAccountActionReceiptImpl(
	serviceInstance: ChatSynchronizationService,
	payload: ConnectedAccountActionReceiptPayload
): Promise<void> {
	if (!payload.chat_id || !payload.action_id || !payload.receipt) {
		console.error('[ChatSyncService:ConnectedAccounts] Invalid receipt payload:', payload);
		return;
	}

	const chatKey = await chatKeyManager.getKey(payload.chat_id);
	if (!chatKey) {
		console.warn('[ChatSyncService:ConnectedAccounts] No chat key for receipt system message');
		return;
	}
	if (!(await ensureChatKeySafeForWrite(payload.chat_id, chatKey, 'connected account receipt'))) {
		return;
	}

	const { generateUUID } = await import('../message_parsing/utils');
	const messageId = `${payload.chat_id.slice(-10)}-${generateUUID()}`;
	const now = Math.floor(Date.now() / 1000);
	const content = JSON.stringify({
		type: 'connected_account_action_receipt',
		action_id: payload.action_id,
		user_message_id: payload.message_id,
		receipt: payload.receipt
	});
	const encryptedContent = await encryptWithChatKey(content, chatKey);
	const systemMessage = {
		message_id: messageId,
		chat_id: payload.chat_id,
		role: 'system' as const,
		content,
		created_at: now,
		status: 'sending' as const,
		encrypted_content: encryptedContent,
		user_message_id: payload.message_id
	};

	await chatDB.saveMessage(systemMessage);
	await webSocketService.sendMessage('chat_system_message_added', {
		chat_id: payload.chat_id,
		message: {
			message_id: messageId,
			role: 'system',
			encrypted_content: encryptedContent,
			created_at: now,
			user_message_id: payload.message_id,
			status: 'synced'
		}
	});

	const syncedMessage = { ...systemMessage, status: 'synced' as const };
	await chatDB.saveMessage(syncedMessage);
	serviceInstance.dispatchEvent(
		new CustomEvent('chatUpdated', {
			detail: {
				chat_id: payload.chat_id,
				type: 'system_message_added',
				newMessage: syncedMessage
			}
		})
	);
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
