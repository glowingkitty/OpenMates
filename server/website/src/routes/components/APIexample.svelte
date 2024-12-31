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
     */
    function formatOutput(outputDict: Record<string, any>): string {
        // Initialize an array to hold formatted lines
        let formatted = ['{'];

        // Iterate over each key-value pair in the dictionary
        for (const [key, value] of Object.entries(outputDict)) {
            // Determine the display string based on the value type
            let displayValue = '';

            if (typeof value === 'string') {
                // For string values, wrap them in quotes
                displayValue = `"${value}"`;
            } else if (Array.isArray(value)) {
                // For arrays, convert them to a JSON string
                displayValue = JSON.stringify(value, null, 4);
            } else if (typeof value === 'object' && value !== null) {
                // For nested objects, recursively format them
                displayValue = JSON.stringify(value, null, 4);
            } else {
                // For other types (number, boolean, etc.), convert to string
                displayValue = String(value);
            }

            // Construct the formatted line with proper styling
            formatted.push(
                `    <span class="syntax">{"{"}</span>`,
                `    <span class="key">"${key}"</span><span class="syntax">:</span> <span class="value">${displayValue}</span>,`
            );
        }

        // Remove the trailing comma from the last entry
        if (formatted.length > 1) {
            formatted[formatted.length - 1] = formatted[formatted.length - 1].replace(/,$/, '');
        }

        // Close the JSON-like structure
        formatted.push('<span class="syntax">{"}"}</span>');

        // Join all lines into a single string separated by newlines
        return formatted.join('\n');
    }
</script>

<div class="api-example">
    <div class="response">
        <pre class="output"><span class="syntax">{"{"}</span>
{#each Object.entries(output) as [key, value], index}
    <span class="key">"{key}"</span><span class="syntax">:</span> <span class="value">{typeof value === 'string' ? `"${value}"` : JSON.stringify(value)}</span>{#if index < Object.keys(output).length - 1},{/if}
{/each}
<span class="syntax">{"}"}</span></pre>
    </div>

    <div class="request" class:smaller={isSmaller}>
        <div class="endpoint">
            <span class="method">{method}</span> {endpoint}
        </div>
        <pre class="input">{input}</pre>
    </div>
</div>

<style>
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

    .request.smaller {
        bottom: 175px;
    }

    .response {
        position: absolute;
        top: 0;
        left: 0;
        bottom: 0;
        padding: 20px;
        padding-top: 110px;
    }

    .endpoint {
        margin-bottom: 1rem;
        color: #848484;
    }

    .method {
        color: #CC4379;
    }

    .input, .output {
        color: #4CA47F;
        white-space: pre-wrap;
        margin: 0;
    }

    pre {
        font-family: 'Fira Code', monospace;
        font-size: 12px;
        font-weight: 600;
    }

    .key {
        color: #CC4379;
        display: inline-block;
        /* margin-left: -30px; */
    }

    .value {
        color: #4CA47F; /* Green color for values */
    }

    .syntax {
        color: #FFFFFF; /* White color for syntax characters like ":" and "{" "}" */
    }
</style>
