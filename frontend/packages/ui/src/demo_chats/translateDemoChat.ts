import type { DemoChat } from './types';
import { get } from 'svelte/store';
import { _ } from 'svelte-i18n';
import { 
	buildPrivacyPolicyContent, 
	buildTermsOfUseContent, 
	buildImprintContent 
} from '../legal/buildLegalContent';

/**
 * Type for translation function
 */
type TranslationFunction = (key: string) => string;

/**
 * Translates a demo chat by resolving translation keys from i18n JSON files
 * 
 * Demo chats MUST use translation keys (no hardcoded text allowed).
 * Legal chats build content from translation keys - they construct markdown from i18n keys.
 * Translation keys should be in format: 'demo_chats.{chat_name}.{field}.text'
 * 
 * @param demoChat - The demo chat with translation keys
 * @returns A new demo chat with translated content
 */
export function translateDemoChat(demoChat: DemoChat): DemoChat {
	const t = get(_) as TranslationFunction;
	
	// Legal chats (chat_id starts with 'legal-') build content from translation keys
	if (demoChat.chat_id.startsWith('legal-')) {
		let builtContent = '';
		
		// Build content based on chat type
		if (demoChat.chat_id === 'legal-privacy') {
			builtContent = buildPrivacyPolicyContent(t);
		} else if (demoChat.chat_id === 'legal-terms') {
			builtContent = buildTermsOfUseContent(t);
		} else if (demoChat.chat_id === 'legal-imprint') {
			builtContent = buildImprintContent(t);
		} else {
			// Fallback: use first message content as-is (shouldn't happen)
			builtContent = demoChat.messages[0]?.content || '';
		}
		
		return {
			...demoChat,
			// Legal chats use translation keys for title/description
			title: t(demoChat.title),
			description: t(demoChat.description),
			// Build content from translation keys
			messages: [{
				...demoChat.messages[0],
				content: builtContent
			}],
			// Translate follow-up suggestions if they exist
			follow_up_suggestions: demoChat.follow_up_suggestions?.map(suggestion => 
				suggestion.startsWith('legal.') ? t(suggestion) : suggestion
			)
		};
	}
	
	// Demo chats use translation keys - translate them
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

