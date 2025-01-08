<script>
    import '@website-styles/buttons.css';
    import '@website-styles/fonts.css';
    import '@website-styles/icons.css';
    import '@website-styles/buttons.css';
    import '@website-styles/fields.css';
    import '@website-styles/cards.css';
    import '@website-styles/chat.css';
    import '@website-styles/mates.css';
    import '@website-styles/theme.css';
    import { theme, toggleTheme, initializeTheme } from '@website-stores/theme';
    import { replaceOpenMates } from '@website-actions/replaceText';
    import { onMount, onDestroy } from 'svelte';
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

<main use:replaceOpenMates>
    <slot />
</main>

<style>
    /* Apply background color to the body */
    :global(body) {
        background-color: var(--color-grey-0);
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