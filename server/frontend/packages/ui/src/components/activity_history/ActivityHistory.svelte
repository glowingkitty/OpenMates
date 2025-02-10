<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { _ } from 'svelte-i18n';
    import Chat from './Chat.svelte';
    import { isMenuOpen } from '../../stores/menuState';
    import { isAuthenticated } from '../../stores/authState';
    import { chatDB } from '../../services/db';
    import type { Chat as ChatType } from '../../types/chat';
    import { tooltip } from '../../actions/tooltip';

    const dispatch = createEventDispatcher();

    let chats: ChatType[] = [];
    let loading = true;

    // Group chats by their relative date
    $: groupedChats = chats.reduce<Record<string, ChatType[]>>((groups, chat) => {
        const now = new Date();
        const chatDate = new Date(chat.lastUpdated);
        const diffDays = Math.floor((now.getTime() - chatDate.getTime()) / (1000 * 60 * 60 * 24));
        
        let groupKey = 'Today';
        if (diffDays === 1) {
            groupKey = 'Yesterday';
        } else if (diffDays > 1) {
            groupKey = `${diffDays} days ago`;
        }

        if (!groups[groupKey]) {
            groups[groupKey] = [];
        }
        groups[groupKey].push(chat);
        return groups;
    }, {});

    onMount(async () => {
        try {
            console.log("[ActivityHistory] Initializing database");
            await chatDB.init();
            
            // Check if we have any chats
            const existingChats = await chatDB.getAllChats();
            if (existingChats.length === 0) {
                console.log("[ActivityHistory] No existing chats, loading examples");
                await chatDB.loadExampleChats();
            }
            
            // Load all chats
            chats = await chatDB.getAllChats();
            console.log("[ActivityHistory] Loaded chats:", chats.length);
        } catch (error) {
            console.error("[ActivityHistory] Error loading chats:", error);
        } finally {
            loading = false;
        }
    });

    function handleChatClick(chat: ChatType) {
        console.log("[ActivityHistory] Chat clicked:", chat.id);
        dispatch('chatSelected', { chat });
        
        // Only close the activity history on mobile screens
        if (window.innerWidth < 730) {
            handleClose();
        }
    }

    // Add keydown event handler
    function handleKeyDown(event: KeyboardEvent, chat: ChatType) {
        if (event.key === 'Enter' || event.key === ' ') {
            handleChatClick(chat);
        }
    }

    // Function to handle menu close
    const handleClose = () => {
        isMenuOpen.set(false);
    };
</script>

{#if $isAuthenticated}
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
            <div class="loading-indicator">Loading chats...</div>
        {:else}
            <div class="chat-groups">
                {#each Object.entries(groupedChats) as [groupName, groupChats]}
                    <div class="chat-group">
                        <h2 class="group-title">{groupName}</h2>
                        {#each groupChats as chat}
                            <div role="button" tabindex="0" on:click={() => handleChatClick(chat)} on:keydown={(e) => handleKeyDown(e, chat)}>
                                <Chat {chat} />
                                {#if chat.isDraft}
                                    <span class="draft-indicator">Draft</span>
                                {/if}
                            </div>
                        {/each}
                    </div>
                {/each}
            </div>
        {/if}
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
        text-transform: capitalize;
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
</style>