<script lang="ts">
    import {
        MetaTags,
        Privacy,
        getMetaTags
    } from '@repo/ui';

    const meta = getMetaTags('legalPrivacy');
</script>

<MetaTags {...meta} />
<Privacy />
