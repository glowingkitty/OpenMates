<script lang="ts">
    import { _ } from 'svelte-i18n';
    import Chat from './Chat.svelte';
    import { formatDistanceToNow } from 'date-fns';
    import { isMenuOpen } from '../../../lib/stores/menuState';
    import { isAuthenticated } from '../../../lib/stores/authState';

    // Example chats for testing - will be replaced with DB data later
    const exampleChats = [
        {
            id: 'draft1',
            isDraft: true,
            draftContent: 'How do I make a neural network that can...',
            lastUpdated: new Date()
        },
        {
            id: 'draft2',
            isDraft: true,
            draftContent: 'I plan to visit New York soon and wonder what places are great to visit in winter. Any idea?',
            lastUpdated: new Date()
        },
        {
            id: 'chat1',
            title: 'Offline Whisper iOS Integration',
            mates: ['burton'],
            lastUpdated: new Date()
        },
        {
            id: 'chat2',
            title: 'Cardiologist appointments',
            mates: ['lisa', 'sophia'],
            lastUpdated: new Date()
        },
        {
            id: 'chat3',
            title: 'Legality of Ad-skipping Plugins',
            mates: ['burton', 'lisa', 'sophia'],
            lastUpdated: new Date(Date.now() - 24 * 60 * 60 * 1000) // yesterday
        },
        {
            id: 'chat4',
            title: 'US Time Zones and Meeting Scheduling',
            mates: ['sophia'],
            lastUpdated: new Date(Date.now() - 24 * 60 * 60 * 1000)
        },
        {
            id: 'chat5',
            title: 'Gemma 2 2B Hardware Requirements Analysis',
            mates: ['burton', 'lisa'],
            lastUpdated: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000)
        },
        {
            id: 'chat6',
            title: 'Weekly Team Sync Notes',
            mates: ['burton', 'sophia'],
            lastUpdated: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000)
        },
        {
            id: 'chat7',
            title: 'Project Milestone Review',
            mates: ['lisa'],
            lastUpdated: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000)
        },
        {
            id: 'chat8',
            title: 'Database Migration Planning',
            mates: ['burton', 'lisa', 'sophia'],
            lastUpdated: new Date(Date.now() - 4 * 24 * 60 * 60 * 1000)
        },
        {
            id: 'chat9',
            title: 'Customer Feedback Analysis',
            mates: ['sophia', 'lisa'],
            lastUpdated: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000)
        },
        {
            id: 'chat10',
            title: 'AI Model Training Discussion',
            mates: ['burton'],
            lastUpdated: new Date(Date.now() - 6 * 24 * 60 * 60 * 1000)
        }
    ];

    // Group chats by their relative date
    $: groupedChats = exampleChats.reduce<Record<string, typeof exampleChats>>((groups, chat) => {
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
                ></button>
                <button 
                    class="clickable-icon icon_filter top-button center" 
                    aria-label={$_('activity.filter.text')}
                ></button>
                <button 
                    class="clickable-icon icon_close top-button right" 
                    aria-label={$_('activity.close.text')}
                    on:click={handleClose}
                ></button>
            </div>
        </div>

        <div class="chat-groups">
            {#each Object.entries(groupedChats) as [groupName, chats]}
                <div class="chat-group">
                    <h2 class="group-title">{groupName}</h2>
                    {#each chats as chat}
                        <Chat {chat} />
                    {/each}
                </div>
            {/each}
        </div>
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
</style>