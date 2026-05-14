<!-- frontend/packages/ui/src/components/SavedEmbedContinuePreview.svelte
     Renders saved embeds in the welcome-screen continue carousel.
     Tall viewports should preserve the embed's real preview component rather than
     flattening it into the generic resume-card treatment. The component resolves
     encrypted stored embed content locally, while saved event embeds render
     directly from their saved memory payload so they never degrade to a generic
     carousel card while the embed store is still warming up.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import type { Component } from 'svelte';
    import EventEmbedPreview from './embeds/events/EventEmbedPreview.svelte';
    import { embedStore } from '../services/embedStore';
    import { decodeToonContent, resolveEmbed } from '../services/embedResolver';
    import { embedPreviewRegistry } from '../services/embedPreviewRegistry';
    import type { EmbedStoreEntry } from '../message_parsing/types';

    interface EventPreviewData {
        embed_id: string;
        id?: string;
        provider?: string;
        title?: string;
        description?: string;
        url?: string;
        date_start?: string;
        date_end?: string;
        timezone?: string;
        event_type?: string;
        venue?: {
            name?: string;
            address?: string;
            city?: string;
            state?: string;
            country?: string;
            lat?: number;
            lon?: number;
        };
        organizer?: {
            id?: string;
            name?: string;
            slug?: string;
        };
        rsvp_count?: number;
        is_paid?: boolean;
        fee?: {
            amount?: number;
            currency?: string;
        };
        image_url?: string | null;
        cover_url?: string | null;
    }

    interface Props {
        appId: string;
        embedId: string;
        title: string;
        itemValue: Record<string, unknown>;
        fallbackStyle: string;
        onFallbackOpen: () => void;
    }

    let { appId, embedId, title, itemValue, fallbackStyle, onFallbackOpen }: Props = $props();

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

    function getSavedEventPreviewData(): EventPreviewData {
        return {
            ...itemValue,
            embed_id: embedId,
            title: typeof itemValue.title === 'string' ? itemValue.title : title,
        } as EventPreviewData;
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
    {#if appId === 'events'}
        <EventEmbedPreview
            id={embedId}
            event={getSavedEventPreviewData()}
            isMobile={false}
            onFullscreen={onFallbackOpen}
        />
    {:else if isLoading}
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
