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
    import { onMount } from 'svelte';
    
    const meta = getMetaTags('for_all_of_us');
    
    // Add redirect to app.openmates.org
    onMount(() => {
        // Check if we're on the main page and not a subpage
        if (window.location.pathname === '/' || window.location.pathname === '') {
            window.location.href = 'https://app.openmates.org';
        }
    });

    // TESTED: works
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
