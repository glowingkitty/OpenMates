<!-- figma-visual-proof: not-required. Reuses the original Design viewer. -->
<script lang="ts">
  import { getContext } from 'svelte';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedFullscreenRawData, type EmbedSourceChatContext } from '../../../types/embedFullscreen';
  import { getWorkspaceCacheEpoch } from '../../../services/workspaceCacheLifecycle';
  import EmbedFullscreenLoading from '../EmbedFullscreenLoading.svelte';
  import DesignEditorFullscreen from './editor/DesignEditorFullscreen.svelte';
  import type { DesignDocument } from './editor/designDocument';
  import { readDesignView } from './editor/designView';
  import { readDesignImage } from './editor/designViewAssets';

  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
  }

  let { data, embedId, onClose }: Props = $props();
  const context = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);
  let design = $state.raw<DesignDocument | null>(null);
  let failed = $state(false);
  const chatId = $derived(context?.exampleChatId ? null : context?.lookupChatId ?? context?.chatId ?? null);
  const readImage = $derived.by(() => {
    const id = embedId;
    const sourceChat = chatId;
    return (asset: string) => id && sourceChat ? readDesignImage(asset, id, sourceChat) : Promise.resolve(null);
  });

  $effect(() => {
    const input = data.embedData?.content;
    const decoded = data.decodedContent;
    const epoch = getWorkspaceCacheEpoch();
    let current = true;
    design = null;
    failed = false;
    void readDesignView(decoded, input).then((result) => {
      if (current && getWorkspaceCacheEpoch() === epoch) {
        design = result;
        failed = !result;
      }
    }, () => { if (current) failed = true; });
    return () => { current = false; };
  });
</script>

{#if design}
  {#key design}
    <DesignEditorFullscreen document={design} readOnly {readImage} {onClose} />
  {/key}
{:else}
  <EmbedFullscreenLoading data={{ ...data, embedType: 'design-document' }} {failed} {onClose} />
{/if}
