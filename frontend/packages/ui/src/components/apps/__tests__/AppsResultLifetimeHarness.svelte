<script lang="ts">
  import AppsResultFullscreen from '../AppsResultFullscreen.svelte';
  let { onClose }: { onClose: () => void } = $props();
  let route = $state({ embedId: 'child-one', rootEmbedId: 'root', teamId: undefined as string | undefined });
  export function navigate(next: typeof route) { route = next; }
</script>
<AppsResultFullscreen {...route} appId="health" {onClose} />
