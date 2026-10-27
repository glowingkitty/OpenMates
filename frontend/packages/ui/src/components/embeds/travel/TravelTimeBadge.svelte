<!-- Shared day/night time pill used by connection previews and segment details. -->
<script lang="ts">
  import { text } from '@repo/ui';
  let { time, isDaytime, changed = false }: { time: string; isDaytime?: boolean; changed?: boolean } = $props();
</script>
<span class="time-badge" class:daytime={isDaytime === true} class:nighttime={isDaytime === false} data-testid="travel-time-badge">
  {#if typeof isDaytime === 'boolean'}<span class="time-icon" aria-label={$text(isDaytime ? 'result_embed.daytime' : 'result_embed.nighttime')}>{isDaytime ? '☀' : '🌙'}</span>{/if}
  <span class="time-text" class:changed>{time}</span>
</span>
<style>
  .time-badge { display: inline-flex; align-items: center; justify-content: center; gap: var(--spacing-2); padding: 4px 10px; border-radius: 58px; font-size: 0.875rem; font-weight: 700; color: var(--color-font-primary); background: var(--color-grey-20); white-space: nowrap; }
  .time-badge.nighttime { background: linear-gradient(to right, #365dad, #1745a1); color: white; }
  .time-badge.daytime { background: linear-gradient(to right, #f5bb12, #e79600); color: white; }
  .time-icon { font-size: 0.75rem; line-height: 1; }
  .time-text { line-height: 1; }
</style>
