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
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
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

  // Retry state for when embed ref cannot be resolved to a UUID yet
  // (e.g. cross-device sync hasn't finished decrypting/registering refs).
  let retryCount = 0;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  let resolvedEmbedId = $derived.by(() => {
    void $embedRefIndexVersion;
    return embedId || embedStore.resolveByRef(embedRef) || null;
  });

  /**
   * Child embed types that should override the parent's skill_id for routing.
   * E.g. an images/search child has type "image_result" in its TOON content
   * but app_id "web" and skill_id "website" at the top level.
   */
  const CHILD_TYPE_OVERRIDES = new Set([
    'image_result', 'web_result', 'news_result', 'video_result',
    'location', 'flight', 'stay', 'event', 'product', 'job',
    'health_result', 'recipe', 'price_calendar_result', 'listing',
  ]);

  function buildAttrs(
    id: string,
    embedData: unknown,
    decodedContent?: Record<string, unknown> | null,
  ): EmbedNodeAttributes {
    const data = embedData as Record<string, unknown>;

    // Start with top-level fields
    let appId = (data.app_id as string | null) || null;
    let skillId = (data.skill_id as string | null) || null;

    // Override from decoded TOON content — child embeds store the real
    // app_id/skill_id inside the encrypted content, not at the top level.
    if (decodedContent) {
      if (decodedContent.app_id) appId = decodedContent.app_id as string;
      if (decodedContent.skill_id) skillId = decodedContent.skill_id as string;

      // CRITICAL: For child embeds (e.g. image_result from images/search),
      // the TOON content's `type` field holds the actual child type.
      // Use it as skill_id to route to the correct renderer.
      const childType = decodedContent.type as string | undefined;
      if (childType && CHILD_TYPE_OVERRIDES.has(childType)) {
        skillId = childType;
      }
    }

    // Also check the embed store's type field — for child embeds the WebSocket
    // payload includes `type: "image_result"` which is stored directly.
    // TOON content may NOT contain a `type` field, so this is the reliable fallback.
    if (!skillId || !CHILD_TYPE_OVERRIDES.has(skillId)) {
      const storeType = data.type as string | undefined;
      if (storeType && CHILD_TYPE_OVERRIDES.has(storeType)) {
        skillId = storeType;
      }
    }

    // Heuristic for stored child embeds: if app_id="images", skill_id="search",
    // but there are no embed_ids (parent images/search always has them), and TOON
    // has image_url or thumbnail_url → this is actually an image_result child embed.
    if (appId === 'images' && skillId === 'search' && decodedContent && !decodedContent.embed_ids) {
      if (decodedContent.image_url || decodedContent.thumbnail_url) {
        skillId = 'image_result';
      }
    }

    return {
      id,
      type: normalizeEmbedType(String(data.type || 'app-skill-use')),
      status: String(data.status || 'finished') as EmbedNodeAttributes['status'],
      contentRef: `embed:${id}`,
      app_id: appId,
      skill_id: skillId,
      query: (data.query as string | null) || (decodedContent?.query as string | null) || null,
      url: (data.url as string | null) || (decodedContent?.url as string | null) || null,
      title: (data.title as string | null) || (decodedContent?.title as string | null) || null,
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
      // Retry ref resolution: during cross-device sync, the ref→ID index may
      // not be populated yet. Bump embedRefIndexVersion after a delay to
      // trigger $derived re-evaluation once eager decryption has registered refs.
      if (embedRef && retryCount < 3) {
        if (retryTimer) clearTimeout(retryTimer);
        retryTimer = setTimeout(() => {
          retryCount++;
          embedRefIndexVersion.update((n) => n + 1);
        }, 1000 * (retryCount + 1)); // 1s, 2s, 3s
      }
      return;
    }
    // Ref resolved — clear any pending retry
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
    retryCount = 0;

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
      if (!containerEl || !containerEl.isConnected) {
        console.warn('[EmbedReferencePreview] containerEl detached/null after resolve, aborting render');
        return;
      }

      // Decode TOON content to extract child type overrides (e.g. image_result)
      let decodedContent: Record<string, unknown> | null = null;
      if (embedData.content) {
        try {
          decodedContent = await decodeToonContent(embedData.content) as Record<string, unknown> | null;
        } catch {
          // Ignore decode errors — will fall through to top-level fields
        }
      }

      // Abort if a newer render started while decoding
      if (thisVersion !== renderVersion) return;

      const attrs = buildAttrs(resolvedEmbedId, embedData, decodedContent);
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
    if (retryTimer) clearTimeout(retryTimer);
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
