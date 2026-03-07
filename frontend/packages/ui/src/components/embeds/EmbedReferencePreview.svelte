<script lang="ts">
  // frontend/packages/ui/src/components/embeds/EmbedReferencePreview.svelte
  //
  // Purpose: Render an embed preview from an embed_ref by reusing the existing
  // embed renderer pipeline (CodeEmbedPreview, VideoEmbedPreview, WebsiteEmbedPreview, etc.).
  //
  // Architecture: delegates to getEmbedRenderer() used by TipTap Embed node views.
  // See docs/architecture/embeds.md for renderer routing.
  // Tests: frontend/packages/ui/src/message_parsing/__tests__/parse_message.test.ts

  import { onDestroy } from 'svelte';
  import { embedStore, embedRefIndexVersion } from '../../services/embedStore';
  import { resolveEmbed } from '../../services/embedResolver';
  import { getEmbedRenderer } from '../enter_message/extensions/embed_renderers';
  import { normalizeEmbedType } from '../../data/embedRegistry.generated';
  import type { EmbedNodeAttributes } from '../../message_parsing/types';

  interface Props {
    embedRef: string;
    embedId?: string | null;
    variant?: 'small' | 'large';
  }

  let { embedRef, embedId = null, variant = 'small' }: Props = $props();

  let containerEl = $state<HTMLElement | null>(null);
  let errorText = $state<string | null>(null);
  let loading = $state(true);

  /**
   * Monotonically increasing render version to prevent stale async callbacks
   * from overwriting newer renders. Each call to renderResolvedPreview()
   * captures the current version and aborts if it has been superseded
   * by a later invocation before the async work completes.
   */
  let renderVersion = 0;

  let resolvedEmbedId = $derived.by(() => {
    void $embedRefIndexVersion;
    return embedId || embedStore.resolveByRef(embedRef) || null;
  });

  function buildAttrs(id: string, embedData: unknown): EmbedNodeAttributes {
    const data = embedData as Record<string, unknown>;
    return {
      id,
      type: normalizeEmbedType(String(data.type || 'app-skill-use')),
      status: String(data.status || 'finished') as EmbedNodeAttributes['status'],
      contentRef: `embed:${id}`,
      app_id: (data.app_id as string | null) || null,
      skill_id: (data.skill_id as string | null) || null,
      query: (data.query as string | null) || null,
      url: (data.url as string | null) || null,
      title: (data.title as string | null) || null,
      filename: (data.filename as string | null) || null,
      language: (data.language as string | null) || null,
    } as EmbedNodeAttributes;
  }

  async function renderResolvedPreview(): Promise<void> {
    if (!containerEl) return;

    // Bump version so any in-flight async render from a previous call
    // will detect it has been superseded and skip its DOM update.
    const thisVersion = ++renderVersion;

    containerEl.innerHTML = '';
    errorText = null;

    if (!resolvedEmbedId) {
      loading = true;
      return;
    }

    loading = true;
    try {
      const embedData = await resolveEmbed(resolvedEmbedId);

      // Abort if a newer render has been started while we were awaiting
      if (thisVersion !== renderVersion) return;

      if (!embedData) {
        loading = false;
        return;
      }

      // Guard: container must still be attached to the DOM.
      // During streaming, TipTap may destroy and recreate node views,
      // leaving containerEl detached before the async resolve completes.
      if (!containerEl.isConnected) {
        console.warn('[EmbedReferencePreview] containerEl detached from DOM, aborting render');
        return;
      }

      const attrs = buildAttrs(resolvedEmbedId, embedData);
      const renderer = getEmbedRenderer(attrs.type || '');
      if (!renderer) {
        errorText = 'Preview unavailable';
        loading = false;
        return;
      }

      const maybePromise = renderer.render({
        attrs,
        container: containerEl,
        content: containerEl,
      });

      if (maybePromise instanceof Promise) {
        await maybePromise;
      }

      // Final staleness check after render completes
      if (thisVersion !== renderVersion) return;

      loading = false;
    } catch (error) {
      // Only update UI if this render is still the latest
      if (thisVersion !== renderVersion) return;

      console.error('[EmbedReferencePreview] Failed to render embed_ref preview:', {
        embedRef,
        resolvedEmbedId,
        error,
      });
      errorText = 'Preview unavailable';
      loading = false;
    }
  }

  // Use $effect for reactive re-rendering when dependencies change.
  // onMount is NOT needed separately because $effect runs on mount too.
  $effect(() => {
    void variant;
    void resolvedEmbedId;
    renderResolvedPreview();
  });

  onDestroy(() => {
    if (containerEl) {
      containerEl.innerHTML = '';
    }
  });
</script>

<div class="embed-reference-preview embed-reference-preview--{variant}">
  {#if loading && !resolvedEmbedId}
    <div class="embed-reference-preview-placeholder">Loading preview...</div>
  {/if}

  {#if errorText}
    <div class="embed-reference-preview-error">{errorText}</div>
  {/if}

  <div bind:this={containerEl} class="embed-reference-preview-container"></div>
</div>

<style>
  .embed-reference-preview {
    width: 100%;
  }

  .embed-reference-preview-container {
    width: 100%;
  }

  .embed-reference-preview-placeholder,
  .embed-reference-preview-error {
    margin: 6px 0;
    padding: 10px 12px;
    border-radius: 10px;
    background: var(--color-grey-25);
    color: var(--color-font-secondary);
    font-size: 13px;
  }

  .embed-reference-preview-error {
    color: var(--color-error);
    background: color-mix(in srgb, var(--color-error) 10%, var(--color-grey-25));
  }
</style>
