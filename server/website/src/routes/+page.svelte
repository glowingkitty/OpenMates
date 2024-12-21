<script lang="ts">
    import Header from './components/Header.svelte';
    import Icon from './components/Icon.svelte';
    import AnimatedChatExamples from './components/AnimatedChatExamples.svelte';
    import WaitingList from './components/WaitingList.svelte';
    import Highlights from './components/Highlights.svelte';
    import DesignGuideline from './components/DesignGuideline.svelte';
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

    // Split icons into left and right sides (first 3 columns are left, last 3 are right)
    const leftIcons = header_app_icons.slice(0, 3).flat();
    const rightIcons = header_app_icons.slice(3).flat();

    // Add reactive variable for current app
    let currentApp = '';

    // Helper function to capitalize first letter
    function capitalize(str: string) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }
</script>

<Header />

<!-- Add header section with background color -->
<section class="hero-header">
    <!-- Left side icons -->
    <div class="icon-grid left">
        {#each header_app_icons.slice(0, 3) as column}
            <div class="icon-column">
                {#each column as icon}
                    <div class="icon-wrapper" data-app={icon.name}>
                        <Icon name={icon.name} type={icon.type} />
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
                    AI Team Mates
                {/if}
                <mark><br>For all of us.</mark>
            </h1>
            <p class="text-center platform-text">
                via
                <span class="platform-wrapper">
                    <span class="visually-hidden">Web, </span>
                    <span class="small-icon web"></span>
                </span>
                <span class="platform-wrapper">
                    <span class="visually-hidden">Mattermost, </span>
                    <span class="small-icon mattermost"></span>
                </span>
                <span class="platform-wrapper">
                    <span class="visually-hidden">Discord</span>
                    <span class="small-icon discord"></span>
                </span>
                & more
            </p>
            <AnimatedChatExamples bind:currentApp={currentApp} />
            <WaitingList/>
        </div>
    </div>

    <!-- Right side icons -->
    <div class="icon-grid right">
        {#each header_app_icons.slice(3) as column}
            <div class="icon-column">
                {#each column as icon}
                    <div class="icon-wrapper" style="opacity: 0.2; scale: 0.65;" data-app={icon.name}>
                        <Icon name={icon.name} type={icon.type} />
                    </div>
                {/each}
            </div>
        {/each}
    </div>
</section>

<div class="large-separator"></div>

<!-- Add white body section for future content -->
<section>
    <Highlights target="for_all" />
</section>

<div class="large-separator" style="rotate: 180deg;"></div>

<section>
    <h2>Design Guidelines</h2>
    <DesignGuideline
        main_icon="lock"
        headline="Your privacy matters"
        subheadings={[
            {
                icon: "anonymization",
                heading: "Anonymization",
                link: "/docs/design_guidelines#anonymization"
            },
            {
                icon: "local-processing",
                heading: "Local processing first",
                link: "/docs/design_guidelines#local-processing"
            },
            {
                icon: "self-hosting",
                heading: "Self hosting option",
                link: "/docs/design_guidelines#self-hosting"
            }
        ]}
        text="In today's turbulent world, where profit-at-all-costs companies frequently misuse user data, where companies with inadequate security measures are regularly hacked and their users' data falls into the hands of bad actors, and where we cannot always rely on governments to protect the rights and well-being of their citizens, making decisions to safeguard your privacy has become increasingly essential."
        subtext="Therefore, OpenMates is designed with a focus on privacy."
    />
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

    .web-icon {
        transition: filter 0.2s ease-in-out;
        filter: opacity(0.4);
    }

    .web-icon:hover {
        filter: brightness(0) saturate(100%) invert(48%) sepia(100%) saturate(2000%) hue-rotate(200deg) brightness(100%) contrast(100%);
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
        scale: 0.65;
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
        line-height: 1;
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
        line-height: 0;
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
</style>

<!-- Add the landing-page class to the root element -->
<div class="landing-page">
    <!-- Existing content -->
</div>
