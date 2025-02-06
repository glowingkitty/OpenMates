<script lang="ts">
    import {
        MetaTags,
        Terms,
        getMetaTags
    } from '@repo/ui';

    const meta = getMetaTags('legalTerms');
</script>

<MetaTags {...meta} />
<Terms />
