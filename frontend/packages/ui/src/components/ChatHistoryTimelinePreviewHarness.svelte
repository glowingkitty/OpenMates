<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import ChatHistory from './ChatHistory.svelte';
  import ChatTimelineToggle from './ChatTimelineToggle.svelte';
  import HeaderActionMenu from './HeaderActionMenu.svelte';
  import { headerOverlayControls } from '../actions/headerOverlayControls';
  import { variants } from './ChatHistory.preview';
  import type { Message } from '../types/chat';
  let { short = false, paneWidth = undefined }: { short?: boolean; paneWidth?: number } = $props();
  const fixture = variants.timelineHistory;
  let rows = $state<Message[]>(untrack(() => short ? fixture.sourceMessages.slice(0, 2) : fixture.sourceMessages) as Message[]);
  let history: ChatHistory;
  let timelineOverlayOpen = $state(false);
  let available = $state(false);
  let narrow = $state(false);
  const timelinePanelId = $props.id();
  onMount(() => {
    const latest = () => history.scrollToBottom(true);
    const append = () => { rows = fixture.sourceMessages.slice(0, 4) as Message[]; };
    window.addEventListener('preview:history-latest', latest);
    window.addEventListener('preview:history-follow-up', append);
    return () => { window.removeEventListener('preview:history-latest', latest); window.removeEventListener('preview:history-follow-up', append); };
  });
</script>
<div class="chat-side" style:width={paneWidth ? `${paneWidth}px` : undefined}>
  <div class="top-buttons" use:headerOverlayControls>
    {#snippet empty()}{/snippet}
    {#snippet navigation()}
      {#if available && narrow}
        <ChatTimelineToggle open={timelineOverlayOpen} controls={timelinePanelId} onToggle={() => timelineOverlayOpen = !timelineOverlayOpen} />
      {/if}
    {/snippet}
    <HeaderActionMenu report={empty} share={empty} actions={empty} hasShare={false} actionCount={0} forceOverflow navigationAction={navigation} />
  </div>
  <ChatHistory {...fixture} bind:this={history} sourceMessages={rows} compressionCheckpoints={short ? [] : fixture.compressionCheckpoints}
    bind:timelineOverlayOpen {timelinePanelId} on:timelineStateChange={(event) => { available = event.detail.available; narrow = event.detail.narrow; }} />
</div>
<style>
  .chat-side { position: relative; width: 100%; height: 100%; }
  .top-buttons { position: absolute; top: 8px; left: 8px; right: 8px; z-index: var(--z-index-sticky, 200); pointer-events: none; }
</style>
