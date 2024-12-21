<script lang="ts">
    // Import all necessary styles
    import '$lib/styles/colors.css';
    import '$lib/styles/fonts.css';
    import '$lib/styles/icons.css';
    import '$lib/styles/buttons.css';
    import '$lib/styles/fields.css';
    import '$lib/styles/cards.css';
    import '$lib/styles/chat.css';
    import '$lib/styles/mates.css';
    import '$lib/styles/separators.css';
    import { replaceOpenMates } from '$lib/actions/replaceText';
    import Header from './components/Header.svelte';
    import Footer from './components/Footer.svelte';
</script>

<!-- Header will appear on every page -->
<Header />

<!-- This is where page-specific content will be rendered -->
<main use:replaceOpenMates>
    <slot />
</main>

<!-- Footer will appear on every page -->
<Footer />

<style>
    /* Global styles moved from global.css */
    :global(body) {
        margin: 0;
        overflow-x: hidden;
        position: relative;
        width: 100%;
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
    }
</style>