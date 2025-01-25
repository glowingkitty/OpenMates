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
        console.log('Fullscreen code preview mounted:', { filename, language });
    });
</script>

<div class="fullscreen-overlay">
    <div class="code-container">
        <!-- Fullscreen button at top right -->
        <button 
            class="close-button clickable-icon icon_fullscreen" 
            on:click={onClose}
            aria-label="Close fullscreen view"
        ></button>

        <!-- Code content area -->
        <div class="code-content">
            <pre><code bind:this={codeElement} class="hljs language-{language}">{code}</code></pre>
        </div>

        <!-- Info bar at bottom -->
        <div class="info-bar">
            <div class="icon_rounded code"></div>
            <div class="text-container">
                <span class="filename">{filename}</span>
                <span class="language">{language}</span>
            </div>
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
        padding: 16px;
        position: relative;
    }

    .close-button {
        position: absolute;
        top: 16px;
        right: 16px;
        padding: 8px;
        z-index: 2;
    }

    .code-content {
        position: absolute;
        top: 16px;
        left: 16px;
        right: 16px;
        bottom: 16px;
        background-color: #181818;
        border-radius: 8px;
        padding: 20px;
        overflow: auto;
    }

    .info-bar {
        position: absolute;
        bottom: 32px;
        left: 50%;
        transform: translateX(-50%);
        height: 60px;
        background-color: var(--color-grey-20);
        border-radius: 30px;
        display: flex;
        align-items: center;
        padding: 0 16px 0 70px;
        min-width: 200px;
        z-index: 3;
        user-select: none; /* Prevent text selection */
    }

    .icon_rounded {
        position: absolute;
        top: 50%;
        transform: translateY(-50%);
    }

    .text-container {
        display: flex;
        flex-direction: column;
        justify-content: center;
        line-height: 1.3;
    }

    .filename {
        font-size: 16px;
        color: var(--color-font-primary);
    }

    .language {
        font-size: 16px;
        color: var(--color-font-secondary);
    }

    pre {
        margin: 0;
        font-family: 'JetBrains Mono', monospace;
        font-size: 14px;
        line-height: 1.5;
        height: 100%;
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