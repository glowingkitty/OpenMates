import type { DemoChat } from './types';
import { get } from 'svelte/store';
import { _ } from 'svelte-i18n';

/**
 * Translates a demo chat by resolving translation keys from i18n JSON files
 * 
 * Demo chats MUST use translation keys (no hardcoded text allowed).
 * Legal chats use plain text (already translated) - they skip translation.
 * Translation keys should be in format: 'demo_chats.{chat_name}.{field}.text'
 * 
 * @param demoChat - The demo chat with translation keys (or plain text for legal chats)
 * @returns A new demo chat with translated content
 */
export function translateDemoChat(demoChat: DemoChat): DemoChat {
	// Legal chats (chat_id starts with 'legal-') use plain text, skip translation
	if (demoChat.chat_id.startsWith('legal-')) {
		return demoChat; // Return as-is, already in plain text
	}
	
	// Demo chats use translation keys - translate them
	const t = get(_);
	
	return {
		...demoChat,
		// All fields are translation keys - translate them
		title: t(demoChat.title),
		description: t(demoChat.description),
		messages: demoChat.messages.map(message => ({
			...message,
			content: t(message.content)
		})),
		follow_up_suggestions: demoChat.follow_up_suggestions?.map(suggestion => t(suggestion))
	};
}

/**
 * Translates an array of demo chats
 */
export function translateDemoChats(demoChats: DemoChat[]): DemoChat[] {
	return demoChats.map(translateDemoChat);
}

