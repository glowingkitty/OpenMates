<script lang="ts">
    import Icon from './components/Icon.svelte';
    import AnimatedChatExamples from './components/AnimatedChatExamples.svelte';
    import WaitingList from './components/WaitingList.svelte';
    import Highlights from './components/Highlights.svelte';
    import DesignGuidelines from './components/DesignGuidelines.svelte';
    import Community from './components/Community.svelte';
    import MetaTags from './components/MetaTags.svelte';
    import { getMetaTags } from '$lib/config/meta';
    import LargeSeparator from './components/LargeSeparator.svelte';

    const meta = getMetaTags('for_all_of_us');

    // Define icon groups for left and right sides
    const header_app_icons: Array<Array<{type: 'app' | 'default' | 'skill' | 'provider' | 'focus', name: string}>> = [
        // Left side | First column
        [
            {type: 'app', name: 'videos'},
            {type: 'app', name: 'calendar'},
            {type: 'app', name: 'plants'},
            {type: 'app', name: 'shopping'},
            {type: 'app', name: 'study'},
            {type: 'app', name: 'weather'},
            {type: 'app', name: 'travel'}
        ],
        // Left side | Second column
        [
            {type: 'app', name: 'health'},
            {type: 'app', name: 'nutrition'},
            {type: 'app', name: 'fitness'},
            {type: 'app', name: 'jobs'},
            {type: 'app', name: 'home'},
            {type: 'app', name: 'events'},
            {type: 'app', name: 'photos'}
        ],
        // Left side | Third column
        [
            {type: 'app', name: 'web'},
            {type: 'app', name: 'language'},
            {type: 'app', name: 'shipping'},
            {type: 'app', name: 'books'},
            {type: 'app', name: 'tv'},
            {type: 'app', name: 'legal'},
            {type: 'app', name: 'maps'}
        ],
        // Right side | First column
        [
            {type: 'app', name: 'finance'},
            {type: 'app', name: 'code'},
            {type: 'app', name: 'mail'},
            {type: 'app', name: 'hosting'},
            {type: 'app', name: 'notes'},
            {type: 'app', name: 'design'},
            {type: 'app', name: 'slides'}
        ],
        // Right side | Second column
        [
            {type: 'app', name: 'business'},
            {type: 'app', name: 'pcbdesign'},
            {type: 'app', name: 'socialmedia'},
            {type: 'app', name: 'diagrams'},
            {type: 'app', name: 'whiteboards'},
            {type: 'app', name: 'publishing'},
            {type: 'app', name: 'sheets'}
        ],
        // Right side | Third column
        [
            {type: 'app', name: 'files'},
            {type: 'app', name: 'audio'},
            {type: 'app', name: 'messages'},
            {type: 'app', name: 'news'},
            {type: 'app', name: 'projectmanagement'},
            {type: 'app', name: 'pdfeditor'},
            {type: 'app', name: 'docs'}
        ]
    ]

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
    <!-- Left side icons -->
    <div class="icon-grid left">
        {#each header_app_icons.slice(0, 3) as column}
            <div class="icon-column">
                {#each column as icon}
                    <div class="icon-wrapper" data-app={icon.name}>
                        <Icon name={icon.name} type={icon.type} in_header={true}/>
                    </div>
                {/each}
            </div>
        {/each}
    </div>

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

    <!-- Right side icons -->
    <div class="icon-grid right">
        {#each header_app_icons.slice(3) as column}
            <div class="icon-column">
                {#each column as icon}
                    <div class="icon-wrapper" data-app={icon.name}>
                        <Icon name={icon.name} type={icon.type} in_header={true} />
                    </div>
                {/each}
            </div>
        {/each}
    </div>
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
        background-color: var(--color-background-grey);
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

    .icon-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        align-content: start;
    }

    .icon-column {
        display: flex;
        flex-direction: column;
        align-items: center;
        margin-top: -5rem;
    }

    .icon-column:nth-child(2) {
        transform: translateY(-2rem);
    }

    .icon-wrapper {
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.2;
        transition: opacity 0.3s ease;
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

    @media (max-width: 600px) {
        .icon-grid.left {
            padding-right: 20px;
            margin-right: -20px;
        }
    }

    /* Add media query for mobile devices */
    @media (max-width: 767px) {
        .hero-header {
            position: relative;
            padding-top: 6rem;
        }

        .icon-grid {
            position: absolute;
            top: 1rem;
            display: flex;
            flex-direction: column;
            gap: 0.1rem;
            width: auto;
            /* Add mask for smooth fade effect */
            -webkit-mask-image: linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.4) 40%, rgba(0,0,0,0) 100%);
            mask-image: linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.4) 40%, rgba(0,0,0,0) 100%);
        }

        .icon-grid.left {
            right: 50vw;
        }

        .icon-grid.right {
            left: 50vw;
        }

        /* Hide third column on mobile */
        .icon-grid .icon-column:nth-child(3) {
            display: none;
        }

        .icon-column {
            display: flex;
            flex-direction: row;
            gap: 0.25rem;
            margin-top: 0;
            transform: none;
        }

        /* Adjust shifts for remaining columns */
        .icon-grid.left .icon-column:nth-child(2),
        .icon-grid.right .icon-column:nth-child(2) {
            transform: translateX(24px); /* Reduced shift for better spacing with 2 columns */
        }

        .center-space {
            padding-top: 0;
            padding-left: 30px;
            padding-right: 30px;
            box-sizing: border-box;
            width: 100%;
        }

        /* Increase icon opacity for better visibility */
        .icon-wrapper {
            opacity: 0.3;
        }
    }
</style>