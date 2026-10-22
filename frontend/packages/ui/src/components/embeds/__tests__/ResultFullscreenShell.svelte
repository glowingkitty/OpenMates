<script lang="ts">
  import type { Snippet } from 'svelte';
  let { fixedBottom }: { fixedBottom?: Snippet } = $props();
</script>
{#if fixedBottom}{@render fixedBottom()}{/if}
