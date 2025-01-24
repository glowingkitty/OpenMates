<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    import { onMount, onDestroy } from 'svelte';
    import hljs from 'highlight.js';
    import 'highlight.js/styles/github-dark.css';
    import 'highlight.js/lib/languages/dockerfile';
    import 'highlight.js/lib/languages/c';
    import 'highlight.js/lib/languages/cpp';
    import 'highlight.js/lib/languages/java';
    import 'highlight.js/lib/languages/javascript';
    import 'highlight.js/lib/languages/python';
    import 'highlight.js/lib/languages/typescript';
    import 'highlight.js/lib/languages/css';
    import 'highlight.js/lib/languages/json';
    import 'highlight.js/lib/languages/rust';
    import 'highlight.js/lib/languages/go';
    import 'highlight.js/lib/languages/ruby';
    import 'highlight.js/lib/languages/php';
    import 'highlight.js/lib/languages/swift';
    import 'highlight.js/lib/languages/kotlin';
    import 'highlight.js/lib/languages/yaml';

    export let src: string;
    export let filename: string;
    export let id: string;
    export let language: string = 'plaintext';

    let codePreview: string = '';
    let isFullscreen = false;
    let messageFieldElement: HTMLElement | null = null;
    let resizeObserver: ResizeObserver | null = null;
    let previewContainer: HTMLElement;

    // Helper function to determine language from filename
    function getLanguageFromFilename(filename: string): string {
        const ext = filename.split('.').pop()?.toLowerCase() || '';

        // Special case for Dockerfile (no extension)
        if (filename.toLowerCase() === 'dockerfile') {
            return 'dockerfile';
        }

        // Improved language map with capitalized names for long names
        const languageMap: { [key: string]: string } = {
            'py': 'Python',
            'js': 'JavaScript',
            'ts': 'TypeScript',
            'html': 'HTML',
            'css': 'CSS',
            'json': 'JSON',
            'svelte': 'Svelte',
            'java': 'Java',
            'cpp': 'C++',
            'c': 'C',
            'h': 'C',
            'rs': 'Rust',
            'go': 'Go',
            'rb': 'Ruby',
            'php': 'PHP',
            'swift': 'Swift',
            'kt': 'Kotlin',
            'yml': 'YAML',
            'yaml': 'YAML',
            'dockerfile': 'Dockerfile'  // Add support for Dockerfile
        };
        return languageMap[ext] || 'Plaintext';
    }

    // Function to update size based on message field dimensions
    function updateSize() {
        if (!isFullscreen || !messageFieldElement || !previewContainer) return;
        
        const messageFieldRect = messageFieldElement.getBoundingClientRect();
        
        // Update container dimensions to match message field
        previewContainer.style.width = `${messageFieldRect.width}px`;
        previewContainer.style.height = `${messageFieldRect.height}px`;
        previewContainer.style.maxHeight = `${messageFieldRect.height}px`;
        
        console.log('Updated code preview size:', { 
            width: messageFieldRect.width, 
            height: messageFieldRect.height 
        });
    }

    // Toggle fullscreen state
    function toggleFullscreen() {
        isFullscreen = !isFullscreen;
        
        // Find message field component and trigger its fullscreen mode
        const messageField = document.querySelector('.message-container');
        if (messageField) {
            const event = new CustomEvent('fullscreenchange', {
                detail: { fullscreen: isFullscreen },
                bubbles: true
            });
            messageField.dispatchEvent(event);
        }
        
        // Find message field element if not already found
        if (!messageFieldElement) {
            messageFieldElement = document.querySelector('.active-chat-container');
        }
        
        if (isFullscreen) {
            // Setup resize observer when entering fullscreen
            if (!resizeObserver && messageFieldElement) {
                resizeObserver = new ResizeObserver(updateSize);
                resizeObserver.observe(messageFieldElement);
            }
        } else {
            // Cleanup resize observer when exiting fullscreen
            if (resizeObserver) {
                resizeObserver.disconnect();
                resizeObserver = null;
            }
            // Reset container styles
            if (previewContainer) {
                previewContainer.style.width = '';
                previewContainer.style.height = '';
                previewContainer.style.maxHeight = '';
            }
        }
        
        // Update size immediately after state change
        updateSize();
    }

    onMount(async () => {
        try {
            const response = await fetch(src);
            const text = await response.text();
            
            language = getLanguageFromFilename(filename);
            
            // Use full text instead of preview
            codePreview = text;
            
            // Highlight code after render
            setTimeout(() => {
                const codeElement = document.querySelector(`#code-${id}`);
                if (codeElement) {
                    hljs.highlightElement(codeElement as HTMLElement);
                }
            }, 0);
            
            console.log('Code preview loaded:', { filename, language });
        } catch (error) {
            console.error('Error loading code preview:', error);
            codePreview = 'Error loading code preview';
        }

        // Initial message field element lookup
        messageFieldElement = document.querySelector('.active-chat-container');
    });

    onDestroy(() => {
        // Cleanup resize observer
        if (resizeObserver) {
            resizeObserver.disconnect();
            resizeObserver = null;
        }
    });
</script>

<InlinePreviewBase {id} type="code" {src} {filename} height={isFullscreen ? 'auto' : '200px'}>
    <div 
        class="preview-container {isFullscreen ? 'fullscreen' : ''}" 
        bind:this={previewContainer}
    >
        <button 
            class="fullscreen-button" 
            on:click={toggleFullscreen}
            aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
        >
            <div class="clickable-icon icon_fullscreen"></div>
        </button>
        
        <div class="code-preview">
            <pre><code id="code-{id}" class="hljs language-{language}">{codePreview}</code></pre>
        </div>
        <div class="info-bar">
            <div class="text-container">
                <span class="filename">{filename}</span>
                <span class="language">{language}</span>
            </div>
        </div>
    </div>
</InlinePreviewBase>

<style>
    .preview-container {
        position: relative;
        width: 100%;
        height: 100%;
        background-color: #181818;
        border-radius: 8px;
        overflow: hidden;
        transition: all 0.3s ease-in-out;
    }

    .preview-container.fullscreen {
        position: fixed;
        top: -150px;
        left: 50%;
        transform: translate(-50%, -50%);
        z-index: 1000;
        border-radius: 24px; /* Match message container border radius */
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.2);
    }

    .fullscreen-button {
        position: absolute;
        top: 8px;
        right: 8px;
        background: none;
        border: none;
        padding: 4px;
        cursor: pointer;
        opacity: 0.5;
        transition: opacity 0.2s ease-in-out;
        z-index: 10;
    }

    .fullscreen-button:hover {
        opacity: 1;
    }

    .code-preview {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 60px; /* Account for info bar */
        padding: 16px;
        overflow: auto;
        max-height: calc(100% - 60px);
    }

    .info-bar {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        border-radius: 30px;
        height: 60px;
        background-color: var(--color-grey-20);
        display: flex;
        align-items: center;
        padding-left: 70px;
        padding-right: 16px;
        z-index: 5;
    }

    .text-container {
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 100%;
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
        height: 100%;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        line-height: 1.4;
    }

    code {
        white-space: pre;
        tab-size: 4;
    }

    :global(.hljs) {
        background: transparent !important;
        padding: 0 !important;
    }

    /* Ensure code is readable in fullscreen */
    .preview-container.fullscreen pre {
        font-size: 14px; /* Larger font size in fullscreen */
    }
</style>
