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

<div
    class="highlight-container"
    style="flex-direction: {text_side === 'left' ? 'row' : 'row-reverse'};">
    <!-- Text content with conditional alignment -->
    <div
        class="highlight-content"
        style="text-align: {text_side === 'left' ? 'right' : 'left'};
        {text_side === 'left' ? 'margin-right: 50px;' : 'margin-left: 50px;'}">
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
        position: relative;
        width: calc(100vw + 100px);
        left: -50px;
        margin: 0;
        overflow: visible;
        margin-top: 80px;
        margin-bottom: 80px;
    }

    /* Content styles */
    .highlight-content {
        width: 40%;
        margin-left: 80px;
        margin-right: 80px;
        box-sizing: border-box;
    }

    /* Visual block styles */
    .highlight-visual {
        width: 60%;
        min-height: 309px;
        height: 50vh;
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