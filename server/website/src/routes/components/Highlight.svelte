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
            <!-- Background AI provider icons -->
            <div class="highlight-content-container-1">
                <div class="provider-icons">
                    <div class="row_1">
                        <div class="icon provider-icon provider-mistral"></div>
                        <div class="icon provider-icon provider-meta"></div>
                    </div>
                    <div class="row_2">
                        <div class="icon provider-icon provider-openai"></div>
                        <div class="icon provider-icon provider-anthropic"></div>
                    </div>
                </div>
                <!-- Center content wrapper -->
                <div class="center-content">
                    <div class="icon mate"></div>
                    <div class="powered-text">
                        powered by the leading<br>cloud & on-device AI models
                    </div>
                </div>
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

    .highlight-content-container-1 {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }

    /* Visual block styles */
    .highlight-visual {
        position: relative;
        width: 60%;
        min-height: 309px;
        height: 50vh;
        background-color: #F0F0F0;
        border-radius: 12px;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
    }

    .provider-icons {
        opacity: 0.3;
    }

    .row_1, .row_2 {
        display: flex;
        justify-content: center;
        align-items: center;
        width: auto;
        gap: 20px;
        margin-bottom: -70px;
    }

    .row_1 {
        gap: 140px;
    }

    .center-content {
        width: 300px;
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }

    .powered-text {
        color: #818181;
        text-align: center;
        margin-top: 15px;
    }

    .title {
        font-size: 2rem;
        margin-bottom: 1rem;
    }

    .description {
        font-size: 1.1rem;
        line-height: 1.6;
    }

    .icon{
        filter: drop-shadow(0 0 10px rgba(0, 0, 0, 0.1));
    }
</style>