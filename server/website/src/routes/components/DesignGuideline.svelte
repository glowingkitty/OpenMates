<script lang="ts">
    // Import necessary Svelte components
    import { goto } from '$app/navigation';
    import { routes } from '$lib/config/links';

    // Props definition
    export let main_icon = '';
    export let headline = '';
    export let subheadings: {icon: string; heading: string; link?: string}[] = [];
    export let text = '';
    export let subtext = '';

    // If there are any links to design guidelines or documentation
    const designDocsLink = routes.docs.designGuidelines;

    // Function to sanitize HTML, allowing only <mark> and <br> tags
    function sanitizeHtml(html: string) {
        // Remove all HTML tags except <mark> and <br>
        return html
            .replace(/<(?!\/?(mark|br)(?=>|\s.*>))\/?(?:.|\n)*?>/gm, '')
            // Ensure proper closing of mark tags
            .replace(/<mark>/g, '<mark>')
            .replace(/<\/mark>/g, '</mark>')
            // Ensure self-closing br tags
            .replace(/<br>/g, '<br />');
    }

    // Handle navigation for subheading links
    const handleSubheadingClick = (link?: string) => {
        if (link) {
            goto(link);
        }
    };
</script>

<div class="design-guideline">
    <!-- Add background icons -->
    <div class="background-icon background-icon-left {main_icon}"></div>
    <div class="background-icon background-icon-right {main_icon}"></div>
    
    <!-- Main icon and headline section -->
    <div class="header">
        <div class="main-icon {main_icon}"></div>
        <h2>{@html sanitizeHtml(headline)}</h2>
    </div>

    <!-- Subheadings grid -->
    <div class="subheadings-grid">
        {#each subheadings as { icon, heading, link }}
            <a
                href={link || '#'}
                target={link ? '_blank' : '_self'}
                class="subheading-item"
                on:click|preventDefault={(e) => handleSubheadingClick(link)}
                on:keydown={(e) => e.key === 'Enter' && handleSubheadingClick(link)}
                role="button"
                tabindex="0"
            >
                <div class="{icon}"></div>
                <h4>{@html sanitizeHtml(heading)}</h4>
                {#if link}
                    <div class="learn-more">
                        Learn more
                        <span class="small-icon icon_open"></span>
                    </div>
                {/if}
            </a>
        {/each}
    </div>

    <!-- Main text content -->
    <div class="content">
        <p class="main-text">{@html sanitizeHtml(text)}</p>
        {#if subtext}
            <p class="sub-text">{@html sanitizeHtml(subtext)}</p>
        {/if}
    </div>
</div>

<style>
    .design-guideline {
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        padding: 2rem;
        max-width: 1200px;
        margin: 0 auto;
    }

    .header {
        margin-bottom: 2rem;
    }

    .main-icon {
        width: 96px;
        height: 96px;
        margin: 0 auto 1.5rem;
        mask-size: cover;
        mask-repeat: no-repeat;
        background: var(--color-primary);
    }

    .main-icon.icon_lock {
        mask-image: url('/icons/lock.svg');
    }

    .main-icon.icon_good {
        mask-image: url('/icons/good.svg');
    }


    .subheadings-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 2rem;
        width: 100%;
        margin-bottom: 2rem;
    }

    .subheading-item {
        text-decoration: none;
        color: inherit;
        display: flex;
        flex-direction: column;
        align-items: center;
        cursor: pointer;
        padding: 1rem;
        transition: transform 0.2s ease;
    }

    .subheading-item:hover {
        transform: translateY(-5px);
    }

    .subheading-item h4 {
        margin: 1rem 0 0.5rem;
    }

    .learn-more {
        width: auto;
        color: var(--color-primary);
        display: flex;
        align-items: center;
        gap: 0.5rem;
        white-space: nowrap;
        color: #A9A9A9;
    }

    .arrow {
        transition: transform 0.2s ease;
    }

    .subheading-item:hover .arrow {
        transform: translateX(5px);
    }

    .content {
        max-width: 800px;
        margin: 0 auto;
    }

    .main-text {
        margin-bottom: 2rem;
        color: var(--text-color);
    }

    .sub-text {
        color: var(--text-color-secondary);
    }

    .subheading-item div[class*="icon_"] {
        width: 61px;
        height: 61px;
        background-size: 100%;
        background-repeat: no-repeat;
        background-position: center;
        filter: brightness(0) saturate(100%) invert(50%); /* Convert black to grey */
    }

    /* Separate styles for the small icon in "Learn more" section */
    .small-icon[class*="icon_"] {
        width: 15px;
        height: 15px;
        filter: opacity(50%);
    }

    /* Add new styles for background icons */
    .background-icon {
        position: absolute;
        width: 50vh;
        height: 50vh;
        mask-size: cover;
        mask-repeat: no-repeat;
        background: var(--color-primary);
        opacity: 0.05;
        z-index: -1;
    }

    .background-icon.icon_lock {
        mask-image: url('/icons/lock.svg');
    }

    .background-icon.icon_good {
        mask-image: url('/icons/good.svg');
    }

    .background-icon-left {
        left: -30vw;
        top: 50%;
        transform: translateY(-50%);
    }

    .background-icon-right {
        right: -30vw;
        top: 50%;
        transform: translateY(-50%);
    }
</style>