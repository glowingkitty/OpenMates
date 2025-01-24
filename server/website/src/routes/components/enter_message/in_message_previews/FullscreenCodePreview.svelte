<script lang="ts">
    import hljs from 'highlight.js';
    import { onMount } from 'svelte';
    
    export let code: string;
    export let filename: string;
    export let language: string;
    export let onClose: () => void;

    let codeElement: HTMLElement;

    onMount(() => {
        // Highlight code after render
        if (codeElement) {
            hljs.highlightElement(codeElement);
        }
    });
</script>

<div class="fullscreen-overlay">
    <div class="code-container">
        <div class="header">
            <div class="file-info">
                <span class="filename">{filename}</span>
                <span class="language">{language}</span>
            </div>
            <button 
                class="close-button clickable-icon icon_fullscreen" 
                on:click={onClose}
                aria-label="Close fullscreen view"
            ></button>
        </div>
        <div class="code-content">
            <pre><code bind:this={codeElement} class="hljs language-{language}">{code}</code></pre>
        </div>
    </div>
</div>

<style>
    .fullscreen-overlay {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: var(--color-grey-20);
        border-radius: 17px;
        z-index: 100;
        display: flex;
        flex-direction: column;
    }

    .code-container {
        display: flex;
        flex-direction: column;
        height: 100%;
        padding: 20px;
    }

    .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
    }

    .file-info {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .filename {
        font-size: 18px;
        font-weight: 600;
        color: var(--color-font-primary);
    }

    .language {
        font-size: 14px;
        color: var(--color-font-secondary);
    }

    .close-button {
        padding: 8px;
    }

    .code-content {
        flex: 1;
        overflow: auto;
        background-color: #181818;
        border-radius: 8px;
        padding: 20px;
    }

    pre {
        margin: 0;
        font-family: 'JetBrains Mono', monospace;
        font-size: 14px;
        line-height: 1.5;
    }

    code {
        white-space: pre;
        tab-size: 4;
    }

    :global(.hljs) {
        background: transparent !important;
        padding: 0 !important;
    }
</style> 