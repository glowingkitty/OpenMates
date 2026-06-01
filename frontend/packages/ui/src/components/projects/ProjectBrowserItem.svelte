<!--
  ProjectBrowserItem.svelte
  Renders a project browser entry in tile or list mode.
  Embed items resolve through the shared embed preview registry so Projects use
  the same preview components as chats, settings memories, and saved embeds.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import type { Component } from 'svelte';
  import type { ProjectItemViewModel } from '../../services/projectService';
  import { decodeToonContent, resolveEmbed } from '../../services/embedResolver';
  import { embedPreviewRegistry } from '../../services/embedPreviewRegistry';

  let { item, viewMode = 'tile' }: { item: ProjectItemViewModel; viewMode?: 'tile' | 'list' } = $props();

  let previewComponent = $state<{ component: unknown; props: Record<string, unknown> } | null>(null);
  let isLoading = $state(false);

  onMount(() => {
    if (item.item_type === 'embed') {
      isLoading = true;
      void loadPreview();
    }
  });

  async function loadPreview(): Promise<void> {
    isLoading = true;
    try {
      const embedData = await resolveEmbed(item.target_id);
      if (!embedData || typeof embedData !== 'object') {
        previewComponent = null;
        return;
      }

      const decodedContent = await decodeToonContent(embedData.content);
      if (!decodedContent) {
        previewComponent = null;
        return;
      }

      const decoded = decodedContent as Record<string, unknown>;
      const appId = String(decoded.app_id || item.metadata.app_id || item.item_type);
      previewComponent = await embedPreviewRegistry.resolve({
        embedId: item.target_id,
        embedData: {
          ...embedData,
          app_id: appId,
          skill_id: decoded.skill_id || item.metadata.skill_id,
          type: decoded.type || item.metadata.embed_type || embedData.type,
        },
        decodedContent: decoded,
        onFullscreen: () => openEmbedFullscreen(embedData, decoded),
      });
    } catch (error) {
      console.error('[ProjectBrowserItem] Failed to render project embed preview:', error);
      previewComponent = null;
    } finally {
      isLoading = false;
    }
  }

  function openEmbedFullscreen(embedData: Record<string, unknown>, decodedContent: Record<string, unknown>): void {
    document.dispatchEvent(new CustomEvent('embedfullscreen', {
      detail: {
        embedId: item.target_id,
        embedData,
        decodedContent,
        embedType: String(decodedContent.type || item.metadata.embed_type || 'app-skill-use'),
        attrs: {
          type: decodedContent.type || item.metadata.embed_type,
          contentRef: `embed:${item.target_id}`,
          status: embedData.status || 'finished',
        },
      },
      bubbles: true,
    }));
  }

  // Svelte dynamic components are heterogeneous because each embed preview has a
  // distinct prop contract behind the registry.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function getRenderableComponent(component: unknown): Component<any, any, any> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return component as Component<any, any, any>;
  }
</script>

<article class="browser-item {viewMode}" data-testid="project-item-card" data-item-type={item.item_type}>
  {#if viewMode === 'tile' && item.item_type === 'embed'}
    <div class="embed-preview-shell">
      {#if isLoading}
        <div class="embed-preview-fallback">Loading preview...</div>
      {:else if previewComponent}
        {@const Component = getRenderableComponent(previewComponent.component)}
        <Component {...previewComponent.props} />
      {:else}
        <div class="embed-preview-fallback">{item.displayName || item.target_id}</div>
      {/if}
    </div>
  {/if}
  <div class="browser-item-meta">
    <span class="item-kind">{item.metadata.embed_type?.toString() || item.item_type}</span>
    <strong>{item.displayName || item.target_id}</strong>
    <small>{item.item_type}</small>
  </div>
</article>

<style>
  .browser-item {
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
    overflow: hidden;
  }

  .browser-item.tile {
    min-height: 210px;
  }

  .browser-item.list {
    display: flex;
    align-items: center;
    min-height: 64px;
    padding: 0 14px;
    box-shadow: none;
  }

  .embed-preview-shell {
    height: 154px;
    overflow: hidden;
    background: var(--color-grey-10);
  }

  .embed-preview-shell :global(.unified-embed-preview) {
    width: 100%;
    max-width: none;
    min-width: 0;
    height: 100%;
    border-radius: 0;
  }

  .embed-preview-fallback {
    display: grid;
    place-items: center;
    height: 100%;
    padding: 16px;
    color: var(--color-font-secondary);
    font-weight: 700;
    text-align: center;
  }

  .browser-item-meta {
    display: grid;
    gap: 6px;
    padding: 16px;
  }

  .list .browser-item-meta {
    grid-template-columns: minmax(90px, 140px) 1fr auto;
    align-items: center;
    width: 100%;
    padding: 0;
  }

  .item-kind,
  small {
    color: var(--color-font-secondary);
    font-size: 0.82rem;
  }

  .item-kind {
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
</style>
