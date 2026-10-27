<!-- Production fullscreen submission with a source-chat context and a local
     image. The host observes the actual handoff; it does not replace submit. -->
<script lang="ts">
  import { onMount, setContext } from 'svelte';
  import ImageGenerateEmbedFullscreen from './images/ImageGenerateEmbedFullscreen.svelte';
  import { EMBED_SOURCE_CHAT_CONTEXT } from '../../types/embedFullscreen';
  import { embedStore } from '../../services/embedStore';
  import { APPS_WORKSPACE_CHAT_HANDOFF_EVENT, takeAppsWorkspaceChatHandoff,
    appsRequestContextDocument } from '../../services/appsWorkspaceChatHandoffService';
  import { tipTapToCanonicalMarkdown } from '../../message_parsing/serializers';

  const chatId = 'e2e-fullscreen-followup-source';
  const embedId = '11111111-1111-4111-8111-11111111f011';
  let open = $state(true);
  let document = $state('');
  let destination = $state('');
  setContext(EMBED_SOURCE_CHAT_CONTEXT, { chatId });
  const image = { app_id: 'images', skill_id: 'generate', prompt: 'A mountain at sunset',
    previewImageUrl: '/images/examples/group1.jpg' };
  embedStore.setInMemoryOnly(`embed:${embedId}`, { embed_id: embedId, type: 'app-skill-use',
    status: 'finished', content: JSON.stringify(image) });
  onMount(() => {
    const submitted = () => {
      const request = takeAppsWorkspaceChatHandoff();
      if (!request) return;
      destination = request.context?.chat_id ?? '';
      document = tipTapToCanonicalMarkdown(appsRequestContextDocument(request));
    };
    window.addEventListener(APPS_WORKSPACE_CHAT_HANDOFF_EVENT, submitted);
    return () => window.removeEventListener(APPS_WORKSPACE_CHAT_HANDOFF_EVENT, submitted);
  });
</script>

<div class="followup-host">
  {#if open}
    <ImageGenerateEmbedFullscreen {embedId} data={{ decodedContent: image }}
      onClose={() => { open = false; }} />
  {:else}
    <p data-testid="followup-destination">{destination}</p>
    <pre data-testid="followup-document">{document}</pre>
  {/if}
</div>

<style>
  .followup-host { position: relative; width: 100%; height: 100dvh; }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
