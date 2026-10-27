<script lang="ts">
  import CalendarEventEmbedPreview from './CalendarEventEmbedPreview.svelte';
  import CalendarEventEmbedFullscreen from './CalendarEventEmbedFullscreen.svelte';
  import { eventContent } from './CalendarEventEmbedPreview.preview';

  interface Props { content?: Record<string, unknown>; large?: boolean; }
  let { content = eventContent, large = false }: Props = $props();
  let expanded = $state(false);
  let status = $derived(['processing', 'error', 'cancelled'].includes(String(content.status)) ? content.status as 'processing' | 'error' | 'cancelled' : 'finished');
</script>
<div class:large class="event-preview-host">
  <CalendarEventEmbedPreview id="calendar-event-preview" {content} {status} resultContext="chat" onFullscreen={() => expanded = true} />
</div>
{#if expanded}<div class="fullscreen-host"><CalendarEventEmbedFullscreen embedId="calendar-event-preview" data={{ decodedContent: content }} onClose={() => expanded = false} /></div>{/if}

<style>
  .event-preview-host { width: 100%; max-width: 300px; container: embed-preview / inline-size; }
  .event-preview-host.large { max-width: none; }
  .fullscreen-host { position: fixed; inset: 16px; z-index: 100; }
  @media (max-width: 600px) { .fullscreen-host { inset: 8px; } }
</style>
