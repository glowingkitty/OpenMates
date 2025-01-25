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
        <!-- Update fullscreen button to match EnterMessageField style -->
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
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
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
        top: 35px;
        right: 35px;
        z-index: 2;
        opacity: 0.5;
    }

    .close-button:hover {
        opacity: 1;
    }

    /* Update scrollbar styles to match ActivityHistory */
    .code-content {
        position: absolute;
        top: 16px;
        left: 16px;
        right: 16px;
        bottom: 16px;
        background-color: #181818;
        border-radius: 17px;
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.25);
        padding: 20px;
        overflow: auto;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
    }

    .code-content:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }

    .code-content::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }

    .code-content::-webkit-scrollbar-track {
        background: transparent;
    }

    .code-content::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        border: 2px solid transparent;
        transition: background-color 0.2s ease;
    }

    .code-content:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }

    .code-content::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
    }

    /* Add horizontal scrollbar container at top */
    .horizontal-scrollbar-container {
        position: absolute;
        top: 16px;
        left: 16px;
        right: 16px;
        height: 8px;
        background-color: #181818;
        border-radius: 4px;
        overflow: hidden;
        z-index: 1;
    }

    .scrollbar-content {
        height: 100%;
        width: 100%;
        overflow-x: auto;
        overflow-y: hidden;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
    }

    .scrollbar-content:hover {
        scrollbar-color: rgba(128, 128, 128, 0.5) transparent;
    }

    .scrollbar-content::-webkit-scrollbar {
        height: 8px;
    }

    .scrollbar-content::-webkit-scrollbar-track {
        background: transparent;
    }

    .scrollbar-content::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.2);
        border-radius: 4px;
        transition: background-color 0.2s ease;
    }

    .scrollbar-content:hover::-webkit-scrollbar-thumb {
        background-color: rgba(128, 128, 128, 0.5);
    }

    .scrollbar-content::-webkit-scrollbar-thumb:hover {
        background-color: rgba(128, 128, 128, 0.7);
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