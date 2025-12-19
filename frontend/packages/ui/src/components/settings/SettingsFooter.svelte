<script lang="ts">
    import { text } from '@repo/ui';
    import { externalLinks, getWebsiteUrl } from '../../config/links';
    import { getApiUrl } from '../../config/api';
    import { getLegalChatBySlug, convertDemoChatToChat, translateDemoChat } from '../../demo_chats';
    import { activeChatStore } from '../../stores/activeChatStore';
    import { createEventDispatcher } from 'svelte';
    
    const dispatch = createEventDispatcher();
    
    /**
     * Get the API documentation URL.
     * Returns the API domain with /docs path appended.
     */
    function getApiDocsUrl(): string {
        return `${getApiUrl()}/docs`;
    }
    
    /**
     * Handle click on a legal document link
     * Opens the legal chat instead of navigating to external URL
     * Stores the chat in IndexedDB so it appears in the sidebar
     */
    async function handleLegalLinkClick(event: MouseEvent, slug: 'imprint' | 'privacy' | 'terms') {
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
        <h3>{@html $text('settings.docs.text')}</h3>
        <a 
            href={getWebsiteUrl('/docs/user-guide')} 
            class="submenu-link" 
            target="_blank" 
            rel="noopener noreferrer"
        >{@html $text('settings.user_guide.text')}</a>
        <a 
            href={getWebsiteUrl('/docs/api-docs')} 
            class="submenu-link" 
            target="_blank" 
            rel="noopener noreferrer"
        >{@html $text('settings.api_docs.text')}</a>
    </div> -->

    <!-- For everyone -->
    <div class="submenu-group">
        <h3>{@html $text('footer.sections.for_everyone.text')}</h3>
        <a
            href={externalLinks.instagram}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.instagram.text')}</a>
        <a
            href={externalLinks.discord}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.discord.text')}</a>
        <a
            href={externalLinks.meetup}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.meetup.text')}</a>
        <a
            href={externalLinks.mastodon}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.mastodon.text')}</a>
        <a
            href={externalLinks.pixelfed}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.pixelfed.text')}</a>
    </div>

    <!-- For developers -->
    <div class="submenu-group">
        <h3>{@html $text('footer.sections.for_developers.text')}</h3>
        <a
            href={getApiDocsUrl()}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.api_docs.text')}</a>
        <a
            href={externalLinks.github}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.github.text')}</a>
        <a
            href={externalLinks.signal}
            class="submenu-link"
            target="_blank"
            rel="noopener noreferrer"
        >{@html $text('settings.signal.text')}</a>
    </div>

    <!-- Contact email -->
    <div class="submenu-group">
        <h3>{@html $text('settings.contact.text')}</h3>
        <a
            href={externalLinks.email}
            class="submenu-link"
        >{@html $text('settings.email.text')}</a>
    </div>

    <div class="submenu-group">
        <h3>{@html $text('settings.legal.text')}</h3>
        <a 
            href={getWebsiteUrl(externalLinks.legal.imprint)} 
            class="submenu-link" 
            onclick={(e) => handleLegalLinkClick(e, 'imprint')}
        >{@html $text('settings.imprint.text')}</a>
        <a 
            href={getWebsiteUrl(externalLinks.legal.privacyPolicy)} 
            class="submenu-link" 
            onclick={(e) => handleLegalLinkClick(e, 'privacy')}
        >{@html $text('settings.privacy.text')}</a>
        <a 
            href={getWebsiteUrl(externalLinks.legal.terms)} 
            class="submenu-link" 
            onclick={(e) => handleLegalLinkClick(e, 'terms')}
        >{@html $text('settings.terms_and_conditions.text')}</a>
    </div>

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
