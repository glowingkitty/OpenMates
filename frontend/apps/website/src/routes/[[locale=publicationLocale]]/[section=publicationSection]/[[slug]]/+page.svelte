<script lang="ts">
  import PublicationRoute from '$lib/components/PublicationRoute.svelte';
  import type { PageData } from './$types';
  let { data }: { data: PageData } = $props();
</script>
<PublicationRoute {data} />
