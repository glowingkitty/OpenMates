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
  type ListApp = 'files' | 'code' | 'docs' | 'sheets' | 'images' | 'pdf';
  function listAppForItem(name: string, embedType: string | undefined): ListApp {
    const lowerName = name.toLowerCase();
    const type = embedType?.toLowerCase() ?? '';
    if (/\.(png|jpe?g|gif|webp|avif|svg)$/.test(lowerName) || type.startsWith('images-')) return 'images';
    if (lowerName.endsWith('.pdf') || type.startsWith('pdf')) return 'pdf';
    if (/\.(xlsx?|csv|ods)$/.test(lowerName) || type.startsWith('sheets-')) return 'sheets';
    if (/\.(md|mdx|txt|rst|docx?|odt)$/.test(lowerName) || type.startsWith('docs-')) return 'docs';
    if (/\.(py|tsx?|jsx?|mjs|cjs|java|go|rs|rb|sh|css|html|json|ya?ml|toml|sql|swift|kt|xml|plist|entitlements|gradle|php|c|h|cpp|hpp)$/.test(lowerName)
      || type.startsWith('code-')) return 'code';
    return 'files';
  }
  let listApp = $derived(listAppForItem(displayName || item.target_id, item.metadata.embed_type?.toString()));

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
    return () => {
      loadGeneration += 1;
      unsubscribe();
    };
  });

  async function loadPreview(): Promise<void> {
    const generation = ++loadGeneration;
    isLoading = true;
    try {
      const projectEmbed = await loadProjectEmbed?.(item);
      if (generation !== loadGeneration) return;
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
      const resolvedPreview = await embedPreviewRegistry.resolve({
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
      if (generation !== loadGeneration) return;
      previewComponent = resolvedPreview;
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

{#if item.item_type === 'workflow'}
  <a class="browser-item workflow-link" href={`/#workflow-id=${encodeURIComponent(item.target_id)}&workflow-tab=details`} data-testid="project-workflow-item" aria-label={`Open workflow ${displayName || item.target_id}`}>
    <span class="item-list-icon" data-app="files" aria-hidden="true"></span>
    <span class="browser-item-meta"><strong>{displayName || item.target_id}</strong><small>Workflow</small></span>
  </a>
{:else if viewMode === 'tile' && item.item_type === 'embed'}
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
    <span class="item-list-icon" data-app={listApp} aria-hidden="true"></span>
    <div class="browser-item-meta">
      <strong>{displayName || item.target_id}</strong>
      <small>{item.item_type}</small>
    </div>
  </article>
{/if}

<style>
  .browser-item {
    color: var(--color-font-primary);
  }
  .workflow-link{display:flex;align-items:center;gap:var(--spacing-8);min-height:4rem;padding:var(--spacing-8);border-radius:var(--radius-5);background:var(--color-grey-0);text-decoration:none;box-shadow:var(--shadow-sm)}
  .workflow-link:hover{background:var(--color-grey-10)}
  .workflow-link:focus-visible{outline:2px solid var(--color-button-primary);outline-offset:2px}

  .browser-item.tile {
    display: flex;
    min-width: 0;
    min-height: 12.5rem;
    justify-content: center;
  }

  .browser-item.list {
    display: grid;
    grid-template-columns: 2.5rem minmax(0, 1fr);
    align-items: center;
    gap: var(--spacing-5);
    min-height: 4rem;
    padding: 0 var(--spacing-7);
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: none;
    scale: 1;
    transition: background-color 0.2s ease;
  }

  .browser-item.list:hover { background: var(--color-grey-20); scale: 1; transform: none; }
  .item-list-icon { position: relative; width: 2.5rem; height: 2.5rem; border-radius: 50%; background: var(--color-app-files); }
  .item-list-icon::after { position: absolute; inset: 0.65rem; content: ''; background: var(--color-white-fixed, #fff); -webkit-mask: var(--icon-url-files) center / contain no-repeat; mask: var(--icon-url-files) center / contain no-repeat; }
  .item-list-icon[data-app='code'] { background: var(--color-app-code); }
  .item-list-icon[data-app='code']::after { -webkit-mask-image: var(--icon-url-coding); mask-image: var(--icon-url-coding); }
  .item-list-icon[data-app='docs'] { background: var(--color-app-docs); }
  .item-list-icon[data-app='docs']::after { -webkit-mask-image: var(--icon-url-docs); mask-image: var(--icon-url-docs); }
  .item-list-icon[data-app='sheets'] { background: var(--color-app-sheets); }
  .item-list-icon[data-app='sheets']::after { -webkit-mask-image: var(--icon-url-sheets); mask-image: var(--icon-url-sheets); }
  .item-list-icon[data-app='images'] { background: var(--color-app-images); }
  .item-list-icon[data-app='images']::after { -webkit-mask-image: var(--icon-url-image); mask-image: var(--icon-url-image); }
  .item-list-icon[data-app='pdf'] { background: var(--color-app-pdfeditor); }
  .item-list-icon[data-app='pdf']::after { -webkit-mask-image: var(--icon-url-pdf); mask-image: var(--icon-url-pdf); }

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
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: space-between;
    gap: var(--spacing-5);
  }

  .browser-item-meta strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .browser-item-meta small { flex: 0 0 auto; color: var(--color-font-secondary); }

  small {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }
</style>
