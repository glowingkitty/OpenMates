<script lang="ts">
    import MetaTags from '$lib/components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';

    const meta = getMetaTags('docsDesignGuidelines');
</script>

<MetaTags {...meta} />

<h1 class="text-center">Design guidelines</h1>

<h2 class="text-center">Learn how OpenMates is designed & built up.</h2>