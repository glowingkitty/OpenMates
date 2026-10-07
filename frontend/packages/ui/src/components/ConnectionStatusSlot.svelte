<script lang="ts">
  import ConnectionStatusIndicator from './ConnectionStatusIndicator.svelte';
  import type { ConnectionFeedbackState } from '../stores/connectionFeedbackStore';

  interface Props {
    state: ConnectionFeedbackState;
    label: string;
    retryLabel: string;
    onReconnect?: () => void;
    withGap?: boolean;
  }
  let { state, label, retryLabel, onReconnect, withGap = true }: Props = $props();
</script>

<div
  class="connection-status-slot"
  class:active={state !== 'idle'}
  class:with-gap={withGap}
  data-testid="connection-status-slot"
>
  <ConnectionStatusIndicator {state} {label} {retryLabel} {onReconnect} />
</div>

<style>
  .connection-status-slot {
    flex: 0 0 auto;
    width: 0;
    height: 30px;
    margin-inline-start: 0;
    opacity: 0;
    overflow: hidden;
    transition: width 200ms ease, margin-inline-start 200ms ease, opacity 150ms ease;
  }
  .active { width: 30px; opacity: 1; }
  .active.with-gap { margin-inline-start: 8px; }
  @media (prefers-reduced-motion: reduce) {
    .connection-status-slot { transition: none; }
  }
</style>
