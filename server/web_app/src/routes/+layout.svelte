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
    import { theme, toggleTheme } from '@website-stores/theme';
    import { replaceOpenMates } from '@website-actions/replaceText';
    import { onMount } from 'svelte';

    // Initialize theme on mount
    onMount(() => {
        const savedTheme = localStorage.getItem('theme') || 'light';
        theme.set(savedTheme);
    });
</script>

<!-- Add theme toggle button -->
<button class="theme-toggle" on:click={toggleTheme}>
    {#if $theme === 'light'}
        🌙
    {:else}
        ☀️
    {/if}
</button>

<main use:replaceOpenMates>
    <slot />
</main>

<style>
    /* Apply background color to the body */
    :global(body) {
        background-color: var(--color-grey-0);
    }

    .theme-toggle {
        position: fixed;
        top: 1rem;
        right: 1rem;
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
        z-index: 1000;
        box-shadow: 0 2px 4px var(--shadow-color);
    }

    .theme-toggle:hover {
        background: var(--background-primary);
    }
</style> 