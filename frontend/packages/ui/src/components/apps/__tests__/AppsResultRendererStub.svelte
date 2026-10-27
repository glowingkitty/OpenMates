<script lang="ts">
  let { data }: { data?: { decodedContent: Record<string, unknown> } } = $props();
  let draft = $state('');
</script>
{#if data}
  <div data-testid="result-title">{String(data.decodedContent.title)}</div>
  <textarea aria-label="Unsent followup" bind:value={draft}></textarea>
{:else}
  <div data-testid="result-loading">Loading</div>
{/if}
