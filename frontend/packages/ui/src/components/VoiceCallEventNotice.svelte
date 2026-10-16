<script lang="ts">
  import { text } from '../i18n/translations';
  import type { VoiceCallHistoryEvent } from '../services/voiceCallLifecycleEvent';
  let { event }: { event: VoiceCallHistoryEvent } = $props();
  let timestamp = $derived(new Date(event.created_at * 1000));
  let time = $derived(timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
</script>
<span class="voice-call-event" data-testid={`voice-call-${event.action}`}>
  <span class="call-icon" aria-hidden="true"></span>
  <span>{$text(`voice_call_events.${event.action}`)} – <time datetime={timestamp.toISOString()}>{time}</time></span>
</span>
<style>
  .voice-call-event { display: inline-flex; align-items: center; gap: var(--spacing-2, 8px); color: var(--color-grey-60); }
  .call-icon {
    flex: none;
    width: 16px;
    height: 16px;
    background-color: var(--color-primary-start);
    -webkit-mask: url("@openmates/ui/static/icons/audiocall.svg") center / contain no-repeat;
    mask: url("@openmates/ui/static/icons/audiocall.svg") center / contain no-repeat;
  }
</style>
