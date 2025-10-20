<script lang="ts">
    import {
        // Components
        Icon,
        WaitingList,
        Highlights,
        DesignGuidelines,
        Community,
        APIexample,
        AppIconGrid,
        // Config
        MetaTags,
        getMetaTags
    } from '@repo/ui';

    const meta = getMetaTags('for_developers');

    // Add reactive variable for current app
    let currentApp = '';

    // Define icon grids based on the original layout
    const leftIconGrid = [
        ['videos', 'health', 'web'],
        ['calendar', 'nutrition', 'language'],
        ['plants', 'fitness', 'shipping'],
        ['shopping', 'jobs', 'books'],
        ['study', 'home', 'tv'],
        ['weather', 'events', 'legal'],
        ['travel', 'photos', 'maps']
    ];
    const rightIconGrid = [
        ['finance', 'business', 'files'],
        ['code', 'pcbdesign', 'audio'],
        ['mail', 'socialmedia', 'messages'],
        ['hosting', 'diagrams', 'news'],
        ['notes', 'whiteboards', 'projectmanagement'],
        ['design', 'publishing', 'pdfeditor'],
        ['slides', 'sheets', 'docs']
    ];

    // Helper function to capitalize first letter
    function capitalize(str: string) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }
</script>

<MetaTags {...meta} />

<!-- Add header section with background color -->
<section class="hero-header">
    <AppIconGrid iconGrid={leftIconGrid} shifted="columns"/>

    <!-- Center space -->
    <div class="center-space">
        <div class="center-content">
            <h1 class="text-center">
                <mark><br>The powerful</mark>
                {#if currentApp}
                    <span class="app-title">
                        <span class="visually-hidden">{capitalize(currentApp)} </span>
                        <Icon name={currentApp} type="app" size="67.98px" />
                        API
                    </span>
                {:else}
                    Digital Team Mates API
                {/if}
            </h1>
            <APIexample
                method="POST"
                endpoint="/api/v1/mates/ask"
                input="I am unhappy in my current job. Any ideas in what direction I could go instead?"
                output={{
                    message: "Of course! Since you mentioned that you have a <b>background in marketing</b> and <b>enjoy storytelling</b>, we could look for roles that leverage those skills.<br>To get a better sense of direction, could you tell me:<br>1. What aspects of your previous jobs did you find most fulfilling?"
                }}
            />
            <WaitingList/>
        </div>
    </div>

    <AppIconGrid iconGrid={rightIconGrid} shifted="columns" />
</section>

<div class="large-separator"></div>

<!-- Highlights -->
<section>
    <Highlights target="for_developers" />
</section>

<div class="large-separator" style="rotate: 180deg;"></div>

<!-- Design Guidelines -->
<section>
    <DesignGuidelines />
</section>

<div class="large-separator"></div>

<!-- Community -->
<section>
    <Community />
</section>

<style>
    .hero-header {
        background-color: #f3f3f3;
        width: 100%;
        padding: 2rem 0;
        display: flex;
        justify-content: center;
        align-items: center;
        overflow: hidden;
        position: relative;
        -webkit-mask-image: linear-gradient(to bottom, black, black 85%, transparent);
        mask-image: linear-gradient(to bottom, black, black 85%, transparent);
    }

    /* Updated center content styles */
    .center-space {
        display: flex;
        align-items: flex-start;
        justify-content: center;
        padding-top: 2rem;
        margin-bottom: 80px;
    }

    .center-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.75rem;
    }

    .center-content h1 {
        margin: 0;
    }

    .app-title {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        position: relative;
        vertical-align: middle;
        margin: 0;
        padding: 0;
    }

    /* Add this to ensure the icon aligns properly */
    .app-title :global(.icon) {
        display: inline-flex;
        align-items: center;
        margin: 0;
        padding: 0;
        vertical-align: middle;
    }

    /* Style for hidden text that will be included in copy */
    .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
    }

</style>

<!-- Add the landing-page class to the root element -->
<div class="landing-page">
    <!-- Existing content -->
</div>
