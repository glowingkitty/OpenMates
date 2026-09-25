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
  import type { EmbedFullscreenDispatchDetail } from '../../services/embedFullscreenController';
  import { embedPreviewRegistry } from '../../services/embedPreviewRegistry';
  import { embedAvailabilityVersion } from '../../services/embedStore';

  interface ProjectBrowserResolvedEmbed {
    embedData: Record<string, unknown>;
    decodedContent: Record<string, unknown>;
  }

  let {
    item,
    viewMode = 'tile',
    onOpenFullscreen,
    loadProjectEmbed,
    displayName = item.displayName,
  }: {
    item: ProjectItemViewModel;
    viewMode?: 'tile' | 'list';
    onOpenFullscreen: (detail: EmbedFullscreenDispatchDetail) => void;
    loadProjectEmbed?: (item: ProjectItemViewModel) => Promise<ProjectBrowserResolvedEmbed | null>;
    displayName?: string;
  } = $props();

  let previewComponent = $state<{ component: unknown; props: Record<string, unknown> } | null>(null);
  let isLoading = $state(false);
  let resolvedEmbedData = $state<Record<string, unknown> | null>(null);
  let resolvedContent = $state<Record<string, unknown> | null>(null);
  let childFullscreenDispatchedAt = 0;
  let loadGeneration = 0;

  onMount(() => {
    let mounted = false;
    const unsubscribe = embedAvailabilityVersion.subscribe(() => {
      if (mounted && item.item_type === 'embed') void loadPreview();
    });
    mounted = true;
    if (item.item_type === 'embed') {
      isLoading = true;
      void loadPreview();
    }
    return unsubscribe;
  });

  async function loadPreview(): Promise<void> {
    const generation = ++loadGeneration;
    isLoading = true;
    try {
      const projectEmbed = await loadProjectEmbed?.(item);
      const embedData = projectEmbed?.embedData ?? await resolveEmbed(item.target_id);
      if (generation !== loadGeneration) return;
      if (!embedData || typeof embedData !== 'object') {
        previewComponent = null;
        resolvedEmbedData = null;
        resolvedContent = null;
        return;
      }

      const decodedContent = projectEmbed?.decodedContent ?? await decodeToonContent(embedData.content);
      if (generation !== loadGeneration) return;
      if (!decodedContent) {
        previewComponent = null;
        resolvedEmbedData = null;
        resolvedContent = null;
        return;
      }

      const decoded = decodedContent as Record<string, unknown>;
      resolvedEmbedData = embedData;
      resolvedContent = decoded;
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
        onFullscreen: () => {
          childFullscreenDispatchedAt = performance.now();
          openEmbedFullscreen(embedData, decoded);
        },
      });
    } catch (error) {
      if (generation !== loadGeneration) return;
      console.error('[ProjectBrowserItem] Failed to render project embed preview:', error);
      previewComponent = null;
      resolvedEmbedData = null;
      resolvedContent = null;
    } finally {
      if (generation === loadGeneration) isLoading = false;
    }
  }

  function openEmbedFullscreen(embedData: Record<string, unknown>, decodedContent: Record<string, unknown>): void {
    const detail: EmbedFullscreenDispatchDetail = {
      embedId: item.target_id,
      embedData,
      decodedContent,
      embedType: String(decodedContent.type || item.metadata.embed_type || 'app-skill-use'),
      attrs: {
        type: decodedContent.type || item.metadata.embed_type,
        contentRef: `embed:${item.target_id}`,
        status: embedData.status || 'finished',
      },
      hasChatContext: false,
    };
    onOpenFullscreen(detail);
  }

  function activateItem(event?: MouseEvent | KeyboardEvent): void {
    if (!resolvedEmbedData || !resolvedContent) return;
    const target = event?.target instanceof Element ? event.target : null;
    const nestedControl = target?.closest('button, a, input, [role="button"]');
    if (nestedControl && nestedControl !== event?.currentTarget) return;
    if (event instanceof MouseEvent) {
      if (performance.now() - childFullscreenDispatchedAt < 100) return;
    }
    if (event instanceof KeyboardEvent && event.key !== 'Enter' && event.key !== ' ') return;
    event?.preventDefault();
    openEmbedFullscreen(resolvedEmbedData, resolvedContent);
  }

  // Svelte dynamic components are heterogeneous because each embed preview has a
  // distinct prop contract behind the registry.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function getRenderableComponent(component: unknown): Component<any, any, any> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return component as Component<any, any, any>;
  }
</script>

{#if viewMode === 'tile' && item.item_type === 'embed'}
  <!-- The shared preview is the complete project tile. It already owns the
       details body, identity footer, focus treatment, and fullscreen click. -->
  <article class="browser-item tile" data-testid="project-item-card" data-item-type={item.item_type}>
    {#if isLoading}
      <div class="embed-preview-fallback">Loading preview...</div>
    {:else if previewComponent}
      {@const Component = getRenderableComponent(previewComponent.component)}
      <Component {...previewComponent.props} />
    {:else}
      <div class="embed-preview-fallback">{displayName || item.target_id}</div>
    {/if}
  </article>
{:else}
  <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
  <article
    class="browser-item list"
    class:actionable={!!resolvedEmbedData && !!resolvedContent}
    data-testid="project-item-card"
    data-item-type={item.item_type}
    role="button"
    tabindex={resolvedEmbedData && resolvedContent ? 0 : undefined}
    aria-disabled={!resolvedEmbedData || !resolvedContent}
    aria-label={resolvedEmbedData && resolvedContent ? `Open ${displayName || 'Project item'}` : undefined}
    onclick={activateItem}
    onkeydown={activateItem}
  >
    <div class="browser-item-meta">
      <span class="item-kind">{item.metadata.embed_type?.toString() || item.item_type}</span>
      <strong>{displayName || item.target_id}</strong>
      <small>{item.item_type}</small>
    </div>
  </article>
{/if}

<style>
  .browser-item {
    color: var(--color-font-primary);
  }

  .browser-item.tile {
    display: flex;
    min-width: 0;
    min-height: 12.5rem;
    justify-content: center;
  }

  .browser-item.list {
    display: flex;
    align-items: center;
    min-height: 4rem;
    padding: 0 var(--spacing-7);
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: none;
  }

  .browser-item.actionable {
    cursor: pointer;
  }

  .browser-item.actionable:focus-visible {
    outline: 2px solid var(--color-focus, var(--color-font-primary));
    outline-offset: 2px;
  }

  .browser-item.tile :global(.unified-embed-preview) {
    flex: 0 0 auto;
  }

  .embed-preview-fallback {
    display: grid;
    place-items: center;
    width: min(18.75rem, 100%);
    min-height: 12.5rem;
    padding: var(--spacing-8);
    border-radius: var(--radius-5);
    background: var(--color-grey-10);
    color: var(--color-font-secondary);
    font-weight: 700;
    text-align: center;
  }

  .browser-item-meta {
    display: grid;
    gap: var(--spacing-3);
    padding: var(--spacing-8);
  }

  .list .browser-item-meta {
    grid-template-columns: minmax(5.625rem, 8.75rem) 1fr auto;
    align-items: center;
    width: 100%;
    padding: 0;
  }

  .item-kind,
  small {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }

  .item-kind {
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
</style>
