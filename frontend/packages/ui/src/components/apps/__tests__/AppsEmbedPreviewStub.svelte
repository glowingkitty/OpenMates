<script lang="ts">
  let { embedId, onFullscreen }: { embedId: string; onFullscreen: () => void } = $props();
</script>
<button data-testid={embedId} onclick={onFullscreen}>{embedId}</button>
