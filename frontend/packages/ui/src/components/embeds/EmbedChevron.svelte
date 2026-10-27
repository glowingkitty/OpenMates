<!-- Canonical fullscreen/header chevron, also used by galleries and carousels. -->
<script lang="ts">
  let { direction }: { direction: 'previous' | 'next' } = $props();
</script>

<span class="embed-chevron" class:previous={direction === 'previous'} aria-hidden="true"></span>

<style>
  .embed-chevron { display: block; width: 12px; height: 12px; border-top: 2.5px solid currentColor; border-right: 2.5px solid currentColor; transform: rotate(45deg); margin-inline-end: 5px; flex-shrink: 0; }
  .previous { transform: rotate(-135deg); margin-inline: 5px 0; }
</style>
