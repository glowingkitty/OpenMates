<!--
  frontend/packages/ui/src/components/settings/SkillExamplesSection.svelte

  App-store "Examples" section shown inside SkillDetails.svelte. Prefer real
  example chats linked to the given skill and render them with the same large
  preview card used by the new-chat "Continue where you left off" carousel.
  Falls back to the older curated embed preview fixtures while chat coverage is
  still incomplete.

  Data flow:
    - skillStoreExamplesResolver looks up the preview component and the
      `*Preview.examples.ts` fixture file via the embed registry.
    - Each example is a flat props object (same shape as *.preview.ts).
    - For the preview card we spread the props into the preview component.
    - For the fullscreen we publish a synthetic EmbedFullscreenState to
      `skillStoreExampleFullscreenStore`. ActiveChat subscribes to that
      store and mounts the fullscreen inside its normal container, so
      behaviour matches regular chat embeds (including child drilldown
      into WebsiteEmbedFullscreen / VideoEmbedFullscreen, download, copy).

  Hidden entirely when no examples file exists for the skill.
-->

<script lang="ts">
    import type { Component } from 'svelte';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { SettingsSectionHeading } from './elements';
    import ChatPreviewCard from './ChatPreviewCard.svelte';
    import {
        loadSkillExamples,
        hasSkillExamples,
    } from '../../services/skillStoreExamplesResolver';
    import { openSkillStoreExampleFullscreen } from '../../stores/skillStoreExampleFullscreenStore';
    import { activeChatStore } from '../../stores/activeChatStore';
    import { isMobileView } from '../../stores/uiStateStore';
    import { getExampleChatsForSkill } from '../../demo_chats';
    import type { Chat } from '../../types/chat';
    import { get } from 'svelte/store';

    interface Props {
        appId: string;
        skillId: string;
    }

    let { appId, skillId }: Props = $props();
    const dispatch = createEventDispatcher();

    let PreviewComponent = $state<Component | null>(null);
    let examples = $state<Array<Record<string, unknown>>>([]);
    let chatExamples = $derived(getExampleChatsForSkill(appId, skillId));

    // Whether the skill has an examples bundle at all — controls section visibility.
    let available = $derived(hasSkillExamples(appId, skillId));

    $effect(() => {
        // Reset on skill change
        PreviewComponent = null;
        examples = [];

        if (!available) return;

        const currentAppId = appId;
        const currentSkillId = skillId;

        loadSkillExamples(currentAppId, currentSkillId)
            .then((bundle) => {
                if (!bundle) return;
                // Guard against stale async resolution after prop change
                if (currentAppId !== appId || currentSkillId !== skillId) return;
                PreviewComponent = bundle.previewComponent;
                examples = bundle.examples;
            })
            .catch((err) => {
                console.error('[SkillExamplesSection] Failed to load examples', err);
            });
    });

    /**
     * Resolve an example's localisable query label.
     *
     * Each example may carry an optional `query_translation_key` that
     * points at an entry in `settings/app_store_examples.yml`. When set,
     * we swap the raw English `query` with the translated string so the
     * card matches the user's UI language. The underlying provider
     * results stay authentic (we never translate page titles or URLs).
     */
    function resolveQuery(example: Record<string, unknown>): string | undefined {
        const key = example.query_translation_key;
        if (typeof key === 'string' && key) {
            const translated = $text(key);
            // $text falls back to the raw key when no translation exists;
            // treat that as "no translation available" and use the
            // literal English `query` we captured at fixture time.
            if (translated && translated !== key && !translated.startsWith('[T:')) return translated;
        }
        const raw = example.query;
        return typeof raw === 'string' ? raw : undefined;
    }

    /**
     * Build the `decodedContent` payload that the fullscreen component
     * reads from `data.decodedContent`. Mirrors the shape produced by
     * the real app-skill-use pipeline: app/skill ids + the flat example
     * props, with `query` replaced by the locale-resolved label.
     */
    function buildDecodedContent(flat: Record<string, unknown>): Record<string, unknown> {
        const resolvedQuery = resolveQuery(flat);
        const { query_translation_key: _ignored, ...rest } = flat;
        return {
            ...rest,
            ...(resolvedQuery !== undefined ? { query: resolvedQuery } : {}),
            app_id: appId,
            skill_id: skillId,
            // Marker read by ActiveChat to render the "Sample data" banner
            // above the fullscreen. Harmless on real embeds because real
            // decodedContent never sets this field.
            is_store_example: true,
        };
    }

    function openExample(index: number) {
        const example = examples[index];
        if (!example) return;
        const embedId =
            typeof example.id === 'string' && example.id
                ? example.id
                : `store-example-${appId}-${skillId}-${index}`;

        // Intentionally do NOT close the settings panel here. The user
        // should be able to browse multiple examples (and the rest of
        // the app store) without losing context. ActiveChat's fullscreen
        // container is rendered inside the chat area and sits at its
        // normal z-index; on wide screens it appears alongside the open
        // settings panel. On close it returns to the open skill details
        // page so the user can keep exploring.
        openSkillStoreExampleFullscreen({
            embedId,
            appId,
            skillId,
            decodedContent: buildDecodedContent(example),
        });
    }

    function handleKey(e: KeyboardEvent, index: number) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            openExample(index);
        }
    }

    function openExampleChat(chat: Chat) {
        activeChatStore.setActiveChat(chat.chat_id);
        dispatch('chatSelected', { chat });
        window.dispatchEvent(new CustomEvent('globalChatSelected', { detail: { chat } }));
        if (get(isMobileView)) {
            dispatch('closeSettings');
        }
    }
</script>

{#if chatExamples.length > 0}
    <div class="section examples-section">
        <SettingsSectionHeading title={$text('settings.app_store.skills.examples')} icon="skill" />
        <p class="examples-prefix">{$text('settings.app_store.skills.examples_prefix')}</p>
        <div class="recent-chats-scroll-container" data-testid="app-store-example-chats">
            {#each chatExamples as chat (chat.chat_id)}
                <ChatPreviewCard {chat} {appId} {skillId} onOpen={openExampleChat} />
            {/each}
        </div>
    </div>
{:else if available && examples.length > 0 && PreviewComponent}
    {@const Preview = PreviewComponent}
    <div class="section examples-section">
        <SettingsSectionHeading title={$text('settings.app_store.skills.examples')} icon="skill" />
        <p class="examples-prefix">{$text('settings.app_store.skills.examples_prefix')}</p>
        <div class="examples-scroll-container">
            <div class="examples-scroll">
                {#each examples as example, i (example.id ?? i)}
                    {@const resolvedQuery = resolveQuery(example)}
                    <div
                        class="example-card"
                        data-testid="app-store-example-card"
                        data-app-id={appId}
                        data-skill-id={skillId}
                        role="button"
                        tabindex="0"
                        aria-label={$text('settings.app_store.skills.open_example')}
                        onclick={() => openExample(i)}
                        onkeydown={(e) => handleKey(e, i)}
                    >
                        <div class="example-card-inner" aria-hidden="true">
                            <Preview
                                {...example}
                                query={resolvedQuery}
                                isMobile={false}
                                onFullscreen={() => openExample(i)}
                            />
                        </div>
                    </div>
                {/each}
            </div>
        </div>
    </div>
{/if}

<style>
    .examples-section {
        margin-top: 2rem;
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
        scrollbar-width: none;
        -ms-overflow-style: none;
        visibility: visible;
        padding: 0.75rem 0 0.5rem 0;
        box-sizing: border-box;
        pointer-events: auto;
        width: 100%;
        max-width: 100%;
    }

    .recent-chats-scroll-container::-webkit-scrollbar {
        display: none;
    }

    .recent-chats-scroll-container :global(.resume-chat-large-card) {
        flex: 0 0 300px;
    }

    .examples-prefix {
        margin: 0.5rem 0 0 0;
        padding: 0;
        font-size: 0.9rem;
        font-weight: 600;
        line-height: 1.5;
        color: var(--color-grey-100);
    }

    .examples-scroll-container {
        overflow-x: auto;
        overflow-y: hidden;
        padding-bottom: 0.5rem;
        margin-top: 0.75rem;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color var(--duration-normal) var(--easing-default);
    }

    .examples-scroll-container:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }

    .examples-scroll-container::-webkit-scrollbar {
        height: 8px;
    }

    .examples-scroll-container::-webkit-scrollbar-track {
        background: transparent;
    }

    .examples-scroll-container::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: var(--radius-1);
        border: 2px solid var(--color-grey-20);
    }

    .examples-scroll-container:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }

    .examples-scroll {
        display: flex;
        gap: 0.75rem;
        padding-right: 1rem;
        min-width: min-content;
    }

    /*
     * Each card is a fixed-width slot containing a full embed preview.
     * The outer wrapper is the click target; the inner wrapper blocks
     * pointer events from reaching the preview's own internal buttons
     * so a single click always goes through our handler.
     */
    .example-card {
        flex: 0 0 auto;
        width: 320px;
        border-radius: var(--radius-5);
        cursor: pointer;
        outline: none;
    }

    .example-card:focus-visible {
        box-shadow: 0 0 0 2px var(--color-primary-start);
    }

    .example-card-inner {
        pointer-events: none;
    }
</style>
