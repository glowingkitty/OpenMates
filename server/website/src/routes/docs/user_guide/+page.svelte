<script lang="ts">
    import MetaTags from '$lib/components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';

    const meta = getMetaTags('docsUserGuide');
</script>

<MetaTags {...meta} />

<h1 class="text-center">User guide</h1>

<h2 class="text-center">Learn how to use OpenMates.</h2>