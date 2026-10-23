<script lang="ts">
  import { text } from "../i18n/translations";

  let { count = 1 }: { count?: number } = $props();
</script>

{#if count > 1}
  <span
    class="notification-repeat-count"
    data-testid="notification-repeat-count"
    role="img"
    aria-label={$text("notifications.occurrence_count", { values: { count } })}
  >
    <span aria-hidden="true">×{count}</span>
  </span>
{/if}

<style>
  .notification-repeat-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    min-width: 1.75rem;
    padding: 0.125rem 0.375rem;
    border-radius: 999px;
    background: var(--color-grey-30);
    color: var(--color-font-primary);
    font-size: 0.75rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    line-height: 1.5;
    white-space: nowrap;
  }
</style>
