<!--
    Share Chat Page
    
    This page handles shared chat links in the format:
    /share/chat/{chatId}#key={encrypted_blob}
    
    The chat ID is in the URL path (visible to server for OG tags).
    The encryption key is in the URL fragment (never sent to server).
    
    Flow:
    1. Extract chat ID from URL params
    2. Extract encryption key from URL fragment (#key=...)
    3. Decrypt the key blob to get the chat encryption key
    4. Request chat data from server (or load from local storage if available)
    5. Decrypt and display the chat
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { browser } from '$app/environment';
	import { get } from 'svelte/store';
	import {
		chatDB,
		activeChatStore,
		decryptShareKeyBlob,
		handleMessageHighlightAddedImpl,
		forcedLogoutInProgress,
		resetForcedLogoutInProgress,
		isLoggingOut,
		type Chat,
		type Message
	} from '@repo/ui';
	import { goto } from '$app/navigation';
	import { getApiEndpoint } from '@repo/ui';
	import {
		dedupeShareChatEmbeds,
		deriveParentByChildEmbeds,
		normalizeEmbedIds,
		type ShareChatEmbedLike
	} from '../shareChatEmbedUtils';

	// CRITICAL: Configure shared chat mode IMMEDIATELY on script load (before any other code runs)
	// This prevents chatDB.init() from blocking during shared chat access.
	// Shared chats don't require authentication, so we should never block on logout state.
	//
	// The problem: chatDB.init() checks for:
	// 1. localStorage 'openmates_needs_cleanup' marker → sets forcedLogoutInProgress to true
	// 2. forcedLogoutInProgress or isLoggingOut flags → throws "Database initialization blocked"
	// 3. Orphan detection: no master key + has chats → sets forcedLogoutInProgress to true
	//
	// For shared chats, ALL of these are false positives because:
	// - Shared chats use URL-embedded encryption keys, not the master key
	// - Having chats without a master key is EXPECTED for shared chat sessions
	//
	// This cleanup must run synchronously at module load time, before any await calls.
	if (browser) {
		// FIRST: Enable skip orphan detection mode on chatDB BEFORE any code can trigger init()
		// This must be the FIRST thing we do to prevent race conditions where other code
		// (imports, components) triggers chatDB.init() before our explicit call
		chatDB.enableSkipOrphanDetection();

		// Clear the localStorage cleanup marker
		if (localStorage.getItem('openmates_needs_cleanup') === 'true') {
			console.debug('[ShareChat] IMMEDIATE: Clearing openmates_needs_cleanup marker');
			localStorage.removeItem('openmates_needs_cleanup');
		}
		// Reset the in-memory flags
		if (get(forcedLogoutInProgress) || get(isLoggingOut)) {
			console.debug('[ShareChat] IMMEDIATE: Resetting logout flags for shared chat access');
			resetForcedLogoutInProgress();
			isLoggingOut.set(false);
		}
	}

	// Get chat ID from URL params
	let chatId = $derived($page.params.chatId);

	// State
	let isLoading = $state(true);
	let error = $state<string | null>(null);
	let requiresPassword = $state(false);
	let passwordInput = $state('');
	let passwordError = $state<string | null>(null);

	type ShareChatServerMessage = {
		id?: string;
		message_id?: string;
		client_message_id?: string;
		chat_id?: string;
		role?: string;
		created_at?: number;
		encrypted_content?: string;
		encrypted_sender_name?: string;
		encrypted_category?: string;
		encrypted_model_name?: string;
		encrypted_pii_mappings?: string;
		user_message_id?: string;
	};

	type ShareChatSubChat = {
		id?: string;
		encrypted_title?: string | null;
		created_at?: number;
		updated_at?: number;
		messages_v?: number;
		title_v?: number;
		last_edited_overall_timestamp?: number;
		unread_count?: number;
		encrypted_chat_summary?: string | null;
		encrypted_icon?: string | null;
		encrypted_category?: string | null;
		parent_id?: string | null;
		is_sub_chat?: boolean;
		budget_limit?: number | null;
		budget_spent?: number;
	};

	type ShareChatHighlight = {
		id?: string;
		chat_id?: string;
		message_id?: string;
		author_user_id?: string;
		key_version?: number | null;
		encrypted_payload?: string;
		created_at?: number;
		updated_at?: number;
	};

	type ShareChatEmbedKey = {
		key_type?: string;
		hashed_chat_id?: string;
		hashed_embed_id?: string;
		encrypted_embed_key?: string;
	};

	type ShareChatCodeRunOutput = {
		id: string;
		chat_id: string;
		embed_id: string;
		author_user_id: string;
		key_version?: number | null;
		encrypted_payload: string;
		created_at: number;
		updated_at: number;
	};

	type ShareChatPayload = {
		chat_id?: string;
		encrypted_title?: string | null;
		encrypted_chat_summary?: string | null;
		encrypted_follow_up_request_suggestions?: string | null;
		encrypted_icon?: string | null;
		encrypted_category?: string | null;
		messages?: Array<string | ShareChatServerMessage>;
		embeds?: ShareChatEmbedLike[];
		embed_keys?: ShareChatEmbedKey[];
		sub_chats?: ShareChatSubChat[];
		code_run_outputs?: ShareChatCodeRunOutput[];
		message_highlights?: ShareChatHighlight[];
		share_pii?: boolean;
		share_highlights?: boolean;
		message_window?: { has_more?: boolean; next_before_timestamp?: number | null; next_before_message_id?: string | null };
	};

	/**
	 * Extract the encryption key and message ID from the URL fragment
	 * Format: #key={encrypted_blob} or #key={encrypted_blob}&messageid={messageId}
	 * Or for public chats: #messageid={messageId}
	 */
	function extractKeyAndMessageFromFragment(): { key: string | null; messageId: string | null } {
		if (!browser) return { key: null, messageId: null };

		const hash = window.location.hash;
		if (hash.startsWith('#key=')) {
			const keyPart = hash.substring(5); // Remove '#key=' prefix
			const parts = keyPart.split('&messageid=');
			const key = parts[0];
			const messageId = parts.length > 1 ? parts[1] : null;
			return { key, messageId };
		} else if (hash.startsWith('#messageid=')) {
			// Public chat with message ID only
			const messageId = hash.substring(11); // Remove '#messageid=' prefix
			return { key: null, messageId };
		}
		return { key: null, messageId: null };
	}

	/**
	 * Get server time for expiration validation
	 * Falls back to client time if server is unreachable
	 */
	async function getServerTime(): Promise<number> {
		try {
			const response = await fetch(getApiEndpoint('/v1/share/time'));
			if (response.ok) {
				const data = await response.json();
				return data.timestamp || data.server_time || Math.floor(Date.now() / 1000);
			}
			throw new Error('Server time request failed');
		} catch (error) {
			console.warn('[ShareChat] Failed to get server time, using client time:', error);
			return Math.floor(Date.now() / 1000);
		}
	}

	/**
	 * Fetch chat data from server
	 * Returns chat, messages, embeds, and embed_keys for the wrapped key architecture
	 */
	async function fetchChatFromServer(
		chatId: string,
		messageId: string | null = null
	): Promise<{
		chat: Chat | null;
		messages: Message[];
		subChats: Chat[];
		embeds: ShareChatEmbedLike[];
		embed_keys: ShareChatEmbedKey[];
		code_run_outputs: ShareChatCodeRunOutput[];
		message_highlights: ShareChatHighlight[];
	}> {
		try {
			let data: ShareChatPayload;
			try {
				const messageParams = new URLSearchParams({ limit: '40' });
				if (messageId) {
					messageParams.set('target_message_id', messageId);
				}
				const [manifestResponse, messagesResponse] = await Promise.all([
					fetch(getApiEndpoint(`/v1/share/chat/${chatId}/manifest`)),
					fetch(getApiEndpoint(`/v1/share/chat/${chatId}/messages?${messageParams.toString()}`))
				]);
				if (!manifestResponse.ok || !messagesResponse.ok) {
					throw new Error(`Windowed share endpoints returned ${manifestResponse.status}/${messagesResponse.status}`);
				}
				const manifestData = await manifestResponse.json();
				const messageWindowData = await messagesResponse.json();
				data = {
					...manifestData,
					messages: messageWindowData.messages || [],
					message_window: {
						has_more: !!messageWindowData.has_more,
						next_before_timestamp: messageWindowData.next_before_timestamp ?? null,
						next_before_message_id: messageWindowData.next_before_message_id ?? null
					}
				};
			} catch (windowedError) {
				console.warn('[ShareChat] Windowed share load failed, falling back to legacy full payload:', windowedError);
				const response = await fetch(getApiEndpoint(`/v1/share/chat/${chatId}`));
				if (!response.ok) {
					throw new Error(`Server returned ${response.status}`);
				}
				data = await response.json();
			}

			// Check if this is dummy data (non-existent chat)
			// The backend returns dummy data for non-existent chats to prevent enumeration
			// We can't distinguish real from dummy data, but if decryption fails later, we'll know
			console.debug('[ShareChat] Received chat data from server:', {
				chat_id: data.chat_id,
				has_title: !!data.encrypted_title,
				message_count: data.messages?.length || 0,
				embed_count: data.embeds?.length || 0,
				embed_keys_count: data.embed_keys?.length || 0
			});

			// Parse messages first (backend returns JSON strings when decrypt_content=False)
			const rawMessages = (data.messages || []) as Array<string | ShareChatServerMessage>;
			const parsedMessages = rawMessages
				.map((msg): ShareChatServerMessage | null => {
					if (typeof msg === 'string') {
						try {
							return JSON.parse(msg) as ShareChatServerMessage;
						} catch (e) {
							console.warn('[ShareChat] Failed to parse message JSON:', e);
							return null;
						}
					}
					return msg;
				})
				.filter((msg): msg is ShareChatServerMessage => msg !== null);

			// Calculate last_edited_overall_timestamp from parsed messages
			const messageTimestamps = parsedMessages
				.map((m) => m.created_at || 0)
				.filter((ts: number) => ts > 0);
			const lastMessageTimestamp =
				messageTimestamps.length > 0
					? Math.max(...messageTimestamps)
					: Math.floor(Date.now() / 1000);

			const resolvedChatId = data.chat_id || chatId;

			// Convert parsed messages to Message format
			const messages: Message[] = parsedMessages.flatMap((messageObj) => {
				const messageId = messageObj.client_message_id || messageObj.message_id || messageObj.id;
				if (!messageId) return [];
				const role =
					messageObj.role === 'assistant' || messageObj.role === 'system' ? messageObj.role : 'user';
				// Prefer client_message_id as the IDB key so that batchSaveMessages() can
				// find the already-stored entry when the owner opens their own share link.
				// The owner's IDB keyed the message by client_message_id at creation time;
				// if we use the Directus `id` here the duplicate-check lookup misses and a
				// second copy is inserted under a different key → duplicate message in the chat.
				// Fall back to `message_id` then `id` for non-owner viewers who have no prior
				// local copy (so any stable ID is fine for them).
				return [{
					message_id: messageId,
					chat_id: resolvedChatId,
					role,
					created_at: messageObj.created_at || Math.floor(Date.now() / 1000),
					status: 'synced' as const,
					encrypted_content: messageObj.encrypted_content || '',
					encrypted_sender_name: messageObj.encrypted_sender_name,
					encrypted_category: messageObj.encrypted_category,
					encrypted_model_name: messageObj.encrypted_model_name, // Model name for assistant messages
					user_message_id: messageObj.user_message_id,
					encrypted_pii_mappings: messageObj.encrypted_pii_mappings,
					client_message_id: messageObj.client_message_id
				}];
			});

			// Get current user ID to check ownership
			// For authenticated users, we need to determine if they own this chat
			// If they don't own it, set user_id to a placeholder to mark it as read-only
			const { authStore } = await import('@repo/ui');
			const { get } = await import('svelte/store');
			const { userDB } = await import('@repo/ui');
			const isAuthenticated = get(authStore).isAuthenticated;

			if (isAuthenticated) {
				try {
					// Try to get current user ID
					await userDB.getUserProfile();

					// For now, we'll check ownership on the backend when sending messages
					// Here we set user_id to a placeholder if we can't verify ownership
					// The actual ownership check happens in ActiveChat component
					// If the chat doesn't have user_id set, it means it's a shared chat from another user
					// We'll leave it undefined for now and let the ownership check in ActiveChat handle it
					// TODO: In the future, we could fetch chat metadata from backend to get owner info

					// For shared chats, we assume the current user is NOT the owner
					// (if they were, they wouldn't need to access via share link)
				} catch (error) {
					console.warn('[ShareChat] Could not determine user ownership:', error);
				}
			}

			// Convert server response to Chat object
			// Note: user_id is intentionally not set here - it will be determined by ownership check
			// If the chat is owned by another user, the ownership check will detect it
			// CRITICAL: Mark as shared_by_others since user accessed via share link (not their own chat)
			const chat: Chat = {
				chat_id: resolvedChatId,
				encrypted_title: data.encrypted_title || null,
				messages_v: messages.length, // Set based on actual message count
				title_v: 0,
				last_edited_overall_timestamp: lastMessageTimestamp,
				unread_count: 0,
				created_at: Math.floor(Date.now() / 1000), // Use current time as fallback
				updated_at: Math.floor(Date.now() / 1000),
				encrypted_chat_summary: data.encrypted_chat_summary || null,
				encrypted_follow_up_request_suggestions:
					data.encrypted_follow_up_request_suggestions || null,
				encrypted_icon: data.encrypted_icon || null, // Icon name encrypted with chat key
				encrypted_category: data.encrypted_category || null, // Category name encrypted with chat key
				// user_id is intentionally not set - will be determined by ownership check in ActiveChat
				// If chat is from another user, ownership check will fail and chat will be read-only
				// SHARING: Mark as shared by others and assign to shared_by_others group for sidebar
				is_shared_by_others: true,
				share_pii: data.share_pii ?? false,
				share_highlights: data.share_highlights ?? true,
				shared_message_window_has_more_before: !!data.message_window?.has_more,
				shared_message_window_next_before_timestamp: data.message_window?.next_before_timestamp ?? null,
				shared_message_window_next_before_message_id: data.message_window?.next_before_message_id ?? null,
				group_key: 'shared_by_others'
			};

			const subChats: Chat[] = ((data.sub_chats || []) as ShareChatSubChat[]).flatMap((subChat) => {
				if (!subChat.id) return [];
				const createdAt = subChat.created_at || Math.floor(Date.now() / 1000);
				return [{
					chat_id: subChat.id,
					encrypted_title: subChat.encrypted_title || null,
					messages_v: subChat.messages_v ?? 0,
					title_v: subChat.title_v ?? 0,
					last_edited_overall_timestamp: subChat.last_edited_overall_timestamp || subChat.updated_at || createdAt,
					unread_count: subChat.unread_count ?? 0,
					created_at: createdAt,
					updated_at: subChat.updated_at || createdAt,
					encrypted_chat_summary: subChat.encrypted_chat_summary || null,
					encrypted_icon: subChat.encrypted_icon || null,
					encrypted_category: subChat.encrypted_category || null,
					parent_id: resolvedChatId,
					is_sub_chat: true,
					is_shared_by_others: true,
					share_pii: data.share_pii ?? false,
					share_highlights: data.share_highlights ?? true,
					group_key: 'shared_by_others',
					budget_limit: subChat.budget_limit ?? null,
					budget_spent: subChat.budget_spent ?? 0
				}];
			});

			return {
				chat,
				messages,
				subChats,
				embeds: (data.embeds || []) as ShareChatEmbedLike[],
				embed_keys: (data.embed_keys || []) as ShareChatEmbedKey[],
				code_run_outputs: (data.code_run_outputs || []) as ShareChatCodeRunOutput[],
				message_highlights: (data.message_highlights || []) as ShareChatHighlight[]
			};
		} catch (error) {
			console.error('[ShareChat] Error fetching chat from server:', error);
			return { chat: null, messages: [], subChats: [], embeds: [], embed_keys: [], code_run_outputs: [], message_highlights: [] };
		}
	}

	async function validateSharedEmbedRefs(
		chatId: string,
		messages: Message[],
		keyBytes: Uint8Array
	): Promise<void> {
		const { decryptWithChatKey, embedStore } = await import('@repo/ui');
		const refs = new Set<string>();

		for (const message of messages) {
			if (!message.encrypted_content) continue;
			const plaintext = await decryptWithChatKey(message.encrypted_content, keyBytes, {
				chatId,
				fieldName: 'shared_chat_embed_ref_validation'
			});
			if (!plaintext) continue;

			for (const match of plaintext.matchAll(/embed:([A-Za-z0-9._-]+)/g)) {
				refs.add(match[1]);
			}
		}

		if (refs.size === 0) return;

		const unresolved: string[] = [];
		for (const ref of refs) {
			const resolved = embedStore.resolveByRef(ref) || await embedStore.resolveByRefDeep(ref);
			if (!resolved) unresolved.push(ref);
		}

		if (unresolved.length > 0) {
			console.warn('[ShareChat] Unresolved embed refs after cold-load hydration:', {
				chatId,
				unresolved,
				totalRefs: refs.size
			});
		}
	}

	/**
	 * Load and decrypt the shared chat
	 */
	async function loadSharedChat(password?: string) {
		if (!chatId) {
			error = 'Invalid chat link: missing chat ID';
			isLoading = false;
			return;
		}

		try {
			isLoading = true;
			error = null;
			passwordError = null;

			// Double-check: Reset logout flags again in case something re-triggered them
			// The main reset happens at module load time (top of script), but we ensure
			// the flags are still cleared before calling chatDB.init()
			if (browser && (get(forcedLogoutInProgress) || get(isLoggingOut))) {
				console.debug('[ShareChat] Re-clearing logout flags before init');
				localStorage.removeItem('openmates_needs_cleanup');
				resetForcedLogoutInProgress();
				isLoggingOut.set(false);
			}

			// Extract encryption key and message ID from URL fragment
			const { key: encryptedBlob, messageId } = extractKeyAndMessageFromFragment();
			if (!encryptedBlob) {
				error = 'Invalid share link: missing encryption key';
				isLoading = false;
				return;
			}

			// Get server time for expiration validation
			const serverTime = await getServerTime();

			// Decrypt the key blob
			const result = await decryptShareKeyBlob(chatId, encryptedBlob, serverTime, password);

			if (!result.success) {
				if (result.error === 'password_required') {
					requiresPassword = true;
					isLoading = false;
					return;
				} else if (result.error === 'invalid_password') {
					passwordError = 'Incorrect password. Please try again.';
					isLoading = false;
					return;
				} else if (result.error === 'expired') {
					error = 'This chat link has expired.';
					isLoading = false;
					return;
				} else {
					error = 'Failed to decrypt share link. The link may be invalid.';
					isLoading = false;
					return;
				}
			}

			if (!result.chatEncryptionKey) {
				error = 'Failed to extract chat encryption key.';
				isLoading = false;
				return;
			}

			// ── Owner shortcut ──────────────────────────────────────────────
			// If the authenticated user already owns this chat locally (it's in
			// IndexedDB with a valid master-key-wrapped key), skip the share-page
			// flow entirely and redirect to the normal chat view. This prevents
			// the share-link key from overwriting the correct master-key-derived
			// key and avoids corrupting the chat record with share-page defaults
			// (is_shared_by_others, missing user_id, wrong version counters).
			const { authStore } = await import('@repo/ui');
			const isAuth = get(authStore).isAuthenticated;
			if (isAuth) {
				try {
					await chatDB.init({ skipOrphanDetection: true });
					const existingChat = await chatDB.getChat(chatId);
					if (existingChat && existingChat.encrypted_chat_key) {
						// The owner already has this chat with a wrapped key — the
						// normal chat view can decrypt it via the master key.
						console.info(
							'[ShareChat] Owner shortcut: chat already exists locally with ' +
								'encrypted_chat_key — redirecting to normal view instead of ' +
								'overwriting with share-link key.'
						);
						const { key: _k, messageId } = extractKeyAndMessageFromFragment();
						const targetUrl = messageId
							? `/#chat-id=${chatId}&messageid=${messageId}`
							: `/#chat-id=${chatId}`;
						sessionStorage.setItem('openmates_shared_chat_redirect', chatId);
						await goto(targetUrl);
						isLoading = false;
						return;
					}
				} catch (ownerCheckError) {
					console.warn(
						'[ShareChat] Owner check failed, falling through to share flow:',
						ownerCheckError
					);
				}
			}

			// Fetch chat data from server
			// The server returns encrypted chat data for existing chats
			// or dummy encrypted data for non-existent chats (to prevent enumeration)
			console.debug('[ShareChat] Fetching chat data from server...');
			const {
				chat: fetchedChat,
				messages: fetchedMessages,
				subChats: fetchedSubChats,
				embeds: fetchedEmbeds,
				embed_keys: fetchedEmbedKeys,
				code_run_outputs: fetchedCodeRunOutputs,
				message_highlights: fetchedMessageHighlights
			} = await fetchChatFromServer(chatId, messageId);

			if (!fetchedChat) {
				error = 'Chat not found. The chat may have been deleted or the link is invalid.';
				isLoading = false;
				return;
			}

			// Convert the chat encryption key from base64 string to Uint8Array
			// The key is stored as base64 in the blob, but chatDB expects Uint8Array
			const keyBytes = Uint8Array.from(atob(result.chatEncryptionKey), (c) => c.charCodeAt(0));

			// The API deliberately returns deterministic dummy ciphertext for missing/unshared
			// chats to prevent ID enumeration. Validate that the URL key can decrypt at
			// least one returned field before storing anything locally; otherwise stale
			// links become dummy chats that render "[Content decryption failed]".
			const validationCiphertext =
				fetchedMessages.find((message) => !!message.encrypted_content)?.encrypted_content ||
				fetchedChat.encrypted_title ||
				fetchedChat.encrypted_chat_summary;
			if (validationCiphertext) {
				const { decryptWithChatKey } = await import('@repo/ui');
				const validationPlaintext = await decryptWithChatKey(validationCiphertext, keyBytes, {
					chatId,
					fieldName: 'share_chat_validation'
				});
				if (validationPlaintext === null) {
					error = 'This shared chat is no longer available or the link is invalid.';
					isLoading = false;
					return;
				}
			}

			// Set the chat encryption key in the database cache BEFORE storing chat
			// This allows the chat to be decrypted when stored.
			// Source = 'share_link' so the immutability guard can block this if a
			// master-key-derived key already exists (owner opening their own share link).
			chatDB.setChatKey(chatId, keyBytes, 'share_link');

			// CRITICAL: Persist the shared chat key to IndexedDB so it survives page reloads
			// This is essential for unauthenticated users who can't derive keys from a master key.
			// Without this, the key would be lost on reload since it's only in memory.
			const { saveSharedChatKey } = await import('@repo/ui');
			await saveSharedChatKey(chatId, keyBytes);
			console.debug('[ShareChat] Persisted shared chat key to IndexedDB for chat:', chatId);

			// Store chat and messages in IndexedDB
			// CRITICAL: Skip orphan detection for shared chats. Shared chats are stored
			// without a master key (they use URL-embedded encryption keys), so the
			// "no master key but has chats" condition is expected and NOT orphan data.
			console.debug('[ShareChat] Storing chat and messages in IndexedDB...');
			await chatDB.init({ skipOrphanDetection: true });

			// Store chat metadata first (addChat creates its own transaction)
			await chatDB.addChat(fetchedChat);
			for (const subChat of fetchedSubChats) {
				chatDB.setChatKey(subChat.chat_id, keyBytes, 'share_link');
				await saveSharedChatKey(subChat.chat_id, keyBytes);
				await chatDB.addChat(subChat);
			}
			if (fetchedSubChats.length > 0) {
				console.debug(`[ShareChat] Stored ${fetchedSubChats.length} shared sub-chat metadata rows`);
			}

			// Store messages if any (batchSaveMessages creates its own transaction)
			if (fetchedMessages.length > 0) {
				await chatDB.batchSaveMessages(fetchedMessages);
				console.debug(`[ShareChat] Stored ${fetchedMessages.length} messages`);
			}

			if (fetchedMessageHighlights.length > 0) {
				for (const highlight of fetchedMessageHighlights) {
					if (
						!highlight.id ||
						!highlight.chat_id ||
						!highlight.message_id ||
						!highlight.author_user_id ||
						!highlight.encrypted_payload ||
						highlight.created_at == null
					) {
						continue;
					}

					await handleMessageHighlightAddedImpl({
						chat_id: highlight.chat_id,
						message_id: highlight.message_id,
						id: highlight.id,
						author_user_id: highlight.author_user_id,
						key_version: highlight.key_version ?? null,
						encrypted_payload: highlight.encrypted_payload,
						created_at: highlight.created_at
					});
				}
				console.debug(`[ShareChat] Stored ${fetchedMessageHighlights.length} message highlights`);
			}

			// Process embed_keys first - unwrap them with chat key and store
			// This is the wrapped key architecture: embed_keys contain AES(embed_key, chat_key)
			// We unwrap to get embed_key, which is used to decrypt embed content
			const { embedStore, unwrapEmbedKeyWithChatKey } = await import('@repo/ui');
			const { computeSHA256 } = await import('@repo/ui');

			// Compute hashed_chat_id for matching embed_keys
			const hashedChatId = await computeSHA256(chatId);

			if (fetchedEmbedKeys && fetchedEmbedKeys.length > 0) {
				// Store embed keys and unwrap them with chat key
				for (const keyEntry of fetchedEmbedKeys) {
					try {
						// Only process key entries for this chat (key_type='chat' with matching hashed_chat_id)
						if (keyEntry.key_type === 'chat' && keyEntry.hashed_chat_id === hashedChatId && keyEntry.encrypted_embed_key) {
							// Unwrap the embed key using the chat key
							const embedKey = await unwrapEmbedKeyWithChatKey(
								keyEntry.encrypted_embed_key,
								keyBytes
							);
							if (embedKey) {
								// Find matching embed by computing hashed_embed_id from embed_id
								// We need to match keyEntry.hashed_embed_id with computed hash of each embed's embed_id
								for (const embed of fetchedEmbeds) {
									if (embed.embed_id) {
										const embedIdHash = await computeSHA256(embed.embed_id);
										if (embedIdHash === keyEntry.hashed_embed_id) {
											// Store the unwrapped embed key in cache for decryption
											embedStore.setEmbedKeyInCache(embed.embed_id, embedKey, hashedChatId);
											console.debug(
												'[ShareChat] Unwrapped and cached embed key for:',
												embed.embed_id
											);
											break;
										}
									}
								}
							}
						}
					} catch (keyError) {
						console.warn('[ShareChat] Error processing embed key:', keyError);
					}
				}

				// Also store the raw embed_keys entries in IndexedDB for future use
				await embedStore.storeEmbedKeys(fetchedEmbedKeys as unknown as Parameters<typeof embedStore.storeEmbedKeys>[0]);
				console.debug(`[ShareChat] Stored ${fetchedEmbedKeys.length} embed keys`);
			}

			// Store embeds if any
			const uniqueFetchedEmbeds = dedupeShareChatEmbeds(fetchedEmbeds);
			if (uniqueFetchedEmbeds.length > 0) {
				// Ensure child embeds can resolve the parent key in shared-chat (non-auth) flows.
				// The EmbedStore can reuse a parent's embed key for a child embed if `parent_embed_id` is stored.
				// Some payloads include `parent_embed_id` directly; otherwise we can derive it from parent `embed_ids`.
				const derivedParentByChild = deriveParentByChildEmbeds(uniqueFetchedEmbeds);

				// CRITICAL: Pre-cache embed keys for child embeds.
				// putEncrypted tries to decrypt content to extract embed_ref, which requires
				// the embed key. For child embeds, getEmbedKey does getRawEntry(childContentRef)
				// to find parent_embed_id, but the child hasn't been stored yet at that point.
				// By pre-caching the parent's key under the child's ID, getEmbedKey finds it
				// immediately in cache without needing the IDB lookup chain.
				for (const [childId, parentId] of derivedParentByChild.entries()) {
					const parentKey = embedStore.getEmbedKeyFromCache(parentId, hashedChatId);
					if (parentKey) {
						embedStore.setEmbedKeyInCache(childId, parentKey, hashedChatId);
					}
				}

				// CRITICAL: Sort embeds so parents are processed BEFORE children.
				// putEncrypted tries to decrypt content to extract embed_ref for the in-memory
				// ref→id index. For child embeds, getEmbedKey needs the parent's key, which
				// requires the parent to already be in the memory cache (via a prior putEncrypted).
				// Without this ordering, child embeds can't resolve their parent's key, so their
				// content can't be decrypted and embed_ref never gets registered — causing
				// "Loading preview..." stuck state in EmbedReferencePreview / EmbedPreviewLarge.
				const parentEmbeds = uniqueFetchedEmbeds.filter(
					(e: ShareChatEmbedLike) =>
						normalizeEmbedIds(e.embed_ids).length > 0
				);
				const childEmbeds = uniqueFetchedEmbeds.filter(
					(e: ShareChatEmbedLike) =>
						normalizeEmbedIds(e.embed_ids).length === 0
				);
				const sortedEmbeds = [...parentEmbeds, ...childEmbeds];

				for (const embed of sortedEmbeds) {
					try {
						const contentRef = `embed:${embed.embed_id}`;
						// Store the embed with its already-encrypted content (no re-encryption)
						// The embed_key is already in cache, so decryption will work
						await embedStore.putEncrypted(
							contentRef,
							{
								encrypted_content: embed.encrypted_content,
								encrypted_type: embed.encrypted_type,
								embed_id: embed.embed_id,
								status: embed.status || 'finished',
								hashed_chat_id: embed.hashed_chat_id,
								hashed_user_id: embed.hashed_user_id,
								embed_ids: normalizeEmbedIds(embed.embed_ids),
								parent_embed_id: embed.parent_embed_id || (embed.embed_id ? derivedParentByChild.get(embed.embed_id) : undefined)
							},
							embed.encrypted_type ? 'app-skill-use' : embed.embed_type || 'app-skill-use'
						);
					} catch (embedError) {
						console.warn(`[ShareChat] Error storing embed ${embed.embed_id}:`, embedError);
					}
				}
				console.debug(
					`[ShareChat] Stored ${uniqueFetchedEmbeds.length}/${fetchedEmbeds.length} embeds (${parentEmbeds.length} parents first, then ${childEmbeds.length} children)`
				);
			}

			if (fetchedCodeRunOutputs.length > 0) {
				const { handleCodeRunOutputSyncedImpl } = await import('@repo/ui');
				for (const output of fetchedCodeRunOutputs) {
					await handleCodeRunOutputSyncedImpl(output);
				}
				console.debug(`[ShareChat] Stored ${fetchedCodeRunOutputs.length} code run outputs`);
			}

			await validateSharedEmbedRefs(chatId, fetchedMessages, keyBytes);

			// NOTE: Shared chat keys are now persisted in IndexedDB via sharedChatKeyStorage
			// This allows unauthenticated users to reload the tab and still access the chat.
			// The sessionStorage tracking has been removed since keys persist until explicitly deleted.
			// For authenticated users, the chat will sync normally via the regular chat sync mechanism.

			console.debug('[ShareChat] Successfully stored chat in IndexedDB');

			// Set active chat in store BEFORE dispatching events
			activeChatStore.setActiveChat(chatId);

			// CRITICAL: Dispatch event to notify Chats.svelte that a new shared chat was added
			// This ensures the chat appears in the sidebar immediately
			// Import the event constant from @repo/ui
			const { LOCAL_CHAT_LIST_CHANGED_EVENT } = await import('@repo/ui');
			window.dispatchEvent(
				new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
					detail: { chat_id: chatId, sharedChatAdded: true }
				})
			);
			console.debug(
				'[ShareChat] Dispatched LOCAL_CHAT_LIST_CHANGED_EVENT for shared chat:',
				chatId
			);

			// CRITICAL: Small delay to ensure IndexedDB transactions are fully committed
			// before navigating to the main page. Without this, there's a race condition
			// where the main page tries to read from IndexedDB before the transaction is visible.
			await new Promise((resolve) => setTimeout(resolve, 50));

			// CRITICAL: Set sessionStorage flag so root +page.svelte knows this navigation
			// came from the share page. Without this, the forced-logout path in +page.svelte
			// clears the hash for non-public chat IDs, breaking the shared chat deep link.
			// The flag is consumed (removed) by +page.svelte after reading it.
			sessionStorage.setItem('openmates_shared_chat_redirect', chatId);

			// Navigate to main app with the chat loaded
			// This allows the user to see the chat in the normal interface
			// The chat key is already set in the cache, so the chat will be decrypted when loaded
			// Include message ID if provided for highlighting/scrolling
			// NOTE: Must include leading '/' to navigate to root, not just update hash on current page
			const targetUrl = messageId
				? `/#chat-id=${chatId}&messageid=${messageId}`
				: `/#chat-id=${chatId}`;
			console.debug('[ShareChat] Navigating to:', targetUrl);
			await goto(targetUrl);

			isLoading = false;
		} catch (err) {
			console.error('[ShareChat] Error loading shared chat:', err);
			error = 'An error occurred while loading the shared chat.';
			isLoading = false;
		}
	}

	/**
	 * Handle password submission
	 */
	async function handlePasswordSubmit() {
		if (!passwordInput || passwordInput.length === 0) {
			passwordError = 'Password is required';
			return;
		}

		await loadSharedChat(passwordInput);
	}

	// Load chat on mount
	onMount(() => {
		if (chatId) {
			loadSharedChat();
		} else {
			error = 'Invalid share link: missing chat ID';
			isLoading = false;
		}
	});
</script>

<div class="share-chat-page">
	{#if isLoading}
		<div class="loading-container">
			<img class="openmates-logo" src="/favicon.svg" alt="OpenMates" />
			<p>Decrypting chat…</p>
			<div class="loading-spinner"></div>
		</div>
	{:else if error}
		<div class="error-container">
			<div class="error-icon">⚠️</div>
			<h1>Unable to Load Chat</h1>
			<p>{error}</p>
			<button onclick={() => goto('/')}>Go to Home</button>
		</div>
	{:else if requiresPassword}
		<div class="password-container">
			<div class="password-icon">🔒</div>
			<h1>Password Required</h1>
			<p>This shared chat is protected with a password.</p>
			<form
				onsubmit={(e) => {
					e.preventDefault();
					handlePasswordSubmit();
				}}
			>
				<input
					type="password"
					bind:value={passwordInput}
					placeholder="Enter password"
					maxlength="10"
					class:error={!!passwordError}
				/>
				{#if passwordError}
					<p class="password-error">{passwordError}</p>
				{/if}
				<button type="submit">Access Chat</button>
			</form>
		</div>
	{/if}
</div>

<style>
	.share-chat-page {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 20px;
		background-color: var(--color-grey-5, #f5f5f5);
	}

	.loading-container,
	.error-container,
	.password-container {
		max-width: 500px;
		width: 100%;
		text-align: center;
		padding: 40px;
		background: white;
		border-radius: 12px;
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
	}

	.loading-container {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
	}

	.loading-spinner {
		width: 48px;
		height: 48px;
		border: 4px solid var(--color-grey-20, #e0e0e0);
		border-top-color: var(--color-primary, #6b46c1);
		border-radius: 50%;
		animation: spin 1s linear infinite;
		margin: 0 auto;
	}

	.openmates-logo {
		width: 96px;
		height: 96px;
		margin-bottom: 18px;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.error-icon,
	.password-icon {
		font-size: 64px;
		margin-bottom: 20px;
	}

	h1 {
		font-size: 24px;
		margin: 0 0 12px;
		color: var(--color-grey-100, #1a1a1a);
	}

	p {
		font-size: 16px;
		font-family: var(--font-primary, 'Lexend Deca', sans-serif);
		text-align: center;
		color: var(--color-grey-70, #666);
		margin: 0 0 18px;
	}

	button {
		padding: 12px 24px;
		background-color: var(--color-primary, #6b46c1);
		color: white;
		border: none;
		border-radius: 8px;
		font-size: 16px;
		font-weight: 500;
		cursor: pointer;
		transition: background-color 0.2s ease;
	}

	button:hover {
		background-color: var(--color-primary-dark, #5a36b2);
	}

	form {
		display: flex;
		flex-direction: column;
		gap: 12px;
		margin-top: 24px;
	}

	input[type='password'] {
		padding: 12px;
		border: 2px solid var(--color-grey-30, #d0d0d0);
		border-radius: 8px;
		font-size: 16px;
	}

	input[type='password'].error {
		border-color: var(--color-error, #dc2626);
	}

	.password-error {
		color: var(--color-error, #dc2626);
		font-size: 14px;
		margin: -8px 0 0;
	}
</style>
