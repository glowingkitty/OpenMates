// frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { aiTypingStore } from '../stores/aiTypingStore';
import type {
    AITaskInitiatedPayload,
    AIMessageUpdatePayload,
    AITypingStartedPayload,
    AIMessageReadyPayload,
    AITaskCancelRequestedPayload
} from '../types/chat'; // Assuming these types might be moved or are already in a shared types file

// --- AI Task and Stream Event Handler Implementations ---

export function handleAITaskInitiatedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AITaskInitiatedPayload
): void {
    console.info("[ChatSyncService:AI] Received 'ai_task_initiated':", payload);
    // Accessing private member, ensure 'this' context is correct or pass necessary state/methods
    (serviceInstance as any).activeAITasks.set(payload.chat_id, { taskId: payload.ai_task_id, userMessageId: payload.user_message_id });
    serviceInstance.dispatchEvent(new CustomEvent('aiTaskInitiated', { detail: payload }));
}

export function handleAIMessageUpdateImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AIMessageUpdatePayload
): void {
    console.debug("[ChatSyncService:AI] Received 'ai_message_update':", payload);
    serviceInstance.dispatchEvent(new CustomEvent('aiMessageChunk', { detail: payload }));
    if (payload.is_final_chunk) {
        const taskInfo = (serviceInstance as any).activeAITasks.get(payload.chat_id);
        if (taskInfo && taskInfo.taskId === payload.task_id) {
            (serviceInstance as any).activeAITasks.delete(payload.chat_id);
            // Clear typing status for this specific AI task
            aiTypingStore.clearTyping(payload.chat_id, payload.task_id); 
            serviceInstance.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: payload.chat_id, taskId: payload.task_id, status: payload.interrupted_by_revocation ? 'cancelled' : (payload.interrupted_by_soft_limit ? 'timed_out' : 'completed') } }));
            console.info(`[ChatSyncService:AI] AI Task ${payload.task_id} for chat ${payload.chat_id} considered ended due to final chunk marker. Typing status cleared.`);
        }
    }
}

export function handleAITypingStartedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AITypingStartedPayload
): void {
    console.debug("[ChatSyncService:AI] Received 'ai_typing_started':", payload);
    aiTypingStore.setTyping(payload.chat_id, payload.user_message_id, payload.message_id, payload.category);
    serviceInstance.dispatchEvent(new CustomEvent('aiTypingStarted', { detail: payload }));
}

export function handleAITypingEndedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: { chat_id: string, message_id: string }
): void {
    console.debug("[ChatSyncService:AI] Received 'ai_typing_ended':", payload);
    aiTypingStore.clearTyping(payload.chat_id, payload.message_id);
    serviceInstance.dispatchEvent(new CustomEvent('aiTypingEnded', { detail: payload }));
}

export function handleAIMessageReadyImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AIMessageReadyPayload
): void {
    console.debug("[ChatSyncService:AI] Received 'ai_message_ready':", payload);
    serviceInstance.dispatchEvent(new CustomEvent('aiMessageCompletedOnServer', { detail: payload }));
    const taskInfo = (serviceInstance as any).activeAITasks.get(payload.chat_id);
    if (taskInfo && taskInfo.taskId === payload.message_id) {
        (serviceInstance as any).activeAITasks.delete(payload.chat_id);
        serviceInstance.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: payload.chat_id, taskId: payload.message_id, status: 'completed' } }));
        console.info(`[ChatSyncService:AI] AI Task ${payload.message_id} for chat ${payload.chat_id} considered ended due to 'ai_message_ready'.`);
    }
}

export function handleAITaskCancelRequestedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AITaskCancelRequestedPayload
): void {
    console.info("[ChatSyncService:AI] Received 'ai_task_cancel_requested' acknowledgement:", payload);
    serviceInstance.dispatchEvent(new CustomEvent('aiTaskCancellationAcknowledged', { detail: payload }));
    
    if (payload.status === 'already_completed' || payload.status === 'not_found') {
        const chatIdsToClear: string[] = [];
        (serviceInstance as any).activeAITasks.forEach((value: { taskId: string; }, key: string) => {
            if (value.taskId === payload.task_id) {
                chatIdsToClear.push(key);
            }
        });
        chatIdsToClear.forEach(chatId => {
            (serviceInstance as any).activeAITasks.delete(chatId);
            serviceInstance.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: chatId, taskId: payload.task_id, status: payload.status } }));
            console.info(`[ChatSyncService:AI] AI Task ${payload.task_id} for chat ${chatId} cleared due to cancel ack status: ${payload.status}.`);
        });
    }
}
