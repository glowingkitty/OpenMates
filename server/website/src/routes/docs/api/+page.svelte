<script lang="ts">
    import MetaTags from '$lib/components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';

    const meta = getMetaTags('docsApi');
</script>

<MetaTags {...meta} />

<h1 class="text-center">API docs</h1>

<h2 class="text-center">Learn to integrate OpenMates into your software.</h2>