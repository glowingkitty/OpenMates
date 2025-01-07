<script lang="ts">
    import Icon from './components/Icon.svelte';
    import AnimatedChatExamples from './components/AnimatedChatExamples.svelte';
    import WaitingList from './components/WaitingList.svelte';
    import Highlights from './components/Highlights.svelte';
    import DesignGuidelines from './components/DesignGuidelines.svelte';
    import Community from './components/Community.svelte';
    import MetaTags from './components/MetaTags.svelte';
    import AppIconGrid from './components/AppIconGrid.svelte';
    import { getMetaTags } from '$lib/config/meta';
    import LargeSeparator from './components/LargeSeparator.svelte';

    const meta = getMetaTags('for_all_of_us');

    // Add reactive variable for current app
    let currentApp = '';

    // Helper function to capitalize first letter
    function capitalize(str: string) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }
</script>

<MetaTags {...meta} />

<!-- Add header section with background color -->
<section class="hero-header">
    <AppIconGrid side="left" />

    <!-- Center space -->
    <div class="center-space">
        <div class="center-content">
            <h1 class="text-center">
                {#if currentApp}
                    <span class="app-title">
                        <span class="visually-hidden">{capitalize(currentApp)} </span>
                        <Icon name={currentApp} type="app" size="67.98px" />
                        Team Mates
                    </span>
                {:else}
                    Digital Team Mates
                {/if}
                <mark><br>For all of us.</mark>
            </h1>
            <p class="text-center platform-text">
                via
                <span class="platform-wrapper">
                    <span class="visually-hidden">Web, </span>
                    <span class="small-icon icon_web"></span>
                </span>
                <span class="platform-wrapper">
                    <span class="visually-hidden">Mattermost, </span>
                    <span class="small-icon icon_mattermost"></span>
                </span>
                <span class="platform-wrapper">
                    <span class="visually-hidden">Discord</span>
                    <span class="small-icon icon_discord"></span>
                </span>
                & more
            </p>
            <div class="chat-container header">
                <AnimatedChatExamples bind:currentApp={currentApp} />
            </div>
            <WaitingList/>
        </div>
    </div>

    <AppIconGrid side="right" />
</section>

<LargeSeparator after_header={true} />

<!-- Highlights -->
<section>
    <Highlights target="for_all" />
</section>


<!-- Design Guidelines -->
<DesignGuidelines />


<!-- Community -->
<section>
    <Community />
</section>

<style>
    .hero-header {
        background-color: var(--color-grey-20);
        width: 100%;
        padding: 2rem 0;
        display: flex;
        justify-content: center;
        align-items: center;
        overflow: hidden;
        position: relative;
        -webkit-mask-image: linear-gradient(to bottom, black, black 85%, transparent);
        mask-image: linear-gradient(to bottom, black, black 85%, transparent);
        height: 90vh;
        min-height: 845px;
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
        width: 100%;
        max-width: 1200px;
        margin: 0 auto;
    }

    .center-content h1,
    .center-content p {
        margin: 0;
    }

    .app-title {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        user-select: all;
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
        user-select: all;
    }

    /* Make sure the icon is included in text selection */
    .app-title :global(svg) {
        user-select: all;
        -webkit-user-select: all;
        -moz-user-select: all;
        -ms-user-select: all;
    }

    .platform-text {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 1.1rem;
        color: #8A8A8A;
        margin-bottom: -0.5rem;
    }

    .platform-wrapper {
        display: inline-flex;
        align-items: center;
        position: relative;
        user-select: all;
    }

    .platform-wrapper :global(.messenger-mattermost),
    .platform-wrapper :global(.messenger-discord),
    .platform-wrapper :global(.messenger-slack) {
        user-select: all;
        -webkit-user-select: all;
        -moz-user-select: all;
        -ms-user-select: all;
    }

    .chat-container {
        position: relative;
        height: 400px;
        width: 100%;
        max-width: 800px;
        overflow: hidden;
        margin: 20px 0;
    }

    .chat-container.header {
        height: 280px;
        /* Add mask/gradient for bottom fade effect */
        -webkit-mask-image: linear-gradient(to bottom, black, black calc(100% - 40px), transparent);
        mask-image: linear-gradient(to bottom, black, black calc(100% - 40px), transparent);
    }

    /* Add media query for mobile devices */
    @media (max-width: 767px) {
        .hero-header {
            position: relative;
            padding-top: 6rem;
        }

    }

    @media (max-width: 600px) {
        .hero-header {
            padding-top: 70px;
        }
    }

</style>