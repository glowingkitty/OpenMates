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
    <!-- Main icon and headline section -->
    <div class="header">
        <div class="main-icon {main_icon}"></div>
        <h2>{@html sanitizeHtml(headline)}</h2>
    </div>

    <!-- Subheadings grid -->
    <div class="subheadings-grid">
        {#each subheadings as { icon, heading, link }}
            <div
                class="subheading-item"
                on:click={() => handleSubheadingClick(link)}
                on:keydown={(e) => e.key === 'Enter' && handleSubheadingClick(link)}
                role="button"
                tabindex="0"
            >
                <div class="{icon}"></div>
                <h3>{@html sanitizeHtml(heading)}</h3>
                {#if link}
                    <div class="learn-more">
                        Learn more
                        <span class="arrow">→</span>
                    </div>
                {/if}
            </div>
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
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        padding: 2rem;
        max-width: 1200px;
        margin: 0 auto;
    }

    .header {
        margin-bottom: 3rem;
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

    h2 {
        font-size: 2.5rem;
        font-weight: 600;
        color: var(--text-color);
        margin-bottom: 2rem;
    }

    .subheadings-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        gap: 2rem;
        width: 100%;
        margin-bottom: 3rem;
    }

    .subheading-item {
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

    .subheading-item h3 {
        font-size: 1.2rem;
        margin: 1rem 0 0.5rem;
        color: var(--text-color);
    }

    .learn-more {
        color: var(--color-primary);
        font-size: 0.9rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
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
        font-size: 1.1rem;
        line-height: 1.6;
        margin-bottom: 2rem;
        color: var(--text-color);
    }

    .sub-text {
        font-size: 1rem;
        color: var(--text-color-secondary);
    }

    .subheading-item div[class] {
        width: 61px;
        height: 61px;
    }
</style>
