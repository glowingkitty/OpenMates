<script>
    // Props for the API example
    export let input = "";  // Input string
    export let output = { message: "" }; // Initialize with message property
    export let endpoint = ""; // API endpoint
    export let method = "POST"; // HTTP method
    
    // Add import for onMount if you need to trigger animation on component load
    import { onMount } from 'svelte';
    
    // Remove showResponse flag since request will always be visible
    let isSmaller = false;
    
    onMount(() => {
        // Trigger size animation after 1500ms
        setTimeout(() => {
            isSmaller = true;
        }, 1500);
    });
</script>

<div class="api-example">
    <div class="response">
        <pre class="output"><span class="syntax">{"{"}</span>
        <span class="key">"message"</span><span class="syntax">:</span> <span class="string">"{output.message}"</span>
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
        padding-left: 40px;
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
    }

    .string {
        color: #4CA47F;
    }

    .syntax {
        color: #ffffff;
    }
</style>
