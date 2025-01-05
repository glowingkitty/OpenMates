<script>
    // Import any necessary components or styles
</script>

<slot />

<style>
    /* Apply global styles */
    :global(body) {
        /* Set default font family and size */
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 16px;
        line-height: 1.5;
        margin: 0;
        padding: 0;
        /* Add font weight for bold text */
        font-weight: bold;
    }

    /* Ensure all text elements inherit the font and bold weight */
    :global(*) {
        font-family: inherit;
        font-weight: inherit;
    }
</style> 