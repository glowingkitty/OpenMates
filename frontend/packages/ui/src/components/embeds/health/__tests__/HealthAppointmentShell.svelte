<script lang="ts">
  import type { Snippet } from 'svelte';
  let { details }: { details: Snippet<[{ isMobile: boolean }]> } = $props();
</script>

{@render details({ isMobile: false })}
