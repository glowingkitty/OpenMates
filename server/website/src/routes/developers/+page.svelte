<script lang="ts">
    import Header from '../components/Header.svelte';
    import MetaTags from '$lib/components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';

    const meta = getMetaTags('developers');
</script>

<MetaTags {...meta} />
<Header />
<h1><mark>The most powerful</mark><br>AI Agents API</h1>