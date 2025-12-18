<!--
    Share Embed Page

    This page handles shared embed links in the format:
    /share/embed/{embedId}#key={encrypted_blob}

    The embed ID is in the URL path (visible to server for OG tags).
    The encryption key is in the URL fragment (never sent to server).

    Flow:
    1. Extract embed ID from URL params
    2. Extract encryption key from URL fragment (#key=...)
    3. Decrypt the key blob to get the embed encryption key
    4. Request embed data from server (or load from local storage if available)
    5. Decrypt and display the embed in fullscreen view
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { browser } from '$app/environment';
    import { goto } from '$app/navigation';
    import { getApiEndpoint } from '@repo/ui';

    // Get embed ID from URL params
    let embedId = $derived($page.params.embedId);

    // State
    let isLoading = $state(true);
    let error = $state<string | null>(null);
    let requiresPassword = $state(false);
    let passwordInput = $state('');
    let passwordError = $state<string | null>(null);

    /**
     * Extract the encryption key from the URL fragment
     * Format: #key={encrypted_blob}
     */
    function extractKeyFromFragment(): string | null {
        if (!browser) return null;

        const hash = window.location.hash;
        if (hash.startsWith('#key=')) {
            return hash.substring(5); // Remove '#key=' prefix
        }
        return null;
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
            console.warn('[ShareEmbed] Failed to get server time, using client time:', error);
            return Math.floor(Date.now() / 1000);
        }
    }

    /**
     * Fetch embed data from server
     * Returns embed data, child embeds, and embed_keys for the wrapped key architecture
     */
    async function fetchEmbedFromServer(embedId: string): Promise<{ embed: any | null; childEmbeds: any[]; embed_keys: any[] }> {
        try {
            const response = await fetch(getApiEndpoint(`/v1/share/embed/${embedId}`));
            if (!response.ok) {
                throw new Error(`Server returned ${response.status}`);
            }

            const data = await response.json();

            // Check if this is dummy data (non-existent embed)
            // The backend returns dummy data for non-existent embeds to prevent enumeration
            // We can't distinguish real from dummy data, but if decryption fails later, we'll know
            console.debug('[ShareEmbed] Received embed data from server:', {
                embed_id: data.embed?.embed_id,
                has_encrypted_content: !!data.embed?.encrypted_content,
                encrypted_content_length: data.embed?.encrypted_content?.length || 0,
                encrypted_content_preview: data.embed?.encrypted_content?.substring(0, 100) || 'none',
                has_encrypted_type: !!data.embed?.encrypted_type,
                encrypted_type_length: data.embed?.encrypted_type?.length || 0,
                encrypted_type_preview: data.embed?.encrypted_type?.substring(0, 50) || 'none',
                child_embed_count: data.child_embeds?.length || 0,
                embed_keys_count: data.embed_keys?.length || 0,
                all_embed_fields: Object.keys(data.embed || {})
            });

            return {
                embed: data.embed || null,
                childEmbeds: data.child_embeds || [],
                embed_keys: data.embed_keys || []
            };
        } catch (error) {
            console.error('[ShareEmbed] Error fetching embed from server:', error);
            return { embed: null, childEmbeds: [], embed_keys: [] };
        }
    }

    /**
     * Load and decrypt the shared embed
     */
    async function loadSharedEmbed(password?: string) {
        if (!embedId) {
            error = 'Invalid embed link: missing embed ID';
            isLoading = false;
            return;
        }

        try {
            isLoading = true;
            error = null;
            passwordError = null;

            // Extract encryption key from URL fragment
            const encryptedBlob = extractKeyFromFragment();
            if (!encryptedBlob) {
                error = 'Invalid share link: missing encryption key';
                isLoading = false;
                return;
            }

            // Get server time for expiration validation
            const serverTime = await getServerTime();

            // Decrypt the key blob using embed share encryption service
            const { decryptEmbedShareKeyBlob } = await import('@repo/ui');
            const result = await decryptEmbedShareKeyBlob(embedId, encryptedBlob, serverTime, password);

            if (!result.success) {
                if (result.error === 'expired') {
                    error = 'This embed link has expired.';
                } else if (result.error === 'password_required') {
                    requiresPassword = true;
                    isLoading = false;
                    return;
                } else if (result.error === 'invalid_password') {
                    passwordError = 'Invalid password. Please try again.';
                    isLoading = false;
                    return;
                } else {
                    error = 'Failed to decrypt share link. The link may be invalid or expired.';
                }
                isLoading = false;
                return;
            }

            if (!result.embedKey) {
                error = 'Failed to extract embed encryption key.';
                isLoading = false;
                return;
            }

            // Fetch embed data from server
            // The server returns encrypted embed data for existing embeds
            // or dummy encrypted data for non-existent embeds (to prevent enumeration)
            console.debug('[ShareEmbed] Fetching embed data from server...');
            const { embed: fetchedEmbed, childEmbeds: fetchedChildEmbeds, embed_keys: fetchedEmbedKeys } = await fetchEmbedFromServer(embedId);

            if (!fetchedEmbed) {
                error = 'Embed not found. The embed may have been deleted or the link is invalid.';
                isLoading = false;
                return;
            }

            // Validate that we have encrypted content
            if (!fetchedEmbed.encrypted_content) {
                error = 'Embed data is missing encrypted content. The embed may be corrupted.';
                isLoading = false;
                return;
            }

            // Set the embed encryption key in the database cache BEFORE storing embed
            // This allows the embed to be decrypted when stored
            // Pass hashed_chat_id if available so the cache key matches when retrieving
            const { embedStore, decryptWithEmbedKey } = await import('@repo/ui');
            embedStore.setEmbedKeyInCache(embedId, result.embedKey, fetchedEmbed.hashed_chat_id);

            // CRITICAL: Decrypt the embed content immediately to verify it works
            // This ensures the embed key is correct and the content is decryptable
            // Just like shared chats, we decrypt first, then store
            console.debug('[ShareEmbed] Decrypting embed content to verify...');
            console.debug('[ShareEmbed] Embed key length:', result.embedKey.length);
            console.debug('[ShareEmbed] Raw encrypted_content:', {
                value: fetchedEmbed.encrypted_content,
                length: fetchedEmbed.encrypted_content?.length || 0,
                type: typeof fetchedEmbed.encrypted_content,
                firstChars: fetchedEmbed.encrypted_content?.substring(0, 50)
            });
            
            let decryptedContent: string | null = null;
            let decryptedType: string | null = null;
            
            try {
                if (fetchedEmbed.encrypted_content) {
                    // Clean the base64 string - remove whitespace and URL decode if needed
                    let cleanedContent = String(fetchedEmbed.encrypted_content).trim();
                    // Try URL decoding in case it's URL-encoded
                    try {
                        cleanedContent = decodeURIComponent(cleanedContent);
                    } catch {
                        // Not URL-encoded, use as-is
                    }
                    
                    console.debug('[ShareEmbed] Attempting decryption with embed key:', {
                        cleanedContentLength: cleanedContent.length,
                        cleanedContentPreview: cleanedContent.substring(0, 50),
                        embedKeyLength: result.embedKey.length
                    });
                    
                    // Validate base64 format before attempting decryption
                    const base64Regex = /^[A-Za-z0-9+/]*={0,2}$/;
                    if (!base64Regex.test(cleanedContent)) {
                        console.error('[ShareEmbed] Invalid base64 format in encrypted_content:', cleanedContent.substring(0, 50));
                        error = 'Invalid embed data format. The link may be corrupted.';
                        isLoading = false;
                        return;
                    }
                    
                    decryptedContent = await decryptWithEmbedKey(cleanedContent, result.embedKey);
                    if (!decryptedContent) {
                        console.error('[ShareEmbed] Failed to decrypt encrypted_content with embed key');
                        console.error('[ShareEmbed] Debug info:', {
                            contentLength: cleanedContent.length,
                            contentPreview: cleanedContent.substring(0, 100),
                            keyLength: result.embedKey.length
                        });
                        error = 'Failed to decrypt embed content. The link may be invalid or corrupted.';
                        isLoading = false;
                        return;
                    }
                    console.debug('[ShareEmbed] ✅ Successfully decrypted embed content, length:', decryptedContent.length);
                } else {
                    console.error('[ShareEmbed] No encrypted_content field in embed data');
                    error = 'Embed data is missing encrypted content. The embed may be corrupted.';
                    isLoading = false;
                    return;
                }
                
                if (fetchedEmbed.encrypted_type) {
                    // Clean the base64 string for type as well
                    let cleanedType = String(fetchedEmbed.encrypted_type).trim();
                    try {
                        cleanedType = decodeURIComponent(cleanedType);
                    } catch {
                        // Not URL-encoded, use as-is
                    }
                    
                    decryptedType = await decryptWithEmbedKey(cleanedType, result.embedKey);
                    if (decryptedType) {
                        console.debug('[ShareEmbed] ✅ Successfully decrypted embed type:', decryptedType);
                    }
                }
            } catch (decryptError) {
                console.error('[ShareEmbed] Error decrypting embed content:', decryptError);
                console.error('[ShareEmbed] Error details:', {
                    errorMessage: decryptError instanceof Error ? decryptError.message : String(decryptError),
                    encryptedContentLength: fetchedEmbed.encrypted_content?.length || 0,
                    embedKeyLength: result.embedKey.length
                });
                error = 'Failed to decrypt embed content. The link may be invalid or corrupted.';
                isLoading = false;
                return;
            }

            // Store embed in IndexedDB
            // Since we've already decrypted the content, we can store it as plaintext content
            // The embedStore will handle re-encryption if needed, or we store it with the decrypted content
            console.debug('[ShareEmbed] Storing embed in IndexedDB...');
            // Note: embedStore doesn't require initialization - it's ready to use

            // Store main embed first
            // Store with cleaned encrypted_content (we verified it decrypts correctly)
            // The embed key is already in cache, so future decryption will work
            const contentRef = `embed:${embedId}`;
            
            // Clean the encrypted_content before storing (same cleaning as decryption)
            let cleanedEncryptedContent = fetchedEmbed.encrypted_content?.trim() || '';
            try {
                cleanedEncryptedContent = decodeURIComponent(cleanedEncryptedContent);
            } catch {
                // Not URL-encoded, use as-is
            }
            
            let cleanedEncryptedType = fetchedEmbed.encrypted_type?.trim() || '';
            if (cleanedEncryptedType) {
                try {
                    cleanedEncryptedType = decodeURIComponent(cleanedEncryptedType);
                } catch {
                    // Not URL-encoded, use as-is
                }
            }
            
            await embedStore.putEncrypted(contentRef, {
                encrypted_content: cleanedEncryptedContent,
                encrypted_type: cleanedEncryptedType || undefined,
                embed_id: fetchedEmbed.embed_id || embedId,
                status: fetchedEmbed.status || 'finished',
                hashed_chat_id: fetchedEmbed.hashed_chat_id,
                hashed_user_id: fetchedEmbed.hashed_user_id
            }, (decryptedType || (fetchedEmbed.encrypted_type ? 'app-skill-use' : fetchedEmbed.embed_type || 'app-skill-use')) as any, decryptedContent || undefined);

            // Process embed_keys if any - unwrap them with main embed key and store
            // This is for child embeds that have their keys wrapped with the parent embed key
            const { unwrapEmbedKeyWithEmbedKey, computeSHA256 } = await import('@repo/ui');

            // Compute hashed_embed_id for matching embed_keys
            const hashedEmbedId = await computeSHA256(embedId);

            if (fetchedEmbedKeys && fetchedEmbedKeys.length > 0) {
                // Store embed keys and unwrap them with parent embed key
                for (const keyEntry of fetchedEmbedKeys) {
                    try {
                        // Only process key entries for this embed (key_type='embed' with matching hashed_embed_id as parent_embed_id)
                        if (keyEntry.key_type === 'embed' && keyEntry.parent_embed_id === hashedEmbedId) {
                            // Unwrap the child embed key using the parent embed key
                            const childEmbedKey = await unwrapEmbedKeyWithEmbedKey(keyEntry.encrypted_embed_key, result.embedKey);
                            if (childEmbedKey) {
                                // Find matching child embed by computing hashed_embed_id from embed_id
                                // We need to match keyEntry.hashed_embed_id with computed hash of each child embed's embed_id
                                for (const childEmbed of fetchedChildEmbeds) {
                                    if (childEmbed.embed_id) {
                                        const childEmbedIdHash = await computeSHA256(childEmbed.embed_id);
                                        if (childEmbedIdHash === keyEntry.hashed_embed_id) {
                                            // Found matching child embed
                                            // Store the unwrapped child embed key in cache for decryption
                                            // Cache with both hashed_chat_id and 'master' to ensure it can be found
                                            embedStore.setEmbedKeyInCache(
                                                childEmbed.embed_id, 
                                                childEmbedKey,
                                                childEmbed.hashed_chat_id
                                            );
                                            // Also cache with 'master' as fallback (in case getEmbedKey is called without hashedChatId)
                                            embedStore.setEmbedKeyInCache(
                                                childEmbed.embed_id,
                                                childEmbedKey,
                                                undefined // 'master' cache key
                                            );
                                            console.debug('[ShareEmbed] Unwrapped and cached child embed key for:', childEmbed.embed_id, 'with hashed_chat_id:', childEmbed.hashed_chat_id, 'and master fallback');
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    } catch (keyError) {
                        console.warn('[ShareEmbed] Error processing child embed key:', keyError);
                    }
                }

                // Also store the raw embed_keys entries in IndexedDB for future use
                await embedStore.storeEmbedKeys(fetchedEmbedKeys);
                console.debug(`[ShareEmbed] Stored ${fetchedEmbedKeys.length} embed keys`);
            }

            // Store child embeds if any
            if (fetchedChildEmbeds && fetchedChildEmbeds.length > 0) {
                console.debug(`[ShareEmbed] Storing ${fetchedChildEmbeds.length} child embeds...`);
                for (const childEmbed of fetchedChildEmbeds) {
                    try {
                        // Validate child embed has required fields
                        if (!childEmbed.embed_id) {
                            console.warn('[ShareEmbed] Skipping child embed without embed_id');
                            continue;
                        }
                        
                        if (!childEmbed.encrypted_content) {
                            console.warn(`[ShareEmbed] Skipping child embed ${childEmbed.embed_id} without encrypted_content`);
                            continue;
                        }
                        
                        const childContentRef = `embed:${childEmbed.embed_id}`;
                        
                        // Clean encrypted content before storing (same as parent embed)
                        let cleanedChildContent = String(childEmbed.encrypted_content).trim();
                        if (cleanedChildContent) {
                            try {
                                cleanedChildContent = decodeURIComponent(cleanedChildContent);
                            } catch {
                                // Not URL-encoded, use as-is
                            }
                        }
                        
                        let cleanedChildType: string | undefined = undefined;
                        if (childEmbed.encrypted_type) {
                            cleanedChildType = String(childEmbed.encrypted_type).trim();
                            if (cleanedChildType) {
                                try {
                                    cleanedChildType = decodeURIComponent(cleanedChildType);
                                } catch {
                                    // Not URL-encoded, use as-is
                                }
                            }
                        }
                        
                        // Store the child embed with its already-encrypted content (no re-encryption)
                        // The embed_key is already in cache, so decryption will work
                        await embedStore.putEncrypted(childContentRef, {
                            encrypted_content: cleanedChildContent,
                            encrypted_type: cleanedChildType,
                            embed_id: childEmbed.embed_id,
                            status: childEmbed.status || 'finished',
                            hashed_chat_id: childEmbed.hashed_chat_id,
                            hashed_user_id: childEmbed.hashed_user_id
                        }, (childEmbed.encrypted_type ? 'app-skill-use' : childEmbed.embed_type || 'app-skill-use') as any);
                        
                        // Verify child embed can be retrieved and decrypted
                        const verifyChildEmbed = await embedStore.get(childContentRef);
                        if (!verifyChildEmbed || !verifyChildEmbed.content) {
                            console.warn(`[ShareEmbed] Child embed verification failed for ${childEmbed.embed_id} - may not be decryptable`);
                        } else {
                            console.debug(`[ShareEmbed] ✅ Child embed ${childEmbed.embed_id} verified and decrypted successfully`);
                        }
                    } catch (embedError) {
                        console.error(`[ShareEmbed] Error storing child embed ${childEmbed.embed_id}:`, embedError);
                        // Continue with other child embeds even if one fails
                    }
                }
                console.debug(`[ShareEmbed] Completed processing ${fetchedChildEmbeds.length} child embeds`);
            }

            console.debug('[ShareEmbed] Successfully stored embed and child embeds in IndexedDB');

            // Verify the embed can be retrieved and decrypted before proceeding
            // This ensures the embed key is properly cached and the embed is accessible
            const verifyEmbed = await embedStore.get(`embed:${embedId}`);
            if (!verifyEmbed || !verifyEmbed.content) {
                console.warn('[ShareEmbed] Embed verification failed - embed may not be decryptable yet');
                // Continue anyway - handleEmbedFullscreen will retry loading
            } else {
                console.debug('[ShareEmbed] Embed verified and decrypted successfully');
                
                // Also verify child embeds are accessible if this is a composite embed
                if (fetchedChildEmbeds && fetchedChildEmbeds.length > 0) {
                    console.debug('[ShareEmbed] Verifying child embeds are accessible...');
                    let verifiedCount = 0;
                    for (const childEmbed of fetchedChildEmbeds) {
                        if (childEmbed.embed_id) {
                            const childVerify = await embedStore.get(`embed:${childEmbed.embed_id}`);
                            if (childVerify && childVerify.content) {
                                verifiedCount++;
                            } else {
                                console.warn(`[ShareEmbed] Child embed ${childEmbed.embed_id} not accessible yet`);
                            }
                        }
                    }
                    console.debug(`[ShareEmbed] Verified ${verifiedCount}/${fetchedChildEmbeds.length} child embeds are accessible`);
                }
            }
            
            // Small delay to ensure all IndexedDB writes are flushed
            await new Promise(resolve => setTimeout(resolve, 100));

            // Navigate to main app first
            await goto('/');

            // Wait a bit longer for the main app to fully initialize and ActiveChat to be ready
            // This ensures the embedfullscreen event listener is registered
            await new Promise(resolve => setTimeout(resolve, 300));

            // Determine embed type from the fetched embed data
            // encrypted_type indicates app-skill-use embeds, otherwise use the direct embed_type
            let embedType = 'app-skill-use'; // Default for most embeds
            if (fetchedEmbed.encrypted_type) {
                // This is an app-skill-use embed (most common)
                embedType = 'app-skill-use';
            } else {
                // This could be a direct embed like 'web-website', 'videos-video', etc.
                // The exact type will be determined by handleEmbedFullscreen based on decoded content
                embedType = 'app-skill-use'; // Safe default since most embeds are app-skill-use
            }

            // Dispatch embedfullscreen event to open the embed in fullscreen using existing mechanism
            // This reuses the same system that opens embeds when clicking on embed previews
            const embedFullscreenEvent = new CustomEvent('embedfullscreen', {
                detail: {
                    embedId: embedId,
                    // Let handleEmbedFullscreen load and decode the embed content
                    embedData: null,
                    decodedContent: null,
                    embedType: embedType,
                    attrs: null
                }
            });

            console.debug('[ShareEmbed] Dispatching embedfullscreen event for shared embed:', embedId);
            document.dispatchEvent(embedFullscreenEvent);

            isLoading = false;
        } catch (err) {
            console.error('[ShareEmbed] Error loading shared embed:', err);
            error = 'An error occurred while loading the shared embed.';
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

        await loadSharedEmbed(passwordInput);
    }

    // Load embed on mount
    onMount(() => {
        if (embedId) {
            loadSharedEmbed();
        } else {
            error = 'Invalid share link: missing embed ID';
            isLoading = false;
        }
    });
</script>

<div class="share-embed-page">
    {#if isLoading}
        <div class="loading-container">
            <div class="loading-spinner"></div>
            <p>Loading shared embed...</p>
        </div>
    {:else if error}
        <div class="error-container">
            <div class="error-icon">⚠️</div>
            <h1>Unable to Load Embed</h1>
            <p>{error}</p>
            <button onclick={() => goto('/')}>Go to Home</button>
        </div>
    {:else if requiresPassword}
        <div class="password-container">
            <div class="password-icon">🔒</div>
            <h1>Password Required</h1>
            <p>This shared embed is protected with a password.</p>
            <form onsubmit={(e) => { e.preventDefault(); handlePasswordSubmit(); }}>
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
                <button type="submit">Access Embed</button>
            </form>
        </div>
    {/if}
</div>

<style>
    .share-embed-page {
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

    .loading-spinner {
        width: 48px;
        height: 48px;
        border: 4px solid var(--color-grey-20, #e0e0e0);
        border-top-color: var(--color-primary, #6b46c1);
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin: 0 auto 20px;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
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
        color: var(--color-grey-70, #666);
        margin: 0 0 24px;
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

    input[type="password"] {
        padding: 12px;
        border: 2px solid var(--color-grey-30, #d0d0d0);
        border-radius: 8px;
        font-size: 16px;
    }

    input[type="password"].error {
        border-color: var(--color-error, #dc2626);
    }

    .password-error {
        color: var(--color-error, #dc2626);
        font-size: 14px;
        margin: -8px 0 0;
    }
</style>