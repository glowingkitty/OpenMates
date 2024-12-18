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

<div class="highlight-container">
    <div class={`highlight-content ${text_side === 'right' ? 'order-2' : 'order-1'}`}>
        <h3 class="subheading">{sub_heading}</h3>
        <!-- Use {@html} with processed text to safely render mark tags -->
        <h2 class="title">{@html processMarkTags(main_heading)}</h2>
        <p class="description">{@html processMarkTags(paragraph)}</p>
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

    .title {
        font-size: 2rem;
        margin-bottom: 1rem;
    }

    .description {
        font-size: 1.1rem;
        line-height: 1.6;
    }
</style>