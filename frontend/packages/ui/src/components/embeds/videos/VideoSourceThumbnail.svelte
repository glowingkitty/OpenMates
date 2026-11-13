<!--
  Dimmed still image of the video a running change request is changing, with a
  processing indicator over it. The video is resolved by embed id from this
  client's embed store; without a thumbnail a neutral surface remains.
  Used by the videos.generate result card and the request card while a change runs.
-->
<script lang="ts">
  import { getContext, onDestroy } from 'svelte';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../../types/embedFullscreen';
  import { createImageUrlOwner } from '../images/imageEmbedCrypto';
  import { loadSourceVideoThumbnail } from './videoGenerateCard';

  interface Props {
    /** Embed id of the video being changed. */
    embedId: string;
  }

  let { embedId }: Props = $props();
  const chatId = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT)?.chatId ?? null;
  const owner = createImageUrlOwner();
  onDestroy(owner.destroy);
  let url = $state<string | undefined>();

  $effect(() => {
    const id = embedId;
    let cancelled = false;
    url = undefined;
    loadSourceVideoThumbnail(id, chatId, owner)
      .then((loaded) => { if (!cancelled) url = loaded; })
      .catch((err) => {
        // Not synced to this device yet, or unreadable: the neutral surface stays.
        console.warn('[VideoSourceThumbnail] Thumbnail of the changed video unavailable:', id, err);
      });
    return () => { cancelled = true; };
  });
</script>

<div class="source-thumbnail" data-testid="video-generate-source" data-source-embed-id={embedId}>
  {#if url}<img src={url} alt="" data-testid="video-generate-source-thumbnail" />{/if}
  <span class="spinner" data-testid="video-generate-processing" aria-hidden="true"></span>
</div>

<style>
  .source-thumbnail { position: absolute; inset: 0; overflow: hidden; background: var(--color-grey-20); }
  img { position: absolute; inset: 0; width: 100%; height: 100%; display: block; object-fit: cover; opacity: 0.45; }
  .spinner {
    position: absolute; top: 50%; left: 50%; width: 36px; height: 36px; margin: -18px 0 0 -18px;
    border-radius: var(--radius-full); border: 3px solid color-mix(in srgb, white 45%, transparent); border-top-color: white;
    background: color-mix(in srgb, black 35%, transparent); box-sizing: border-box; animation: spin 1s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
</style>
