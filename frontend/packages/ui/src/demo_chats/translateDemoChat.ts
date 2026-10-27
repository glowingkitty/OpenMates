import type { DemoChat } from './types';
import { get } from 'svelte/store';
import { text } from '../i18n/translations';
/**
 * Type for translation function
 */
type TranslationFunction = (key: string) => string;

const VERSION_ANNOUNCEMENT_TITLE_PATTERN = /^v(\d+\.\d+:\s*)/;

function normalizeVersionAnnouncementTitle(chatId: string, title: string): string {
	if (!chatId.startsWith('announcements-introducing-openmates-v')) {
		return title;
	}
	return title.replace(VERSION_ANNOUNCEMENT_TITLE_PATTERN, 'OpenMates v$1');
}

/**
 * Translates a demo chat by resolving translation keys from i18n JSON files
 * 
 * Demo chats MUST use translation keys (no hardcoded text allowed).
 * Legal chats build content from translation keys - they construct markdown from i18n keys.
 * Translation keys should be in format: 'demo_chats.{chat_name}.{field}'
 * 
 * For legal documents, the lastUpdated date is stored in TypeScript metadata (single source of truth)
 * and formatted using Intl.DateTimeFormat for the user's locale.
 * 
 * @param demoChat - The demo chat with translation keys
 * @returns A new demo chat with translated content
 */
export function translateDemoChat(demoChat: DemoChat): DemoChat {
	// Use our text store which auto-appends ".text" for the { text: value } JSON wrapper
	const t = get(text) as TranslationFunction;
	// Demo chats use translation keys - translate them
	const translatedTitle = t(demoChat.title);
	return {
		...demoChat,
		// All fields are translation keys - translate them
		title: normalizeVersionAnnouncementTitle(demoChat.chat_id, translatedTitle),
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
