<!-- frontend/packages/ui/src/components/settings/ContentEmbedDetails.svelte
     App-store detail page for a durable content embed type.

     Data source: CONTENT_EMBED_CATALOG from embedRegistry.generated.ts.
     Example chats: hardcoded public example chats linked by content_embed_examples.
     Verification note: this source file is intentionally part of the deployable
     web app so test-only catalog/audit fixes can be validated on the same head.
     This page never reads the user's private embeds; authenticated saved embeds
     remain in AppEmbedsPanel.svelte under the separate My embeds section.
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { get } from 'svelte/store';
    import { text } from '@repo/ui';
    import ChatPreviewCard from './ChatPreviewCard.svelte';
    import { SettingsSectionHeading } from './elements';
    import { CONTENT_EMBED_CATALOG } from '../../data/embedRegistry.generated';
    import { getExampleChatsForContentEmbed } from '../../demo_chats';
    import { activeChatStore } from '../../stores/activeChatStore';
    import { isMobileView } from '../../stores/uiStateStore';
    import type { Chat } from '../../types/chat';

    interface Props {
        appId: string;
        contentTypeId: string;
    }

    let { appId, contentTypeId }: Props = $props();
    const dispatch = createEventDispatcher();

    let content = $derived(
        CONTENT_EMBED_CATALOG.find(
            (item) => item.appId === appId && item.contentTypeId === contentTypeId,
        ),
    );
    let chatExamples = $derived(getExampleChatsForContentEmbed(appId, contentTypeId));

    function openExampleChat(chat: Chat) {
        const shouldCloseSettings = get(isMobileView);
        if (shouldCloseSettings) {
            activeChatStore.setActiveChat(chat.chat_id);
        } else {
            activeChatStore.setWithoutHashUpdate(chat.chat_id);
        }
        dispatch('chatSelected', { chat });
        window.dispatchEvent(new CustomEvent('globalChatSelected', { detail: { chat } }));
        if (shouldCloseSettings) {
            dispatch('closeSettings');
        }
    }
</script>

<div class="content-details">
    {#if !content}
        <div class="error">{$text('settings.app_store.content.not_found')}</div>
    {:else}
        <section class="section overview-section" data-testid="content-embed-details">
            <SettingsSectionHeading title={content.name} icon={content.icon || 'embed'} />
            <p class="section-description">{content.description}</p>
            <div class="metadata-row" aria-label={content.name}>
                <span>{content.frontendType}</span>
                {#if content.skillId}<span>{appId}.{content.skillId}</span>{/if}
            </div>
        </section>

        {#if chatExamples.length > 0}
            <section class="section examples-section">
                <SettingsSectionHeading title={$text('settings.app_store.content.examples')} icon="embed" />
                <p class="section-description">{$text('settings.app_store.content.examples_prefix')}</p>
                <div class="recent-chats-scroll-container" data-testid="content-embed-example-chats">
                    {#each chatExamples as chat (chat.chat_id)}
                        <ChatPreviewCard {chat} {appId} skillId={content.contentTypeId} onOpen={openExampleChat} />
                    {/each}
                </div>
            </section>
        {/if}
    {/if}
</div>

<style>
    .content-details {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }

    .section {
        margin-top: 2rem;
        padding-left: 0;
    }

    .overview-section {
        margin-top: 0.5rem;
    }

    .section-description {
        margin: 0.35rem 0 0.5rem 0;
        padding: 0;
        font-size: 0.9rem;
        line-height: 1.5;
        color: var(--color-font-secondary);
    }

    .metadata-row {
        display: flex;
        flex-wrap: wrap;
        gap: var(--spacing-2);
        margin-top: var(--spacing-3);
    }

    .metadata-row span {
        display: inline-flex;
        align-items: center;
        border-radius: var(--radius-full);
        padding: var(--spacing-2) var(--spacing-4);
        background: var(--color-grey-10);
        color: var(--color-font-secondary);
        font-size: 0.8rem;
        border: 1px solid var(--color-grey-20);
    }

    .recent-chats-scroll-container {
        display: flex;
        flex-direction: row;
        align-items: center;
        gap: var(--spacing-8);
        overflow-x: auto;
        overflow-y: hidden;
        -webkit-overflow-scrolling: touch;
        scroll-behavior: smooth;
        padding: var(--spacing-2) 0 var(--spacing-3) 0;
        scrollbar-width: none;
        -ms-overflow-style: none;
    }

    .recent-chats-scroll-container::-webkit-scrollbar {
        display: none;
    }

    .error {
        padding: 2rem;
        text-align: center;
        color: var(--error-color, #dc3545);
    }
</style>
