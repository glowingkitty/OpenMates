<script lang="ts">
    // Import all necessary styles
    import '$lib/styles/fonts.css';
    import '$lib/styles/icons.css';
    import '$lib/styles/buttons.css';
    import '$lib/styles/fields.css';
    import '$lib/styles/cards.css';
    import '$lib/styles/chat.css';
    import '$lib/styles/mates.css';
    import '$lib/styles/theme.css';
    import { replaceOpenMates } from '$lib/actions/replaceText';
    import Header from './components/Header.svelte';
    import Footer from './components/Footer.svelte';
    import MetaTags from './components/MetaTags.svelte';
    import { theme, toggleTheme, initializeTheme } from '$lib/stores/theme';
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';

    // Initialize theme on mount
    onMount(() => {
        initializeTheme();
    });

    // Reset to system preference
    function resetToSystemPreference() {
        if (browser) {
            localStorage.removeItem('theme_preference');
            localStorage.removeItem('theme');
            initializeTheme();
        }
    }

    // Helper function to safely check localStorage
    function getThemePreference() {
        if (browser) {
            return localStorage?.getItem('theme_preference');
        }
        return null;
    }

    // Watch theme changes and update document attribute
    $: if (browser) {
        document.documentElement.setAttribute('data-theme', $theme);
    }
</script>

<!-- Default meta tags for all pages -->
<MetaTags />

<!-- Header will appear on every page -->
<Header />

<!-- This is where page-specific content will be rendered -->
<main use:replaceOpenMates>
    <slot />
</main>

<!-- Footer will appear on every page -->
<Footer />

<!-- Add theme toggle buttons -->
<div class="theme-controls">
    <button class="theme-toggle" on:click={toggleTheme}>
        {#if $theme === 'light'}
            🌙
        {:else}
            ☀️
        {/if}
    </button>
    
    <!-- Only show reset button if manually overridden -->
    {#if browser && getThemePreference() === 'manual'}
        <button class="reset-theme" on:click={resetToSystemPreference}>
            🔄
        </button>
    {/if}
</div>

<style>
    /* Global styles moved from global.css */
    :global(body) {
        margin: 0;
        overflow-x: hidden;
        position: relative;
        max-width: 100vw;
    }

    :global(section) {
        overflow: hidden;
    }

    :global(.centered) {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-direction: column;
    }

    :global(.content) {
        max-width: 1000px;
        margin: 0 auto;
    }

    /* Main content styling */
    main {
        min-height: calc(100vh - var(--header-height) - var(--footer-height));
        width: 100%;
        max-width: 100%;
        overflow-x: hidden;
    }

    :global(html) {
        overflow-x: hidden;
    }

    .theme-controls {
        position: fixed;
        top: 1rem;
        right: 1rem;
        display: flex;
        gap: 0.5rem;
        z-index: 1000;
    }

    .theme-toggle,
    .reset-theme {
        padding: 0.5rem;
        border-radius: 50%;
        border: none;
        background: var(--background-secondary);
        color: var(--text-primary);
        cursor: pointer;
        width: 40px;
        height: 40px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.2rem;
        box-shadow: 0 2px 4px var(--shadow-color);
    }

    .theme-toggle:hover,
    .reset-theme:hover {
        background: var(--background-primary);
    }

    .reset-theme {
        font-size: 1rem;
    }
</style>