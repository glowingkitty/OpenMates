<script>
    // Props for the API example
    export let input = "";  // Input string
    export let output = { message: "" }; // Initialize with message property
    export let endpoint = ""; // API endpoint
    export let method = "POST"; // HTTP method
    
    // Add import for onMount if you need to trigger animation on component load
    import { onMount } from 'svelte';
    
    // Flag to control animation state
    let showResponse = false;
    
    onMount(() => {
        // Trigger animation after 1500ms
        setTimeout(() => {
            showResponse = true;
        }, 1500);
    });
</script>

<div class="api-example">
    {#if showResponse}
        <div class="response" class:show={showResponse}>
            <div class="endpoint">
                <span class="method">{method}</span> {endpoint}
            </div>
            <pre class="output">{"{"}<br/>    <span class="key">"message"</span>: <span class="string">"{output.message}"</span><br/>{"}"}</pre>
        </div>
    {/if}
    
    <div class="request">
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
    }

    .request {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: #242424;
        border-radius: 8px;
        padding: 1rem;
        transition: height 0.5s ease;
    }

    .request.smaller {
        height: 70px;
    }

    .response {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        border-radius: 8px;
        padding: 1rem;
        transform: translateY(100%);
        transition: transform 0.5s ease, height 0.5s ease;
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
    }

    .key {
        color: #CC4379;
    }

    .string {
        color: #4CA47F;
    }
</style>
