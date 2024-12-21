<script lang="ts">
    import MetaTags from '$lib/components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';

    const meta = getMetaTags('docsRoadmap');
</script>

<MetaTags {...meta} />

<h1 class="text-center">Roadmap</h1>
<h2 class="text-center">Learn what’s next for OpenMates</h2>