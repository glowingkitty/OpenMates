<!-- frontend/packages/ui/src/components/settings/AppSettingsMemoryEmbedPreview.svelte
     Renders a compact embed preview inside app memory entries.
     Saved memories keep only compact structured fields plus an embed_id reference.
     This component resolves that referenced embed from the encrypted local embed store
     and reuses the normal embed preview/fullscreen registry so memory entries open
     the same fullscreen view as chat embeds.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { embedStore } from '../../services/embedStore';
    import { decodeToonContent, resolveEmbed } from '../../services/embedResolver';
    import { embedPreviewRegistry } from '../../services/embedPreviewRegistry';
    import type { EmbedStoreEntry } from '../../message_parsing/types';

    interface Props {
        appId: string;
        embedId: string;
    }

    let { appId, embedId }: Props = $props();

    let previewComponent = $state<{ component: unknown; props: Record<string, unknown> } | null>(null);
    let isLoading = $state(true);

    onMount(() => {
        void loadPreview();
    });

    async function loadPreview(): Promise<void> {
        isLoading = true;
        try {
            const embedEntry = await getEmbedEntry();
            const embedData = await resolveEmbed(embedId);

            if (!embedEntry || !embedData || typeof embedData !== 'object') {
                previewComponent = null;
                return;
            }

            const decodedContent = await decodeToonContent(embedData.content);
            if (!decodedContent) {
                previewComponent = null;
                return;
            }

            const embedAppId = embedEntry.app_id || decodedContent.app_id || appId;
            if (embedAppId !== appId) {
                previewComponent = null;
                return;
            }

            previewComponent = await embedPreviewRegistry.resolve({
                embedId,
                embedData: {
                    ...embedData,
                    app_id: embedAppId,
                    skill_id: embedEntry.skill_id || decodedContent.skill_id,
                },
                decodedContent: decodedContent as Record<string, unknown>,
                onFullscreen: () => openEmbedFullscreen(embedData, embedEntry, decodedContent),
            });
        } catch (error) {
            console.error('[AppSettingsMemoryEmbedPreview] Failed to render saved embed preview:', error);
            previewComponent = null;
        } finally {
            isLoading = false;
        }
    }

    async function getEmbedEntry(): Promise<EmbedStoreEntry | null> {
        const appEmbeds = await embedStore.getEmbedsByAppId(appId);
        return appEmbeds.find((entry) => entry.contentRef === `embed:${embedId}`) ?? null;
    }

    function openEmbedFullscreen(
        embedData: Record<string, unknown>,
        embedEntry: EmbedStoreEntry,
        decodedContent: Record<string, unknown>,
    ): void {
        const rawType = embedEntry.type || '';
        const autoConvertedTypes = ['code', 'code-code', 'sheet', 'sheets-sheet', 'math-plot', 'document', 'docs-doc'];
        const embedType = autoConvertedTypes.includes(rawType) ? rawType : 'app-skill-use';

        document.dispatchEvent(new CustomEvent('embedfullscreen', {
            detail: {
                embedId,
                embedData,
                decodedContent,
                embedType,
                attrs: {
                    type: embedEntry.type,
                    contentRef: embedEntry.contentRef,
                    status: embedData.status || 'finished',
                },
            },
            bubbles: true,
        }));
    }
</script>

{#if isLoading}
    <div class="memory-embed-loading" data-testid="memory-embed-preview-loading">Loading preview...</div>
{:else if previewComponent}
    {@const Component = previewComponent.component}
    <div class="memory-embed-preview" data-testid="memory-embed-preview" data-embed-id={embedId}>
        <Component {...previewComponent.props} />
    </div>
{/if}

<style>
    .memory-embed-loading {
        padding: 0.625rem 0.75rem;
        color: var(--text-secondary, #666666);
        font-size: 0.85rem;
    }

    .memory-embed-preview {
        width: min(300px, 100%);
        margin: 0.35rem 0 0.85rem 3.75rem;
    }

    .memory-embed-preview :global(.unified-embed-preview) {
        max-width: 100%;
    }

    @media (max-width: 640px) {
        .memory-embed-preview {
            width: 150px;
            margin-left: 3.25rem;
        }
    }
</style>
