<!--
  Legacy Project detail route.
  Projects now use the root app's hash-state navigation model, so direct nested
  route visits are redirected to /#project-id=<id>. Keeping this
  small redirect prevents existing links from dead-ending while the canonical UI
  stays in the root route shell.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';

  onMount(() => {
    const projectId = page.params.project_id;
    if (!projectId) return;
    void goto(`/#project-id=${encodeURIComponent(projectId)}`, { replaceState: true });
  });
</script>

<main class="project-route-redirect" data-testid="project-route-redirect">Opening project...</main>

<style>
  .project-route-redirect {
    min-height: calc(100vh - 90px);
    display: grid;
    place-content: center;
    color: var(--color-font-primary);
  }
</style>
