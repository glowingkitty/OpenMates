<!-- Shared non-interactive pill for dates and times. -->
<script lang="ts">
  let { label, datetime, testId }: { label: string; datetime?: string; testId?: string } = $props();
</script>

<time class="embed-time-pill" {datetime} data-testid={testId}>{label}</time>

<style>
  .embed-time-pill { display: inline-block; vertical-align: top; box-sizing: border-box; padding: 4px 7px; border-radius: var(--radius-full); background: var(--color-grey-0); color: var(--color-font-primary); box-shadow: var(--shadow-xs); font-size: var(--embed-time-pill-font-size, var(--font-size-xxs)); font-weight: 600; line-height: 1.2; white-space: nowrap; }
</style>
