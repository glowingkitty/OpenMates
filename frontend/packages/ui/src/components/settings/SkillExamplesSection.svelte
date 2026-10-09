<!-- Real example chats explicitly linked to this app skill. -->
<script lang="ts">
    import { text } from '@repo/ui';
    import { SettingsSectionHeading } from './elements';
    import ChatPreviewCard from './ChatPreviewCard.svelte';
    import { getExampleChatsForSkill } from '../../demo_chats';
    import type { Chat } from '../../types/chat';

    interface Props {
        appId: string;
        skillId: string;
        onOpenExampleChat?: (chatId: string) => void;
    }

    let { appId, skillId, onOpenExampleChat }: Props = $props();
    let chatExamples = $derived(getExampleChatsForSkill(appId, skillId));

    function openExampleChat(chat: Chat) {
        if (onOpenExampleChat) onOpenExampleChat(chat.chat_id);
        else window.open(`/#chat-id=${encodeURIComponent(chat.chat_id)}`, '_blank', 'noopener,noreferrer');
    }
</script>

{#if chatExamples.length > 0}
    <div class="section examples-section">
        <SettingsSectionHeading title={$text('settings.app_store.skills.examples')} icon="chat" />
        <p class="examples-prefix">{$text('settings.app_store.skills.examples_prefix')}</p>
        <div class="recent-chats-scroll-container" data-testid="app-store-example-chats">
            {#each chatExamples as chat (chat.chat_id)}
                <ChatPreviewCard {chat} {appId} {skillId} onOpen={openExampleChat} />
            {/each}
        </div>
    </div>
{/if}

<style>
    .examples-section { margin-top: 2rem; }
    .examples-prefix { margin: 0.5rem 0 0; padding: 0; font-size: 0.9rem; }
    .recent-chats-scroll-container {
        display: flex;
        align-items: center;
        gap: var(--spacing-8);
        overflow-x: auto;
        overflow-y: hidden;
        -webkit-overflow-scrolling: touch;
        scroll-behavior: smooth;
        scrollbar-width: none;
        padding: 0.75rem 0 0.5rem;
        box-sizing: border-box;
        width: 100%;
        max-width: 100%;
    }
    .recent-chats-scroll-container::-webkit-scrollbar { display: none; }
    .recent-chats-scroll-container :global(.resume-chat-large-card) { flex: 0 0 300px; }
</style>
