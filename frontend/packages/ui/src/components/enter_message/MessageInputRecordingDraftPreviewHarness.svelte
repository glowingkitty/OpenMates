<script lang="ts">
  import { onMount, tick } from 'svelte';
  import type { JSONContent } from '@tiptap/core';
  import MessageInput from './MessageInput.svelte';
  import ImageEmbedFullscreen from '../embeds/images/ImageEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../types/embedFullscreen';

  let { includeNotes = true }: { includeNotes?: boolean } = $props();
  const chatId = 'e9ca8e41-940a-4d6a-8380-275a573ab468';
  let composer = $state<{ setDraftContent: (id: string, content: JSONContent, version: number) => Promise<void> }>();
  let ready = $state(false);
  let image = $state<EmbedFullscreenRawData | null>(null);
  let sendRequests = $state(0);

  onMount(() => {
    const paragraph = (text: string): JSONContent => ({
      type: 'paragraph', content: [{ type: 'text', text }],
    });
    const draft: JSONContent = {
      type: 'doc',
      content: [
        ...(includeNotes ? [paragraph('Existing image notes. Describe the people in this photo.')] : []),
        { type: 'paragraph', content: [{ type: 'embed', attrs: {
          id: 'synthetic-recording-draft-image', type: 'image', status: 'finished',
          src: '/images/examples/group1.jpg', filename: 'recording-draft.jpg', fileType: 'image/jpeg',
        } }] },
        ...(includeNotes
          ? Array.from({ length: 12 }, (_, index) => paragraph(`Existing detail ${index + 1}. Keep this note while describing the image.`))
          : [{ type: 'paragraph' }]),
      ],
    };
    void tick().then(async () => {
      await composer?.setDraftContent(chatId, draft, 1);
      ready = true;
    });
  });

  function openImage(event: CustomEvent<{ src?: string; filename?: string; fileType?: string }>) {
    image = { decodedContent: {
      src: event.detail.src, filename: event.detail.filename,
      file_type: event.detail.fileType, is_authenticated: false,
    } };
  }
</script>

<div data-testid="recording-draft-fixture" data-ready={ready} data-send-requests={sendRequests}>
  <div data-testid="recording-draft-composer">
    <MessageInput
      bind:this={composer}
      currentChatId={chatId}
      onAssistantSpeechPreferenceChange={() => {}}
      on:imagefullscreen={openImage}
      on:sendMessage={() => { sendRequests += 1; }}
    />
  </div>
  {#if image}
    <ImageEmbedFullscreen data={image} onClose={() => { image = null; }} />
  {/if}
</div>
