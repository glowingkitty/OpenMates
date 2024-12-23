<script lang="ts">
    import Header from '../components/Header.svelte';
    import MetaTags from '../components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';

    const meta = getMetaTags('docs');
</script>

<MetaTags {...meta} />
<Header />

<h1 class="text-center">Documentation</h1>

<h2 class="text-center">What would you like to know?</h2>