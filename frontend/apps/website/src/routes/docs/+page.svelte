<script lang="ts">
    import {
        // Components
        Header,
        MetaTags,
        // Config
        getMetaTags
    } from '@repo/ui';

    const meta = getMetaTags('docs');
</script>

<MetaTags {...meta} />
<Header context="website" />

<h1 class="text-center">Documentation</h1>

<h2 class="text-center">What would you like to know?</h2>