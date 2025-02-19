<script lang="ts">
    import hljs from 'highlight.js';
    import { onMount } from 'svelte';
    import { fade, scale } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import { _ } from 'svelte-i18n';
    
    export let code: string;
    export let filename: string;
    export let language: string;
    export let lineCount: number;
    export let onClose: () => void;

    let codeElement: HTMLElement;
    let lineNumbersElement: HTMLElement;

    // Add function to handle smooth closing
    function handleClose() {
        // First start the scale down animation
        const overlay = document.querySelector('.fullscreen-overlay') as HTMLElement;
        if (overlay) {
            overlay.style.transform = 'scale(0.5)';
            overlay.style.opacity = '0';
        }
        
        // Delay the actual close callback to allow animation to play
        setTimeout(() => {
            onClose();
        }, 300);
    }

    // Function to generate line numbers HTML
    function generateLineNumbers(count: number): string {
        return Array.from({ length: count }, (_, i) => i + 1)
            .map(num => `<div class="line-number">${num}</div>`)
            .join('');
    }

    onMount(() => {
        // Highlight code after render
        if (codeElement) {
            hljs.highlightElement(codeElement);
        }
        
        // Calculate actual line count if not provided
        if (!lineCount) {
            lineCount = code.split('\n').length;
            console.log('Calculated line count:', lineCount);
        }
        
        // Generate line numbers
        if (lineNumbersElement) {
            lineNumbersElement.innerHTML = generateLineNumbers(lineCount);
        }
        
        console.log('Fullscreen code preview mounted:', { filename, language, lineCount });
    });
</script>

<div 
    class="fullscreen-overlay"
    in:scale={{
        duration: 300,
        delay: 0,
        opacity: 0.5,
        start: 0.5,
        easing: cubicOut
    }}
>
    <div class="code-container">
        <!-- Update fullscreen button to match MessageInput style -->
        <button 
            class="close-button clickable-icon icon_fullscreen" 
            on:click={handleClose}
            aria-label={$_('enter_message.exit_fullscreen.text')}
        ></button>

        <!-- Code content area -->
        <div class="code-content">
            <div class="line-numbers-container" bind:this={lineNumbersElement}>
                <!-- Line numbers will be inserted here by generateLineNumbers() -->
            </div>
            <pre><code bind:this={codeElement} class="hljs language-{language}">{code}</code></pre>
        </div>

        <!-- Info bar at bottom -->
        <div class="info-bar">
            <div class="icon_rounded code"></div>
            <div class="text-container">
                <span class="filename">{filename}</span>
                {#if filename !== 'Code snippet'}
                    <span class="language">{language}</span>
                {/if}
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
        transform-origin: center center;
        transition: transform 300ms cubic-bezier(0.4, 0, 0.2, 1),
                    opacity 300ms cubic-bezier(0.4, 0, 0.2, 1);
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
        padding-left: 0px;
        overflow: auto;
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
        transition: scrollbar-color 0.2s ease;
        display: flex;
        align-items: flex-start;
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

    .line-numbers-container {
        position: sticky;
        left: 0;
        background-color: #181818;
        padding: 0 8px;
        text-align: right;
        color: rgba(255, 255, 255, 0.4);
        font-family: 'JetBrains Mono', monospace;
        font-size: 14px;
        line-height: 1.5;
        border-right: 1px solid rgba(128, 128, 128, 0.3);
        margin-right: 1em;
        z-index: 1;
    }

    .line-number {
        height: 1.5em;
        padding-top: 0.1em;
    }

    pre {
        margin: 0;
        font-family: 'JetBrains Mono', monospace;
        font-size: 14px;
        line-height: 1.5;
        height: 100%;
        flex: 1;
        padding-top: 0.1em;
    }

    code {
        white-space: pre;
        tab-size: 4;
    }

    :global(.hljs) {
        background: transparent !important;
        padding: 0 !important;
        padding-bottom: 90px !important;
    }
</style> 