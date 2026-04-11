<!--
  frontend/packages/ui/src/components/settings/SkillExamplesSection.svelte

  App-store "Examples" section shown inside SkillDetails.svelte. Renders a
  horizontal scrollable row of real, curated embed previews for the given
  skill, captured from actual provider responses. Clicking a card opens the
  skill's fullscreen component (with sharing disabled) so users can interact
  with download, copy, and other read-only actions before installing.

  Data flow:
    - skillStoreExamplesResolver looks up the preview/fullscreen Svelte
      components and the `*Preview.examples.ts` fixture file via the embed
      registry.
    - Each example is a flat props object (same shape as *.preview.ts).
    - For the preview card we spread the props straight in.
    - For the fullscreen we wrap the flat props into the data-driven shape
      expected by post-OPE-276 fullscreen components
      (`{ data: { decodedContent, embedData } }`).

  Hidden entirely when no examples file exists for the skill.
-->

<script lang="ts">
    import type { Component } from 'svelte';
    import { text } from '@repo/ui';
    import { SettingsSectionHeading } from './elements';
    import {
        loadSkillExamples,
        hasSkillExamples,
    } from '../../services/skillStoreExamplesResolver';

    interface Props {
        appId: string;
        skillId: string;
    }

    let { appId, skillId }: Props = $props();

    let PreviewComponent = $state<Component | null>(null);
    let FullscreenComponent = $state<Component | null>(null);
    let examples = $state<Array<Record<string, unknown>>>([]);
    let activeIndex = $state<number | null>(null);

    // Whether the skill has an examples bundle at all — controls section visibility.
    let available = $derived(hasSkillExamples(appId, skillId));

    $effect(() => {
        // Reset on skill change
        PreviewComponent = null;
        FullscreenComponent = null;
        examples = [];
        activeIndex = null;

        if (!available) return;

        const currentAppId = appId;
        const currentSkillId = skillId;

        loadSkillExamples(currentAppId, currentSkillId)
            .then((bundle) => {
                if (!bundle) return;
                // Guard against stale async resolution after prop change
                if (currentAppId !== appId || currentSkillId !== skillId) return;
                PreviewComponent = bundle.previewComponent;
                FullscreenComponent = bundle.fullscreenComponent;
                examples = bundle.examples;
            })
            .catch((err) => {
                console.error('[SkillExamplesSection] Failed to load examples', err);
            });
    });

    /**
     * Wrap flat preview props into the data-driven shape expected by
     * post-OPE-276 fullscreen components. Top-level nav props stay at
     * the top; everything else goes under `data.decodedContent`.
     */
    const FULLSCREEN_TOP_LEVEL_PROPS = new Set([
        'onClose',
        'embedId',
        'hasPreviousEmbed',
        'hasNextEmbed',
        'onNavigatePrevious',
        'onNavigateNext',
        'navigateDirection',
        'showChatButton',
        'onShowChat',
        'data',
    ]);

    function toFullscreenProps(flat: Record<string, unknown>): Record<string, unknown> {
        if ('data' in flat) return flat;
        const decodedContent: Record<string, unknown> = {};
        const topLevel: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(flat)) {
            if (FULLSCREEN_TOP_LEVEL_PROPS.has(k)) {
                topLevel[k] = v;
            } else {
                decodedContent[k] = v;
            }
        }
        const status = (decodedContent.status as string | undefined) ?? 'finished';
        return {
            ...topLevel,
            data: {
                decodedContent,
                embedData: { status },
                attrs: { app_id: appId, skill_id: skillId },
            },
        };
    }

    function openExample(index: number) {
        activeIndex = index;
    }

    function closeExample() {
        activeIndex = null;
    }

    function handleKey(e: KeyboardEvent, index: number) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            openExample(index);
        }
    }
</script>

{#if available && examples.length > 0 && PreviewComponent}
    {@const Preview = PreviewComponent}
    <div class="section examples-section">
        <SettingsSectionHeading title={$text('settings.app_store.skills.examples')} icon="skill" />
        <p class="examples-prefix">{$text('settings.app_store.skills.examples_prefix')}</p>
        <div class="examples-scroll-container">
            <div class="examples-scroll">
                {#each examples as example, i (example.id ?? i)}
                    <div
                        class="example-card"
                        role="button"
                        tabindex="0"
                        aria-label={$text('settings.app_store.skills.open_example')}
                        onclick={() => openExample(i)}
                        onkeydown={(e) => handleKey(e, i)}
                    >
                        <div class="example-card-inner" aria-hidden="true">
                            <Preview
                                {...example}
                                isMobile={false}
                                onFullscreen={() => openExample(i)}
                            />
                        </div>
                    </div>
                {/each}
            </div>
        </div>
    </div>

    {#if activeIndex !== null && FullscreenComponent}
        {@const Fullscreen = FullscreenComponent}
        {@const fsProps = toFullscreenProps(examples[activeIndex])}
        <div
            class="examples-fullscreen-portal"
            role="dialog"
            aria-modal="true"
        >
            <Fullscreen
                {...fsProps}
                onClose={closeExample}
                showShare={false}
                hasPreviousEmbed={activeIndex > 0}
                hasNextEmbed={activeIndex < examples.length - 1}
                onNavigatePrevious={() => {
                    if (activeIndex !== null && activeIndex > 0) activeIndex -= 1;
                }}
                onNavigateNext={() => {
                    if (activeIndex !== null && activeIndex < examples.length - 1)
                        activeIndex += 1;
                }}
            />
        </div>
    {/if}
{/if}

<style>
    .examples-section {
        margin-top: 2rem;
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
     * We wrap the preview in a focusable outer div so the whole card is
     * keyboard-activatable, and an inner div that contains the preview
     * component (which itself has its own click handlers for fullscreen).
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

    /*
     * Re-enable pointer events inside the preview so hover/click still
     * reach the preview component's own fullscreen button. The outer
     * click handler then takes over via onFullscreen.
     */
    .example-card-inner :global(*) {
        pointer-events: auto;
    }

    /*
     * Fullscreen overlay — sits above everything and fills the viewport.
     * UnifiedEmbedFullscreen positions itself absolutely inside its parent,
     * so we provide a fixed full-viewport parent here.
     */
    .examples-fullscreen-portal {
        position: fixed;
        inset: 0;
        z-index: var(--z-index-modal, 1000);
        background: rgba(0, 0, 0, 0.5);
    }
</style>
