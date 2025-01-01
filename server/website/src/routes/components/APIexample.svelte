<script lang="ts">
    // Props for the API example
    export let input = "";  // Input string
    export let output = {}; // Updated to accept a dictionary of any shape
    export let endpoint = ""; // API endpoint
    export let method = "POST"; // HTTP method

    // Import onMount if you need to trigger animation on component load
    import { onMount } from 'svelte';

    // Flag to control the size animation of the request block
    let isSmaller = false;

    onMount(() => {
        // Trigger size animation after 1500ms
        setTimeout(() => {
            isSmaller = true;
        }, 1500);
    });

    /**
     * Function to format the output dictionary into a JSON-like string
     * with syntax highlighting based on the specified color scheme.
     * - Keys are wrapped in `{}` and colored red.
     * - Colons are colored white.
     * - Values are colored green.
     * - Additionally, `[`, `]`, and `,` are colored white.
     */
    function formatOutput(outputDict: Record<string, any>): string {
        // Initialize an array to hold formatted lines
        let formatted = ['<span class="syntax">{"{"}</span>']; // Start with `{` in white

        // Iterate over each key-value pair in the dictionary
        for (const [key, value] of Object.entries(outputDict)) {
            // Determine the display string based on the value type
            let displayValue = '';

            if (typeof value === 'string') {
                // For string values, wrap them in quotes
                displayValue = `"${value}"`;
            } else if (Array.isArray(value)) {
                // For arrays, convert them to a JSON string and wrap `[` and `]` in white
                displayValue = `<span class="syntax">[</span>${JSON.stringify(value, null, 4)}<span class="syntax">]</span>`;
            } else if (typeof value === 'object' && value !== null) {
                // For nested objects, recursively format them
                displayValue = JSON.stringify(value, null, 4);
            } else {
                // For other types (number, boolean, etc.), convert to string
                displayValue = String(value);
            }

            // Construct the formatted line with proper styling
            formatted.push(
                `    <span class="key">"${key}"</span><span class="syntax">:</span> <span class="value">${displayValue}</span><span class="syntax">,</span>` // Added comma with syntax span
            );
        }

        // Remove the trailing comma from the last entry
        if (formatted.length > 1) {
            formatted[formatted.length - 1] = formatted[formatted.length - 1].replace(/,<span class="syntax">,<\/span>$/, '</span>'); // Remove comma
        }

        // Close the JSON-like structure with `}` in white
        formatted.push('<span class="syntax">{"}"}</span>');

        // Join all lines into a single string separated by newlines
        return formatted.join('\n');
    }
</script>

<div class="api-example">
    <div class="response">
        <!-- Start JSON output structure -->
        <pre class="output"><span class="syntax">{"{"}</span>
        {#each Object.entries(output) as [key, value], index}
            <!-- Format each key-value pair -->
            <span class="key">"{key}"</span><span class="syntax">:</span> 
            {#if Array.isArray(value)}
                <!-- Handle arrays - display brackets in white -->
                <span class="syntax">[</span>
                {#each value as item, i}
                    {#if typeof item === 'object' && item !== null}
                        <!-- Handle nested objects within arrays -->
                        <span class="syntax">{"{"}</span>
                        {#each Object.entries(item) as [itemKey, itemValue], j}
                            <!-- Format nested object key-value pairs -->
                            <span class="key">"{itemKey}"</span><span class="syntax">:</span> 
                            <span class="value">{typeof itemValue === 'string' ? `"${itemValue}"` : JSON.stringify(itemValue)}</span>
                            <!-- Add comma between object properties -->
                            {#if j < Object.keys(item).length - 1}<span class="syntax">,</span> {/if}
                        {/each}
                        <span class="syntax">{"}"}</span>
                    {:else}
                        <!-- Handle primitive array values -->
                        <span class="value">{typeof item === 'string' ? `"${item}"` : JSON.stringify(item)}</span>
                    {/if}
                    <!-- Add comma between array items -->
                    {#if i < value.length - 1}<span class="syntax">,</span> {/if}
                {/each}
                <span class="syntax">]</span>
            {:else}
                <!-- Handle non-array values -->
                <span class="value">{typeof value === 'string' ? `"${value}"` : JSON.stringify(value)}</span>
            {/if}
            <!-- Add comma between top-level properties -->
            {#if index < Object.keys(output).length - 1}<span class="syntax">,</span>{/if}
        {/each}
        <span class="syntax">{"}"}</span></pre>
    </div>

    <!-- Request section with endpoint and input -->
    <div class="request" class:smaller={isSmaller}>
        <div class="endpoint">
            <span class="method">{method}</span> {endpoint}
        </div>
        <pre class="input">{input}</pre>
    </div>
</div>

<style>
    /* Container styling */
    .api-example {
        position: relative;
        width: 438px;
        height: 267px;
        border-radius: 18px;
        font-family: 'Fira Code', monospace;
        font-size: 12px;
        background-color: #313131;
        overflow: hidden;
    }

    /* Request panel styling */
    .request {
        position: absolute;
        top: 0;
        left: 0;
        bottom: 0;
        background: #242424;
        transition: all 0.5s ease;
        padding: 10px 20px 10px 20px;
        border-radius: 12px;
    }

    /* Animation class for request panel */
    .request.smaller {
        bottom: 175px;
    }

    /* Response panel styling */
    .response {
        position: absolute;
        top: 0;
        left: 0;
        bottom: 0;
        padding: 20px;
        padding-top: 110px;
    }

    /* Endpoint display styling */
    .endpoint {
        margin-bottom: 1rem;
        color: #848484;
    }

    /* HTTP method color */
    .method {
        color: #CC4379;
    }

    /* Input and output text styling */
    .input, .output {
        color: #4CA47F;
        white-space: pre-wrap;
        margin: 0;
    }

    /* Code font styling */
    pre {
        font-family: 'Fira Code', monospace;
        font-size: 12px;
        font-weight: 600;
    }

    /* JSON syntax highlighting colors */
    .key {
        color: #CC4379;  /* Red color for keys */
        display: inline-block;
    }

    .value {
        color: #4CA47F;  /* Green color for values */
    }

    .syntax {
        color: #FFFFFF;  /* White color for brackets, colons, and commas */
    }
</style>
