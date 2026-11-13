<!--
  frontend/packages/ui/src/components/embeds/code/TestResultStatusBadge.svelte

  Small status-coloured pill (dot + label) shared by the test result preview and
  fullscreen. Colour is carried by the status class, never by hardcoded values.
-->
<script lang="ts">
  interface Props {
    status: string;
    label: string;
    testId?: string;
  }

  let { status, label, testId }: Props = $props();
</script>

<span class="tr-badge tr-{status}" data-testid={testId} data-status={status}>
  <i class="tr-dot" aria-hidden="true"></i>{label}
</span>

<style>
  .tr-badge {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-3);
    padding: var(--spacing-1) var(--spacing-4);
    border-radius: var(--radius-full);
    font-size: var(--font-size-small);
    font-weight: 600;
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    white-space: nowrap;
  }
  .tr-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-grey-50); }
  .tr-passed .tr-dot { background: var(--color-success, var(--color-app-code-start)); }
  .tr-failed .tr-dot, .tr-error .tr-dot, .tr-timed_out .tr-dot { background: var(--color-error); }
  .tr-stale .tr-dot { background: var(--color-warning); }
  .tr-stale { background: var(--color-warning-bg); color: var(--color-warning); }
  .tr-failed, .tr-error, .tr-timed_out { background: var(--color-error-light); color: var(--color-error); }
</style>
