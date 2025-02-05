<script lang="ts">
    import {
		HeroHeader,
        Highlights,
        DesignGuidelines,
        Community,
        LargeSeparator,
        MetaTags,
        // Config
        getMetaTags
    } from '@repo/ui';
    const meta = getMetaTags('for_all_of_us');
</script>

<!-- Render meta tags -->
<MetaTags {...meta} />

<HeroHeader />

<!-- Render a large separator after header -->
<LargeSeparator after_header={true} />

<!-- Highlights section -->
<section>
    <Highlights target="for_all" />
</section>

<!-- Design Guidelines section -->
<DesignGuidelines />

<!-- Community section -->
<section>
    <Community />
</section>
