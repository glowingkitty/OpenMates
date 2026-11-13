<script lang="ts">
  import { text } from '../i18n/translations';
  import type { OrchestrationEvent } from '../services/rustCore/crypto/orchestrationOps';
  /** `title` is the spawned chat's current local title; the event's own title is the fallback. */
  let { event, title = null, onOpen }: {
    event: OrchestrationEvent;
    title?: string | null;
    onOpen: (chatId: string) => void;
  } = $props();
  let shownTitle = $derived(title ?? event.title ?? '');
  let timestamp = $derived(new Date(event.created_at * 1000));
  let time = $derived(timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
</script>
<button type="button" class="orchestration-event" data-testid="chat-orchestration-event"
  data-action={event.action} onclick={() => onOpen(event.chat_id)}>
  <span class="line">
    <span class="event-icon" aria-hidden="true"></span>
    <span>{$text(`chat_orchestration_events.${event.action}`, { values: { title: shownTitle } })} – <time datetime={timestamp.toISOString()}>{time}</time></span>
  </span>
  {#if (event.action === 'report' || event.action === 'sent' || event.action === 'reported') && event.text}
    <span class="report-text" data-testid="chat-orchestration-report">{event.text}</span>
  {/if}
</button>
<style>
  .orchestration-event {
    display: inline-flex; flex-direction: column; align-items: center; gap: var(--spacing-2, 8px);
    background: none; border: 0; padding: 0; font: inherit; cursor: pointer; color: var(--color-grey-60);
    max-width: 100%; text-align: center;
    /* Reset the global button look (fixed 41px height, drop shadow, min width, margin) so the
       up-to-four-line text is not clipped and the line stays a plain system event. */
    height: auto; min-width: 0; margin: 0; filter: none;
  }
  .orchestration-event:hover, .orchestration-event:active { background: none; scale: none; filter: none; }
  .orchestration-event:hover .line, .orchestration-event:focus-visible .line { color: var(--color-grey-80); text-decoration: underline; }
  .line { display: inline-flex; align-items: center; gap: var(--spacing-2, 8px); }
  .event-icon {
    flex: none; width: 16px; height: 16px; background-color: var(--color-primary-start);
    -webkit-mask: url("@openmates/ui/static/icons/chat.svg") center / contain no-repeat;
    mask: url("@openmates/ui/static/icons/chat.svg") center / contain no-repeat;
  }
  .report-text {
    display: -webkit-box; -webkit-line-clamp: 4; line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden;
    white-space: pre-wrap; max-width: 560px; color: var(--color-grey-70);
  }
</style>
