// frontend/packages/ui/src/demo_chats/loadCommunityDemos.ts
// Loads community demo chats (example chats) from the server with language-aware caching.
//
// ARCHITECTURE: This module is the single source of loading logic for example chats.
// - Called on app page load (+page.svelte) so the for-everyone and for-developers intro
//   chats show example chat cards immediately, without requiring the sidebar (Chats) to open.
// - Also called from Chats.svelte on mount (fallback) and on language change (force reload).
//
// Language-specific loading with IndexedDB caching:
// 1. Loads demos in the user's current device language ONLY
// 2. Uses IndexedDB for offline support (cached demos available offline)
// 3. Reloads when language changes (via forceLanguageReload)
// 4. Hash-based change detection - only fetches updated demos

import { get } from 'svelte/store';
import { locale as svelteLocaleStore, waitLocale } from 'svelte-i18n';
import { getApiEndpoint } from '../config/api';
import {
	communityDemoStore,
	getLocalContentHashes,
	addCommunityDemo,
	getAllCommunityDemoChats,
} from './communityDemoStore';
import type { Chat, Message } from '../types/chat';

const LOG_PREFIX = '[loadCommunityDemos]';

/** Abort controller for in-flight reload when forceLanguageReload is used (language change). */
let demoReloadAbortController: AbortController | null = null;

/**
 * Load community demo chats from server with language-aware caching.
 * Available for ALL users (authenticated and non-authenticated).
 *
 * @param forceLanguageReload - If true, clears cache and reloads all demos (used on language change)
 */
export async function loadCommunityDemos(
	forceLanguageReload: boolean = false
): Promise<void> {
	if (!forceLanguageReload && communityDemoStore.isLoading()) {
		console.debug(`${LOG_PREFIX} Community demos already loading, skipping`);
		return;
	}

	if (forceLanguageReload && demoReloadAbortController) {
		console.debug(`${LOG_PREFIX} Aborting previous demo reload in favor of new language reload`);
		demoReloadAbortController.abort();
	}
	const abortController = new AbortController();
	if (forceLanguageReload) {
		demoReloadAbortController = abortController;
	}

	try {
		await waitLocale();

		if (abortController.signal.aborted) {
			console.debug(`${LOG_PREFIX} Demo reload aborted (superseded by newer reload)`);
			return;
		}

		communityDemoStore.setLoading(true);

		const currentLang = get(svelteLocaleStore) || 'en';
		console.debug(`${LOG_PREFIX} Loading community demos for language: ${currentLang}`);

		if (forceLanguageReload) {
			console.debug(`${LOG_PREFIX} Language changed - clearing cache and reloading demos`);
			try {
				const { demoChatsDB } = await import('../services/demoChatsDB');
				await demoChatsDB.clearAllDemoChats();
				communityDemoStore.clear();
			} catch (error) {
				console.error(`${LOG_PREFIX} Error clearing demo chats cache:`, error);
			}
		}

		if (!forceLanguageReload && !communityDemoStore.isCacheLoaded()) {
			console.debug(`${LOG_PREFIX} Loading community demos from IndexedDB cache...`);
			await communityDemoStore.loadFromCache();
		}

		if (abortController.signal.aborted) {
			console.debug(`${LOG_PREFIX} Demo reload aborted before fetch (superseded by newer reload)`);
			return;
		}

		const localHashes = await getLocalContentHashes();
		const hashesParam = Array.from(localHashes.entries())
			.map(([demoId, hash]) => `${demoId}:${hash}`)
			.join(',');

		if (forceLanguageReload) {
			console.debug(`${LOG_PREFIX} Reloading all demos in ${currentLang}`);
		} else {
			console.debug(
				`${LOG_PREFIX} Checking for demo chat updates with ${localHashes.size} local hashes...`
			);
		}

		const url = hashesParam
			? getApiEndpoint(
					`/v1/demo/chats?lang=${currentLang}&hashes=${encodeURIComponent(hashesParam)}`
				)
			: getApiEndpoint(`/v1/demo/chats?lang=${currentLang}`);

		const response = await fetch(url, { signal: abortController.signal });
		if (!response.ok) {
			if (getAllCommunityDemoChats().length > 0) {
				console.debug(
					`${LOG_PREFIX} Server unavailable, using ${getAllCommunityDemoChats().length} cached community demos`
				);
				communityDemoStore.markAsLoaded();
				return;
			}
			console.warn(`${LOG_PREFIX} Failed to fetch demo chats list:`, response.status);
			communityDemoStore.markAsLoaded();
			return;
		}

		const data = await response.json();
		const demoChatsList = data.demo_chats || [];

		if (demoChatsList.length === 0) {
			console.debug(`${LOG_PREFIX} No community demo chats available from server`);
			communityDemoStore.markAsLoaded();
			return;
		}

		const demosToFetch =
			localHashes.size > 0
				? demoChatsList.filter((d: { updated?: boolean }) => d.updated === true)
				: demoChatsList;

		console.debug(
			`${LOG_PREFIX} Found ${demoChatsList.length} community demos, ${demosToFetch.length} need updates`
		);

		const newlyLoadedIds: string[] = [];

		for (const demoChatMeta of demosToFetch) {
			if (abortController.signal.aborted) {
				console.debug(`${LOG_PREFIX} Demo reload aborted during fetch loop`);
				return;
			}

			const demoId = demoChatMeta.demo_id;
			const contentHash = demoChatMeta.content_hash || '';
			if (!demoId) continue;

			try {
				const chatResponse = await fetch(
					getApiEndpoint(`/v1/demo/chat/${demoId}?lang=${currentLang}`),
					{ signal: abortController.signal }
				);
				if (!chatResponse.ok) {
					console.warn(
						`${LOG_PREFIX} Failed to fetch community demo chat ${demoId}:`,
						chatResponse.status
					);
					continue;
				}

				const chatData = await chatResponse.json();
				const chatDataObj = chatData.chat_data;
				const serverContentHash = chatData.content_hash || contentHash || '';

				if (!chatDataObj || !chatDataObj.chat_id) {
					console.warn(`${LOG_PREFIX} Invalid community demo chat data for ${demoId}`);
					continue;
				}

				const chatId = chatDataObj.chat_id;

				console.debug(
					`${LOG_PREFIX} Community demo ${demoId} loaded: chatId=${chatId}, hash=${serverContentHash.slice(0, 16)}...`
				);

				const title = chatData.title || 'Demo Chat';
				const summary = chatData.summary || '';
				const category = chatData.category || '';
				const icon = chatData.icon || '';
				const followUpSuggestions = chatData.follow_up_suggestions || [];
				const demoChatCategory =
					chatData.demo_chat_category ||
					demoChatMeta.demo_chat_category ||
					'for_everyone';

				const rawMessages = chatDataObj.messages || [];
				const parsedMessages = rawMessages.map(
					(
						msg: {
							role: string;
							content: string;
							category?: string;
							model_name?: string;
							created_at?: number;
						}
					) =>
						({
							message_id: `${demoId}-${rawMessages.indexOf(msg)}`,
							chat_id: chatId,
							role: msg.role || 'user',
							content: msg.content || '',
							category:
								msg.role === 'assistant' ? (msg.category || category) : undefined,
							model_name: msg.role === 'assistant' ? msg.model_name : undefined,
							created_at: msg.created_at || Math.floor(Date.now() / 1000),
							status: 'synced' as const
						}) as Message
				);

				console.debug(
					`${LOG_PREFIX} Community demo ${demoId} has ${parsedMessages.length} messages`
				);

				const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
				const demoIndex = parseInt(demoId.split('-')[1] || '0');
				const displayTimestamp = sevenDaysAgo - demoIndex * 1000 - 10000;

				const chat: Chat = {
					chat_id: chatId,
					title: title,
					encrypted_title: null,
					chat_summary: summary || null,
					follow_up_request_suggestions:
						followUpSuggestions.length > 0
							? JSON.stringify(followUpSuggestions)
							: null,
					icon: icon || null,
					category: category || null,
					demo_chat_category: demoChatCategory || null,
					messages_v: parsedMessages.length,
					title_v: 0,
					draft_v: 0,
					last_edited_overall_timestamp: displayTimestamp,
					unread_count: 0,
					created_at: displayTimestamp,
					updated_at: displayTimestamp,
					processing_metadata: false,
					waiting_for_metadata: false,
					group_key: 'examples'
				};

				const rawEmbeds = chatDataObj.embeds || [];
				const parsedEmbeds = rawEmbeds.map(
					(emb: {
						embed_id?: string;
						type: string;
						content: string;
						created_at?: number;
					}) => ({
						embed_id: emb.embed_id || `${demoId}-embed-${rawEmbeds.indexOf(emb)}`,
						chat_id: chatId,
						type: emb.type || 'unknown',
						content: emb.content || '',
						created_at: emb.created_at || Math.floor(Date.now() / 1000)
					})
				);

				await addCommunityDemo(
					chatId,
					chat,
					parsedMessages,
					serverContentHash,
					parsedEmbeds
				);

				if (parsedEmbeds.length > 0) {
					console.debug(
						`${LOG_PREFIX} Stored ${parsedEmbeds.length} cleartext embeds for community demo ${demoId}`
					);
				}

				newlyLoadedIds.push(demoId);
				console.debug(
					`${LOG_PREFIX} Successfully loaded community demo ${demoId} (chat_id: ${chatId}) into memory and cache`
				);
			} catch (error) {
				if (error instanceof DOMException && error.name === 'AbortError') {
					throw error;
				}
				console.error(`${LOG_PREFIX} Error loading community demo ${demoId}:`, error);
			}
		}

		communityDemoStore.markAsLoaded();
		console.debug(
			`${LOG_PREFIX} Finished loading community demos: ${newlyLoadedIds.length} updated, ${getAllCommunityDemoChats().length} total`
		);
	} catch (error) {
		if (error instanceof DOMException && error.name === 'AbortError') {
			console.debug(`${LOG_PREFIX} Demo reload aborted (superseded by newer reload)`);
			return;
		}
		console.error(`${LOG_PREFIX} Error loading community demo chats from server:`, error);
		communityDemoStore.markAsLoaded();
	}
}
