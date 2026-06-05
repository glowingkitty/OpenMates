// ActiveChat replay utility helpers.
//
// Extracted from ActiveChat.svelte so the component retains UI state and replay
// orchestration while pure replay calculations and message selection live in a
// small module. This keeps replay behavior testable without Svelte state.

import type { Message as ChatMessageModel } from '../types/chat';

export type ChatReplayOptions = {
    /** Assistant message to replay. Defaults to the latest assistant message in the open chat. */
    messageId?: string;
    /** Playback speed multiplier. Values above 1 make the replay faster. */
    speed?: number;
    /** Optional delay before the assistant bubble appears, before speed scaling. */
    initialDelayMs?: number;
    /** Optional delay between paragraph chunks, before speed scaling. */
    paragraphDelayMs?: number;
};

export function cloneMessagesForReplay(messages: ChatMessageModel[]): ChatMessageModel[] {
    return messages.map((message) => ({ ...message }));
}

export function getReplayDelay(baseMs: number, speed: number): number {
    return Math.max(40, Math.round(baseMs / Math.max(0.1, speed)));
}

export function splitReplayContent(content: string): string[] {
    const paragraphs = content
        .split(/\n{2,}/)
        .map((part) => part.trim())
        .filter(Boolean);

    if (paragraphs.length > 1) {
        return paragraphs.map((_, index) => paragraphs.slice(0, index + 1).join('\n\n'));
    }

    const sentences = content.match(/[^.!?]+[.!?]+(?:\s+|$)|[^.!?]+$/g)?.map((part) => part.trim()).filter(Boolean) ?? [];
    if (sentences.length > 1) {
        return sentences.map((_, index) => sentences.slice(0, index + 1).join(' '));
    }

    return [content];
}

export function resolveReplayPair(messages: ChatMessageModel[], options: ChatReplayOptions) {
    const assistantIndex = options.messageId
        ? messages.findIndex((message) => message.message_id === options.messageId && message.role === 'assistant')
        : (() => {
            for (let index = messages.length - 1; index >= 0; index -= 1) {
                if (messages[index].role === 'assistant') return index;
            }
            return -1;
        })();

    if (assistantIndex === -1) {
        throw new Error('No assistant message found to replay in the open chat.');
    }

    const assistantMessage = messages[assistantIndex];
    const linkedUserIndex = assistantMessage.user_message_id
        ? messages.findIndex((message) => message.message_id === assistantMessage.user_message_id)
        : -1;
    const userIndex = linkedUserIndex !== -1
        ? linkedUserIndex
        : (() => {
            for (let index = assistantIndex - 1; index >= 0; index -= 1) {
                if (messages[index].role === 'user') return index;
            }
            return -1;
        })();

    if (userIndex === -1) {
        throw new Error('No user message found before the assistant message to replay.');
    }

    return { assistantIndex, userIndex, assistantMessage, userMessage: messages[userIndex] };
}
