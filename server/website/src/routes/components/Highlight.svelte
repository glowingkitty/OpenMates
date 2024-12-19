<script lang="ts">
    // Define props for the component
    export let main_heading: string;
    export let sub_heading: string;
    export let paragraph: string;
    export let text_side: 'left' | 'right' = 'left'; // Default to left alignment

    // Function to process text and preserve <mark> and <br> tags
    function processMarkTags(text: string): string {
        // First, escape any HTML except <mark> and <br> tags
        const escaped = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            // Restore <mark> tags
            .replace(/&lt;mark&gt;/g, '<mark>')
            .replace(/&lt;\/mark&gt;/g, '</mark>')
            // Restore <br> tags
            .replace(/&lt;br&gt;/g, '<br>');

        return escaped;
    }
</script>

<div class="highlight-container" style="flex-direction: {text_side === 'left' ? 'row' : 'row-reverse'}">
    <!-- Text content with conditional alignment -->
    <div class="highlight-content" style="text-align: {text_side === 'left' ? 'right' : 'left'};">
        <h3 class="subheading">{sub_heading}</h3>
        <h2 class="title">{@html processMarkTags(main_heading)}</h2>
        <p class="description">{@html processMarkTags(paragraph)}</p>
    </div>

    <!-- Visual block with background and shadow -->
    <div class="highlight-visual">
        {#if sub_heading === 'Ask'}
            <div class="powered-text">
                powered by the leading<br>cloud & on-device AI models
            </div>
        {/if}
    </div>
</div>

<style>
    /* Container styles */
    .highlight-container {
        display: flex;
        align-items: center;
        gap: 2rem;
        padding: 2rem;
        max-width: 1200px;
        margin: 0 auto;
    }

    /* Content styles */
    .highlight-content {
        flex: 1;
    }

    /* Visual block styles */
    .highlight-visual {
        width: 309px;
        height: 309px;
        background-color: #F0F0F0;
        border-radius: 12px;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
    }

    .powered-text {
        color: #666;
        font-size: 0.9rem;
        line-height: 1.5;
    }

    .title {
        font-size: 2rem;
        margin-bottom: 1rem;
    }

    .description {
        font-size: 1.1rem;
        line-height: 1.6;
    }
</style>