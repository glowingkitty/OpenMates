<!--
  frontend/packages/ui/src/components/settings/SkillExamplesSection.svelte

  App-store "Examples" section shown inside SkillDetails.svelte. Renders a
  horizontal scrollable row of real, curated embed previews for the given
  skill, captured from actual provider responses. Clicking a card closes
  the settings panel and opens the skill's fullscreen inside ActiveChat —
  using the exact same data-driven fullscreen container, animation and
  child-embed drilldown as a real chat embed.

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
    import { text } from '@repo/ui';
    import { SettingsSectionHeading } from './elements';
    import {
        loadSkillExamples,
        hasSkillExamples,
    } from '../../services/skillStoreExamplesResolver';
    import { openSkillStoreExampleFullscreen } from '../../stores/skillStoreExampleFullscreenStore';
    import { panelState } from '../../stores/panelStateStore';
    import { settingsMenuVisible } from '../Settings.svelte';

    interface Props {
        appId: string;
        skillId: string;
    }

    let { appId, skillId }: Props = $props();

    let PreviewComponent = $state<Component | null>(null);
    let examples = $state<Array<Record<string, unknown>>>([]);

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
            if (translated && translated !== key) return translated;
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
        };
    }

    function openExample(index: number) {
        const example = examples[index];
        if (!example) return;
        const embedId =
            typeof example.id === 'string' && example.id
                ? example.id
                : `store-example-${appId}-${skillId}-${index}`;

        // Close the settings panel first so the user sees the fullscreen
        // slide up inside ActiveChat. We must drive BOTH of the settings
        // stores: `settingsMenuVisible` triggers the visual close inside
        // Settings.svelte (which also strips the `.mobile-overlay` class
        // that would otherwise keep the invisible settings menu above the
        // chat at z-index 1006, blocking clicks on chat history), and
        // `panelState.closeSettings()` keeps the global panel state in
        // sync. See Settings.svelte `toggleMenu` for the reference path.
        settingsMenuVisible.set(false);
        panelState.closeSettings();

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
</script>

{#if available && examples.length > 0 && PreviewComponent}
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
