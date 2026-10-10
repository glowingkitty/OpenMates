<script lang="ts">
  import type { Snippet } from 'svelte';

  let { children, message = '', testId }: {
    children?: Snippet;
    message?: string;
    testId?: string;
  } = $props();
</script>

<div class="system-message-notice" role="note" data-testid={testId}>
  {#if children}{@render children()}{:else}{message}{/if}
</div>

<style>
  .system-message-notice {
    max-width: 80%;
    text-align: center;
    padding: var(--spacing-4) var(--spacing-8);
    border-radius: var(--radius-5);
    background: var(--color-grey-10, rgba(255, 255, 255, 0.05));
    font-size: var(--font-size-xs);
    line-height: 1.4;
    color: var(--color-grey-60, #888);
  }
</style>
