<!-- frontend/packages/ui/src/components/SavedEmbedContinuePreview.svelte
     Renders saved embeds in the welcome-screen continue carousel.
     Tall viewports should preserve the embed's real preview component rather than
     flattening it into the generic resume-card treatment. The component resolves
     encrypted stored embed content locally and falls back to a compact branded
     card only when no preview resolver exists for the embed type.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import type { Component } from 'svelte';
    import { embedStore } from '../services/embedStore';
    import { decodeToonContent, resolveEmbed } from '../services/embedResolver';
    import { embedPreviewRegistry } from '../services/embedPreviewRegistry';
    import type { EmbedStoreEntry } from '../message_parsing/types';
    import type { ContinuePriority } from '../services/continueCarouselService';

    interface Props {
        appId: string;
        embedId: string;
        title: string;
        priority: ContinuePriority;
        fallbackStyle: string;
        onFallbackOpen: () => void;
    }

    let { appId, embedId, title, priority, fallbackStyle, onFallbackOpen }: Props = $props();

    let previewComponent = $state<{ component: unknown; props: Record<string, unknown> } | null>(null);
    let isLoading = $state(true);

    onMount(() => {
        void loadPreview();
    });

    async function loadPreview(): Promise<void> {
        isLoading = true;
        try {
            const embedData = await resolveEmbed(embedId);
            if (!embedData || typeof embedData !== 'object') {
                previewComponent = null;
                return;
            }

            const decodedContent = await decodeToonContent(embedData.content);
            if (!decodedContent) {
                previewComponent = null;
                return;
            }

            const indexedEmbedEntry = await getEmbedEntry();
            const embedEntry = indexedEmbedEntry ?? {
                contentRef: `embed:${embedId}`,
                app_id: decodedContent.app_id || appId,
                skill_id: decodedContent.skill_id,
                type: decodedContent.type || embedData.type,
            } as EmbedStoreEntry;

            const embedAppId = embedEntry.app_id || decodedContent.app_id || appId;
            previewComponent = await embedPreviewRegistry.resolve({
                embedId,
                embedData: {
                    ...embedData,
                    app_id: embedAppId,
                    skill_id: embedEntry.skill_id || decodedContent.skill_id,
                    type: embedEntry.type || embedData.type,
                },
                decodedContent: decodedContent as Record<string, unknown>,
                onFullscreen: () => openEmbedFullscreen(embedData, embedEntry, decodedContent),
            });
        } catch (error) {
            console.error('[SavedEmbedContinuePreview] Failed to render saved embed preview:', error);
            previewComponent = null;
        } finally {
            isLoading = false;
        }
    }

    async function getEmbedEntry(): Promise<EmbedStoreEntry | null> {
        const appEmbeds = await embedStore.getEmbedsByAppId(appId);
        return appEmbeds.find((entry) => entry.contentRef === `embed:${embedId}`) ?? null;
    }

    // Svelte's dynamic component type requires `any` here because registry entries
    // point at heterogeneous components with different required prop contracts.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    function getRenderableComponent(component: unknown): Component<any, any, any> {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        return component as Component<any, any, any>;
    }

    function openEmbedFullscreen(
        embedData: Record<string, unknown>,
        embedEntry: EmbedStoreEntry,
        decodedContent: Record<string, unknown>,
    ): void {
        const rawType = String(embedEntry.type || decodedContent.type || '');
        const autoConvertedTypes = ['code', 'code-code', 'sheet', 'sheets-sheet', 'math-plot', 'document', 'docs-doc'];
        const embedType = rawType === 'events-event' || appId === 'events'
            ? 'events-event'
            : autoConvertedTypes.includes(rawType)
                ? rawType
                : 'app-skill-use';

        document.dispatchEvent(new CustomEvent('embedfullscreen', {
            detail: {
                embedId,
                embedData,
                decodedContent,
                embedType,
                attrs: {
                    type: embedEntry.type || decodedContent.type,
                    contentRef: embedEntry.contentRef || `embed:${embedId}`,
                    status: embedData.status || 'finished',
                },
            },
            bubbles: true,
        }));
    }
</script>

<div class="saved-embed-continue-preview" data-testid="saved-embed-continue-preview" data-embed-id={embedId}>
    <div class="continue-priority-pill saved-embed-pill" data-testid="continue-priority-pill">
        <span>{priority.label}</span>
    </div>

    {#if isLoading}
        <button class="saved-embed-loading" style={fallbackStyle} type="button" onclick={onFallbackOpen}>
            <span>{title}</span>
        </button>
    {:else if previewComponent}
        {@const Component = getRenderableComponent(previewComponent.component)}
        <Component {...previewComponent.props} />
    {:else}
        <button class="saved-embed-loading" style={fallbackStyle} type="button" onclick={onFallbackOpen}>
            <span>{title}</span>
        </button>
    {/if}
</div>

<style>
    .saved-embed-continue-preview {
        position: relative;
        flex-shrink: 0;
        pointer-events: auto;
    }

    .saved-embed-continue-preview :global(.unified-embed-preview) {
        text-align: left;
    }

    .saved-embed-pill {
        position: absolute;
        top: 12px;
        left: 12px;
        z-index: var(--z-index-raised-4);
        display: inline-flex;
        align-items: center;
        gap: 5px;
        max-width: calc(100% - 24px);
        padding: 5px 9px;
        border-radius: 999px;
        background: rgba(0, 0, 0, 0.28);
        color: white;
        font-size: var(--font-size-xxs);
        font-weight: 700;
        line-height: 1;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        backdrop-filter: blur(8px);
        border: 1px solid rgba(255, 255, 255, 0.2);
        text-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
        pointer-events: none;
    }

    .saved-embed-loading {
        width: 300px;
        min-width: 300px;
        max-width: 300px;
        height: 200px;
        min-height: 200px;
        max-height: 200px;
        border: none;
        border-radius: 30px;
        padding: var(--spacing-10);
        color: white;
        font-weight: 700;
        cursor: pointer;
        box-shadow:
            0 8px 24px rgba(0, 0, 0, 0.16),
            0 2px 6px rgba(0, 0, 0, 0.1);
    }
</style>
