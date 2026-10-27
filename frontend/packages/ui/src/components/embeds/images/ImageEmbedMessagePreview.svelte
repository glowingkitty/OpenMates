<!-- Local data fixture; the real ChatMessage, editor, renderers and menu own all interactions. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import ChatMessage from '../../ChatMessage.svelte';
  import { embedStore } from '../../../services/embedStore';

  let { presentation = 'direct', kind = 'search', record = {}, width = 900 }: {
    presentation?: 'direct' | 'large' | 'grouped';
    kind?: 'search' | 'generated' | 'uploaded';
    record?: Record<string, unknown>;
    width?: number;
  } = $props();
  let ready = $state(false);
  const ids = ['3c93f160-b0c4-4000-8000-000000000001', '3c93f160-b0c4-4000-8000-000000000002'];
  const skill = $derived(kind === 'search' ? 'image_result' : kind === 'uploaded' ? 'upload' : 'generate');
  const type = $derived(kind === 'search' ? 'images-image-result' : kind === 'uploaded' ? 'image' : 'app-skill-use');
  const attrs = $derived(ids.map((id, index) => ({
    id: `node-${index}`, type, status: 'finished', contentRef: `embed:${id}`,
    app_id: 'images', skill_id: skill,
  })));
  const node = $derived(presentation === 'large'
    ? { type: 'embedPreviewLarge', attrs: { embedRef: ids[0], embedId: ids[0], appId: 'images' } }
    : presentation === 'grouped'
      ? { type: 'embed', attrs: { id: 'image-actions-group', type: `${type}-group`, status: 'finished', groupedItems: [...attrs].reverse(), groupCount: 2 } }
      : { type: 'embed', attrs: attrs[0] });
  const content = $derived({
    type: 'doc', content: [
      { type: 'paragraph', content: [
        { type: 'text', text: 'Here is the image.' },
      ] },
      presentation === 'large' ? node : { type: 'paragraph', content: [node] },
    ],
  });
  onMount(() => {
    for (const [index, id] of ids.entries()) {
      const data = {
        type: kind === 'search' ? 'image_result' : 'image', app_id: 'images', skill_id: skill,
        status: 'finished', title: index ? 'Second landscape' : 'Golden Gate Bridge',
        image_url: `https://images.example.org/landscape-${index + 1}.jpg`,
        source: 'images.example.org',
        ...(kind === 'generated' ? { prompt: 'A mountain illustration', previewImageUrl: '/images/examples/group1.jpg' } : {}),
        ...record,
      };
      embedStore.registerStaticEmbed({ embedId: id, type, appId: 'images', skillId: skill, content: JSON.stringify(data) });
    }
    ready = true;
    return () => { for (const id of ids) embedStore.removeFromMemoryCache(`embed:${id}`); };
  });
</script>

<div data-testid="image-message-fixture" data-ready={ready}>
  {#if ready}
    <ChatMessage role="assistant" {content} status="synced" containerWidth={width} animated={false} messageParts={[]} />
  {/if}
</div>
