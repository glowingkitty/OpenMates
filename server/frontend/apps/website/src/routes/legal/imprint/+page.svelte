<script lang="ts">
    import {
        // Components
        MetaTags,
        Imprint,
        // Config
        getMetaTags,
    } from '@repo/ui';

    const meta = getMetaTags('legalImprint');
</script>

<MetaTags {...meta} />
<Imprint />
