<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import ChatHistory from './ChatHistory.svelte';
  import { variants } from './ChatHistory.preview';
  import type { Message } from '../types/chat';
  let { short = false }: { short?: boolean } = $props();
  const fixture = variants.timelineHistory;
  let rows = $state<Message[]>(untrack(() => short ? fixture.sourceMessages.slice(0, 2) : fixture.sourceMessages) as Message[]);
  let history: ChatHistory;
  onMount(() => {
    const latest = () => history.scrollToBottom(true);
    const append = () => { rows = fixture.sourceMessages.slice(0, 4) as Message[]; };
    window.addEventListener('preview:history-latest', latest);
    window.addEventListener('preview:history-follow-up', append);
    return () => { window.removeEventListener('preview:history-latest', latest); window.removeEventListener('preview:history-follow-up', append); };
  });
</script>
<ChatHistory {...fixture} bind:this={history} sourceMessages={rows} compressionCheckpoints={short ? [] : fixture.compressionCheckpoints} />
