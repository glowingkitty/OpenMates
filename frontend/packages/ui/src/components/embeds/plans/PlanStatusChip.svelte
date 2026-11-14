<!--
  PlanStatusChip.svelte
  Small tone-coloured status pill shared by every Plan surface.
-->
<script lang="ts">
  import type { PlanTone } from './planEmbedModel';

  let { label, tone = 'neutral', testId = 'plan-status-chip', status = '' }: {
    label: string;
    tone?: PlanTone;
    testId?: string;
    status?: string;
  } = $props();
</script>

<span class="plan-chip tone-{tone}" data-testid={testId} data-status={status}>{label}</span>

<style>
  .plan-chip { display: inline-flex; align-items: center; width: fit-content; padding: 2px 10px; border-radius: 999px; font-size: var(--font-size-xs); font-weight: 600; line-height: 1.5; white-space: nowrap; background: var(--color-grey-20); color: var(--color-font-secondary); }
  .tone-success { background: var(--color-success-light, var(--color-grey-20)); color: var(--color-success, var(--color-font-primary)); }
  .tone-warning { background: var(--color-warning-light, var(--color-grey-20)); color: var(--color-warning, var(--color-font-primary)); }
  .tone-danger { background: var(--color-error-light, var(--color-grey-20)); color: var(--color-error, var(--color-font-primary)); }
  .tone-info { background: var(--color-grey-20); color: var(--color-font-primary); }
</style>
