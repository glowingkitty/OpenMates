<script lang="ts">
    import { onMount, onDestroy, createEventDispatcher } from 'svelte';
    import { _ } from 'svelte-i18n';
    import Chat from './Chat.svelte';
    import { isMenuOpen } from '../../stores/menuState';
    import { authStore } from '../../stores/authStore';
    import { chatDB } from '../../services/db';
    import type { Chat as ChatType } from '../../types/chat';
    import { tooltip } from '../../actions/tooltip';
    import KeyboardShortcuts from '../KeyboardShortcuts.svelte';

    const dispatch = createEventDispatcher();

    let chats: ChatType[] = [];
    let loading = true;

    // Track current chat index
    let currentChatIndex = -1;

    // Modified sorting function to consider draft content
    function sortChatsInGroup(chats: ChatType[]): ChatType[] {
        return chats.sort((a, b) => {
            // Only prioritize drafts that have content
            if (a.isDraft && a.draftContent && (!b.isDraft || !b.draftContent)) return -1;
            if (b.isDraft && b.draftContent && (!a.isDraft || !a.draftContent)) return 1;
            
            // Then unread messages
            if (a.unreadCount && !b.unreadCount) return -1;
            if (!a.unreadCount && b.unreadCount) return 1;
            if (a.unreadCount && b.unreadCount) {
                if (a.unreadCount !== b.unreadCount) {
                    return b.unreadCount - a.unreadCount;
                }
            }
            
            // Finally sort by last updated
            return new Date(b.lastUpdated).getTime() - new Date(a.lastUpdated).getTime();
        });
    }

    // Modified grouping logic to include sorting
    $: groupedChats = chats.reduce<Record<string, ChatType[]>>((groups, chat) => {
        const now = new Date();
        const chatDate = new Date(chat.lastUpdated);
        const diffDays = Math.floor((now.getTime() - chatDate.getTime()) / (1000 * 60 * 60 * 24));
        
        let groupKey: string;
        if (diffDays === 0) {
            groupKey = 'today';
        } else if (diffDays === 1) {
            groupKey = 'yesterday';
        } else {
            groupKey = `days_ago_${diffDays}`;
        }

        if (!groups[groupKey]) {
            groups[groupKey] = [];
        }
        groups[groupKey].push(chat);
        
        // Sort chats in this group
        groups[groupKey] = sortChatsInGroup(groups[groupKey]);
        
        return groups;
    }, {});

    // Function to get localized group title
    function getLocalizedGroupTitle(groupKey: string): string {
        if (groupKey === 'today') {
            return $_('activity.today.text');
        } else if (groupKey === 'yesterday') {
            return $_('activity.yesterday.text');
        } else if (groupKey.startsWith('days_ago_')) {
            const days = groupKey.split('_')[2];
            return $_('activity.days_ago.text', { values: { days } });
        }
        return groupKey;
    }

    // Flatten grouped chats for navigation
    $: flattenedChats = Object.values(groupedChats).flat();

    let languageChangeHandler: () => void;

    onMount(async() => {
        window.addEventListener('chatUpdated', handleChatUpdate);
        
        // Add language change event listener
        languageChangeHandler = () => {
            // Force re-render of the chat groups by triggering a state update
            chats = [...chats];
        };
        window.addEventListener('language-changed', languageChangeHandler);
        
        try {
            console.debug("[ActivityHistory] Initializing database");
            await chatDB.init();
            
            // Check if we have any chats
            const existingChats = await chatDB.getAllChats();
            if (existingChats.length === 0) {
                console.debug("[ActivityHistory] No existing chats, loading examples");
                await chatDB.loadExampleChats();
            }
            
            // Load all chats
            chats = await chatDB.getAllChats();
        } catch (error) {
            console.error("[ActivityHistory] Error loading chats:", error);
        } finally {
            loading = false;
        }
    });

    onDestroy(() => {
        window.removeEventListener('chatUpdated', handleChatUpdate);
        window.removeEventListener('language-changed', languageChangeHandler);
    });

    // Function to navigate to next chat
    async function navigateToNextChat() {
        console.debug("[ActivityHistory] Navigating to next chat");
        if (flattenedChats.length === 0) return;

        // If at the end, don't do anything
        if (currentChatIndex === flattenedChats.length - 1) return;

        // If no current chat, select first one
        if (currentChatIndex === -1) {
            currentChatIndex = 0;
        } else {
            currentChatIndex++;
        }

        const nextChat = flattenedChats[currentChatIndex];
        await handleChatClick(nextChat);
    }

    // Function to navigate to previous chat
    async function navigateToPreviousChat() {
        console.debug("[ActivityHistory] Navigating to previous chat");
        if (flattenedChats.length === 0) return;

        // If at the beginning, don't do anything
        if (currentChatIndex === 0) return;

        // If no current chat, select last one
        if (currentChatIndex === -1) {
            currentChatIndex = flattenedChats.length - 1;
        } else {
            currentChatIndex--;
        }

        const previousChat = flattenedChats[currentChatIndex];
        await handleChatClick(previousChat);
    }

    // Update currentChatIndex when a chat is clicked directly
    async function handleChatClick(chat: ChatType) {
        console.debug("[ActivityHistory] Chat clicked:", chat.id);
        currentChatIndex = flattenedChats.findIndex(c => c.id === chat.id);
        
        // Dispatch a custom event to save any pending draft before switching chats
        const saveDraftEvent = new CustomEvent('saveDraftBeforeSwitch', { bubbles: true });
        window.dispatchEvent(saveDraftEvent);
        
        // Wait a short moment for the draft to be saved
        await new Promise(resolve => setTimeout(resolve, 100));
        
        dispatch('chatSelected', { 
            chat: {
                ...chat,
                draftContent: chat.draftContent ? 
                    (typeof chat.draftContent === 'string' ? 
                        JSON.parse(chat.draftContent) : 
                        chat.draftContent
                    ) : null
            } 
        });
        
        if (window.innerWidth < 730) {
            handleClose();
        }
    }

    // Handle keyboard navigation events
    function handleKeyboardNavigation(event: CustomEvent) {
        if (event.type === 'nextChat') {
            navigateToNextChat();
        } else if (event.type === 'previousChat') {
            navigateToPreviousChat();
        }
    }

    // Function to handle menu close
    const handleClose = () => {
        isMenuOpen.set(false);
    };

    // Add method to update chat list
    async function updateChatList() {
        chats = await chatDB.getAllChats();
    }

    // Listen for chat updates
    function handleChatUpdate(event: CustomEvent) {
        const { chat } = event.detail;
        updateChatList();
    }

    // Add keydown event handler for individual chat items
    function handleKeyDown(event: KeyboardEvent, chat: ChatType) {
        if (event.key === 'Enter' || event.key === ' ') {
            handleChatClick(chat);
        }
    }
</script>

{#if $authStore.isAuthenticated}
    <div class="activity-history">
        <div class="top-buttons-container">
            <div class="top-buttons">
                <button 
                    class="clickable-icon icon_search top-button left" 
                    aria-label={$_('activity.search.text')}
                    use:tooltip
                ></button>
                <button 
                    class="clickable-icon icon_filter top-button center" 
                    aria-label={$_('activity.filter.text')}
                    use:tooltip
                ></button>
                <button 
                    class="clickable-icon icon_close top-button right" 
                    aria-label={$_('activity.close.text')}
                    on:click={handleClose}
                    use:tooltip
                ></button>
            </div>
        </div>

        {#if loading}
            <div class="loading-indicator">{$_('activity.loading_chats.text', { default: 'Loading chats...' })}</div>
        {:else}
            <div class="chat-groups">
                {#each Object.entries(groupedChats) as [groupKey, groupChats] (groupKey)}
                    <div class="chat-group">
                        <h2 class="group-title">{getLocalizedGroupTitle(groupKey)}</h2>
                        {#each groupChats as chat (chat.id)}
                            <div 
                                role="button" 
                                tabindex="0" 
                                class="chat-item"
                                class:active={currentChatIndex === flattenedChats.findIndex(c => c.id === chat.id)}
                                on:click={() => handleChatClick(chat)} 
                                on:keydown={(e) => handleKeyDown(e, chat)}
                            >
                                <Chat {chat} />
                            </div>
                        {/each}
                    </div>
                {/each}
            </div>
        {/if}

        <KeyboardShortcuts 
            on:nextChat={handleKeyboardNavigation}
            on:previousChat={handleKeyboardNavigation}
        />
    </div>
{/if}

<style>
    .activity-history {
        padding: 0;
        position: relative;
        overflow-y: auto;
        height: 100%;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
    }

    .activity-history:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }

    .activity-history::-webkit-scrollbar {
        width: 8px;
    }

    .activity-history::-webkit-scrollbar-track {
        background: transparent;
    }

    .activity-history::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        border: 2px solid transparent;
        transition: background-color 0.2s ease;
    }

    .activity-history:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }

    .activity-history::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
    }

    .top-buttons-container {
        position: sticky;
        top: 0;
        z-index: 10;
        background-color: var(--color-grey-20);
        padding: 20px;
        margin-bottom: 8px;
        border-bottom: 1px solid var(--color-grey-20);
    }

    .top-buttons {
        position: relative;
        height: 32px;
    }

    /* Position buttons in the top bar */
    .top-button {
        position: absolute;
        top: 0;
    }

    .top-button.left {
        left: 0;
    }

    .top-button.center {
        left: 50%;
        transform: translateX(-50%);
    }

    .top-button.right {
        right: 0;
    }

    .chat-groups {
        display: flex;
        flex-direction: column;
        gap: 24px;
        position: relative;
        padding: 0 0 16px 0;
    }

    .chat-group {
        display: flex;
        flex-direction: column;
        gap: 0;
    }

    .group-title {
        font-size: 0.9em;
        color: var(--color-grey-60);
        margin: 0;
        padding: 0 16px;
        font-weight: 500;
        margin-bottom: 8px;
    }

    .loading-indicator {
        text-align: center;
        padding: 20px;
        color: var(--color-grey-60);
    }

    .draft-indicator {
        display: inline-block;
        margin-left: 10px;
        padding: 2px 6px;
        background-color: var(--color-yellow-20);
        color: var(--color-yellow-90);
        border-radius: 4px;
        font-size: 0.8em;
        font-weight: 600;
    }

    .chat-item {
        transition: background-color 0.2s ease;
    }

    .chat-item:hover,
    .chat-item.active {
        background-color: var(--color-grey-30);
        border-radius: 8px;
    }
</style>