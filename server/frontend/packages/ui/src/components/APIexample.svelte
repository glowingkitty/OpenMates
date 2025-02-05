<script lang="ts">
    export let input = "";
    export let output = {};
    export let endpoint = "";
    export let method = "POST";
    import { onMount } from 'svelte';
    let isSmaller = false;

    onMount(() => {
        setTimeout(() => {
            isSmaller = true;
        }, 1500);
    });

    function formatOutput(outputDict: Record<string, any>): string {
        let formatted = ['<span class="syntax">{"{"}</span>'];
        for (const [key, value] of Object.entries(outputDict)) {
            let displayValue = '';
            if (typeof value === 'string') {
                displayValue = `"${value}"`;
            } else if (Array.isArray(value)) {
                displayValue = `<span class="syntax">[</span>${JSON.stringify(value, null, 4)}<span class="syntax">]</span>`;
            } else if (typeof value === 'object' && value !== null) {
                displayValue = JSON.stringify(value, null, 4);
            } else {
                displayValue = String(value);
            }
            formatted.push(
                `    <span class="key">"${key}"</span><span class="syntax">:</span> <span class="value">${displayValue}</span><span class="syntax">,</span>`
            );
        }
        if (formatted.length > 1) {
            formatted[formatted.length - 1] = formatted[formatted.length - 1].replace(/,<span class="syntax">,<\/span>$/, '</span>');
        }
        formatted.push('<span class="syntax">{"}"}</span>');
        return formatted.join('\n');
    }
</script>

<div class="api-example">
    <div class="response">
        <pre class="output"><span class="syntax">{"{"}</span>{#each Object.entries(output) as [key, value], index}
    <span class="key">"{key}"</span><span class="syntax">:</span>{#if Array.isArray(value)} <span class="syntax">[</span>{#each value as item, i}{#if typeof item === 'object' && item !== null}
    <span class="syntax">{"{"}</span>{#each Object.entries(item) as [itemKey, itemValue], j}
        <span class="key">"{itemKey}"</span><span class="syntax">:</span> 
        <span class="value">{typeof itemValue === 'string' ? `"${itemValue}"` : JSON.stringify(itemValue)}</span>
        {#if j < Object.keys(item).length - 1}<span class="syntax">,</span> {/if}
    {/each}
    <span class="syntax">{"}"}</span>
        {:else}
            <span class="value">{typeof item === 'string' ? `"${item}"` : JSON.stringify(item)}</span>
    {/if}{#if i < value.length - 1}<span class="syntax">,</span> {/if}{/each}<span class="syntax">]</span>
    {:else}
        <span class="value">{typeof value === 'string' ? `"${value}"` : JSON.stringify(value)}</span>
    {/if}
    {#if index < Object.keys(output).length - 1}<span class="syntax">,</span>{/if}
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
    }
    .value {
        color: #4CA47F;
    }
    .syntax {
        color: #FFFFFF;
    }
</style>
