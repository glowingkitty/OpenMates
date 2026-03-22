<script lang="ts">
    import { text } from '@repo/ui';
    import { externalLinks, getWebsiteUrl } from '../../config/links';
    import { getApiUrl } from '../../config/api';
    import { getLegalChatBySlug, convertDemoChatToChat, translateDemoChat } from '../../demo_chats';
    import { activeChatStore } from '../../stores/activeChatStore';
    import { isInSignupProcess } from '../../stores/signupState';
    import { loginInterfaceOpen } from '../../stores/uiStateStore';
    import { createEventDispatcher } from 'svelte';
    import { get } from 'svelte/store';
    
    const dispatch = createEventDispatcher();
    
    // Props using Svelte 5 runes
    // isSelfHosted: When true, hides the legal section (imprint, privacy, terms)
    // because the self-hosted edition is for personal/internal team use only.
    // For such use cases, legal documents (imprint, privacy policy, terms) are not required:
    // - No imprint: only required for commercial/public-facing websites
    // - No privacy policy: GDPR "household exemption" applies to personal/private use
    // - No terms of service: no third-party service relationship exists
    let { isSelfHosted = false }: { isSelfHosted?: boolean } = $props();
    
    /**
     * Get the API documentation URL.
     * Returns the API domain with /docs path appended.
     */
    function getApiDocsUrl(): string {
        return `${getApiUrl()}/docs`;
    }
    
    /**
     * Check if user is currently in login/signup flow
     * Returns true if either signup process is active or login interface is open
     */
    function isInLoginSignupFlow(): boolean {
        return get(isInSignupProcess) || get(loginInterfaceOpen);
    }
    
    /**
     * Get the URL for a legal document link
     * Returns the full website URL for the legal document
     */
    function getLegalUrl(slug: 'imprint' | 'privacy' | 'terms'): string {
        switch (slug) {
            case 'imprint':
                return getWebsiteUrl(externalLinks.legal.imprint);
            case 'privacy':
                return getWebsiteUrl(externalLinks.legal.privacyPolicy);
            case 'terms':
                return getWebsiteUrl(externalLinks.legal.terms);
        }
    }
    
    /**
     * Handle click on a legal document link
     * If user is in login/signup flow, opens the link in a new tab (since chats can't be opened)
     * Otherwise, opens the legal chat instead of navigating to external URL
     */
    async function handleLegalLinkClick(event: MouseEvent, slug: 'imprint' | 'privacy' | 'terms') {
        // Check if user is in login/signup flow
        // If so, open the URL in a new tab instead of trying to open the chat
        if (isInLoginSignupFlow()) {
            // Prevent default navigation to avoid opening in current tab
            event.preventDefault();
            event.stopPropagation();
            
            console.debug(`[SettingsFooter] User in login/signup flow - opening legal link in new tab: ${slug}`);
            const url = getLegalUrl(slug);
            window.open(url, '_blank', 'noopener,noreferrer');
            return;
        }
        
        // Prevent default navigation
        event.preventDefault();
        event.stopPropagation();
        
        console.debug(`[SettingsFooter] Opening legal chat: ${slug}`);
        
        // Get the legal chat by slug
        const legalChat = getLegalChatBySlug(slug);
        if (!legalChat) {
            console.error(`[SettingsFooter] Legal chat not found for slug: ${slug}`);
            return;
        }
        
        // Translate the chat to the user's locale (legal chats skip translation, return as-is)
        const translatedLegalChat = translateDemoChat(legalChat);
        
        // Convert to Chat format
        const chat = convertDemoChatToChat(translatedLegalChat);
        
        // NOTE: Legal chats are now always shown in the sidebar (like demo chats)
        // No need to store them in IndexedDB - they're loaded from static bundle
        // This ensures smooth loading and better UX
        
        // Set active chat in store
        activeChatStore.setActiveChat(chat.chat_id);
        
        // Dispatch chatSelected event that will bubble up to +page.svelte
        // This follows the same pattern as Chats.svelte component
        dispatch('chatSelected', { chat });
        
        // Also dispatch global event so Chats.svelte can mark the chat as active in the sidebar
        window.dispatchEvent(new CustomEvent('globalChatSelected', {
            detail: { chat }
        }));
        
        console.debug(`[SettingsFooter] ✅ Legal chat opened: ${chat.chat_id}`);
        
        // Close settings menu after opening chat (optional UX improvement)
        // The parent Settings component can listen for this if needed
        dispatch('closeSettings');
    }
</script>

<div class="submenu-section">
    <!-- TODO Show again once docs are implemented -->
    <!-- <div class="submenu-group">
        <h3>{@html $text('settings.docs')}</h3>
        <a 
            href={getWebsiteUrl('/docs/user-guide')} 
            class="submenu-link" 
            target="_blank" 
            rel="noopener noreferrer"
        >{@html $text('settings.user_guide')}</a>
        <a 
            href={getWebsiteUrl('/docs/api-docs')} 
            class="submenu-link" 
            target="_blank" 
            rel="noopener noreferrer"
        >{@html $text('settings.api_docs')}</a>
    </div> -->

    <!-- For everyone -->
    <div class="submenu-group">
        <h3>{@html $text('footer.sections.for_everyone')}</h3>
        <a
            href={externalLinks.instagram}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.instagram')}</a>
        <a
            href={externalLinks.discord}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.discord')}</a>
        <a
            href={externalLinks.meetup}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.meetup')}</a>
        <a
            href={externalLinks.mastodon}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.mastodon')}</a>
        <a
            href={externalLinks.pixelfed}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.pixelfed')}</a>
    </div>

    <!-- For developers -->
    <div class="submenu-group">
        <h3>{@html $text('footer.sections.for_developers')}</h3>
        <a
            href={getApiDocsUrl()}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.api_docs')}</a>
        <a
            href={externalLinks.github}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.github')}</a>
        <a
            href={externalLinks.signal}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.signal')}</a>
    </div>

    <!-- Contact email -->
    <div class="submenu-group">
        <h3>{@html $text('settings.contact')}</h3>
        <a
            href={externalLinks.email}
            class="submenu-link"
        >{@html $text('settings.email')}</a>
    </div>

    <!-- Legal section: Only show for non-self-hosted instances -->
    <!-- Self-hosted edition is for personal/internal team use only, so legal docs aren't needed: -->
    <!-- - No imprint: only required for commercial/public-facing websites -->
    <!-- - No privacy policy: GDPR "household exemption" applies to personal/private use -->
    <!-- - No terms of service: no third-party service relationship exists -->
    {#if !isSelfHosted}
        <div class="submenu-group">
            <h3>{@html $text('settings.legal')}</h3>
            <a 
                href={getWebsiteUrl(externalLinks.legal.imprint)} 
                class="submenu-link" 
                onclick={(e) => handleLegalLinkClick(e, 'imprint')}
            >{@html $text('settings.imprint')}</a>
            <a 
                href={getWebsiteUrl(externalLinks.legal.privacyPolicy)} 
                class="submenu-link" 
                onclick={(e) => handleLegalLinkClick(e, 'privacy')}
            >{@html $text('settings.privacy')}</a>
            <a 
                href={getWebsiteUrl(externalLinks.legal.terms)} 
                class="submenu-link" 
                onclick={(e) => handleLegalLinkClick(e, 'terms')}
            >{@html $text('settings.terms_and_conditions')}</a>
        </div>
    {/if}

    <div class="submenu-group">
        <h3>Web app version</h3>
        <span class="version-text">v2025-06-30-15-54-f9a9js</span>
    </div>
</div>

<style>
    .submenu-section {
        padding: 0 16px 16px;
        margin-top: 100px; /* Consistent 100px spacing from content above */
        position: relative; /* Ensure proper positioning in flex layout */
    }

    .submenu-group {
        margin-bottom: 16px;
    }

    .submenu-group h3 {
        color: var(--color-grey-60);
        font-size: 14px;
        font-weight: 600;
        margin: 6px 0;
    }

    .submenu-link {
        display: block;
        color: var(--color-grey-50);
        text-decoration: none;
        padding: 6px 0;
        font-size: 14px;
        transition: color 0.2s ease;
    }

    .submenu-link:hover {
        color: var(--color-primary);
    }

    .version-text {
        color: var(--color-grey-50);
        font-size: 14px;
        padding: 6px 0;
        display: block;
    }
</style>
