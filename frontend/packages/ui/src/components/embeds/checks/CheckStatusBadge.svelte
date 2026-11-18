<!--
  frontend/packages/ui/src/components/embeds/checks/CheckStatusBadge.svelte

  Status pill with icon glyph AND text, so status is never conveyed by color alone.
-->
<script lang="ts">
  interface Props {
    status: string;
    label: string;
    testId: string;
  }
  let { status, label, testId }: Props = $props();
  const GLYPH: Record<string, string> = {
    passed: '✓', failed: '✗', error: '!', blocked: '⊘', running: '…', queued: '…',
    waiting_for_confirmation: '◷', cancelled: '–', never_run: '○', stale: '↻',
  };
  let glyph = $derived(GLYPH[status] ?? '○');
</script>

<span class="cb cb-{status}" data-testid={testId} data-status={status}>
  <span class="cb-glyph" aria-hidden="true">{glyph}</span>
  <span class="cb-label">{label}</span>
</span>

<style>
  .cb { display: inline-flex; align-items: center; gap: var(--spacing-2); padding: var(--spacing-1) var(--spacing-4); border-radius: var(--radius-5); font-size: var(--font-size-small); font-weight: 600; background: var(--color-grey-10); color: var(--color-font-secondary); white-space: nowrap; }
  .cb-passed { color: var(--color-app-code-start); }
  .cb-failed, .cb-error { color: var(--color-error); background: var(--color-error-light); }
  .cb-waiting_for_confirmation, .cb-stale { color: var(--color-font-primary); }
</style>
