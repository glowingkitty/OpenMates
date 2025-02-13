<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    import { onMount } from 'svelte';
    import hljs from 'highlight.js';
    import DOMPurify from 'dompurify';
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
    import 'highlight.js/lib/languages/xml';
    import 'highlight.js/lib/languages/markdown';
    import 'highlight.js/lib/languages/bash';
    import 'highlight.js/lib/languages/shell';
    import 'highlight.js/lib/languages/sql';
    import { createEventDispatcher } from 'svelte';
    import { scale } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';

    export let src: string;
    export let filename: string;
    export let id: string;
    export let language: string = 'plaintext';
    export let content: string | undefined = undefined;
    export let lineCount: number | undefined = undefined;
    export let numberedContent: string | undefined = undefined;

    let codePreview: string = '';
    let isTransitioningToFullscreen = false;
    let isTransitioningFromFullscreen = false;

    const dispatch = createEventDispatcher();

    // Add sanitize function
    function sanitizeCode(code: string): string {
        return DOMPurify.sanitize(code, {
            ALLOWED_TAGS: ['span', 'pre', 'code'],
            ALLOWED_ATTR: ['class']
        });
    }

    // Helper function to determine language from filename
    function getLanguageFromFilename(filename: string): string {
        console.log('Getting language for filename:', filename);
        
        // If filename is already a language name with 'code.' prefix, extract it
        if (filename.startsWith('code.')) {
            const lang = filename.substring(5); // Remove 'code.' prefix
            console.log('Extracted language from code. prefix:', lang);
            return lang.charAt(0).toUpperCase() + lang.slice(1); // Capitalize first letter
        }

        const ext = filename.split('.').pop()?.toLowerCase() || '';
        console.log('Extracted extension:', ext);

        // Special cases for files without extensions
        if (filename.toLowerCase() === 'dockerfile') {
            return 'Dockerfile';
        }
        if (filename.toLowerCase() === 'makefile') {
            return 'Makefile';
        }

        // Enhanced language map with more languages
        const languageMap: { [key: string]: string } = {
            // Existing mappings
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
            // New mappings
            'md': 'Markdown',
            'markdown': 'Markdown',
            'sh': 'Shell',
            'bash': 'Bash',
            'sql': 'SQL',
            'vue': 'Vue',
            'jsx': 'JavaScript',
            'tsx': 'TypeScript',
            'xml': 'XML',
            'gradle': 'Gradle',
            'scala': 'Scala',
            'r': 'R',
            'dart': 'Dart',
            'lua': 'Lua',
            'toml': 'TOML',
            'ini': 'INI',
            'conf': 'Config',
            'dockerfile': 'Dockerfile',
            'makefile': 'Makefile'
        };
        
        const mappedLanguage = languageMap[ext] || ext.charAt(0).toUpperCase() + ext.slice(1);
        console.log('Final mapped language:', mappedLanguage);
        
        return mappedLanguage;
    }

    onMount(async () => {
        try {
            let text: string;
            
            // If we have direct content, use it
            if (content) {
                text = content;
            } else {
                // Otherwise fetch from URL
                const response = await fetch(src);
                text = await response.text();
            }
            
            // Calculate line count and numbered content
            const lines = text.split('\n');
            lineCount = lines.length;
            
            // Create numbered content with padding for line numbers
            const maxLineNumberWidth = lineCount.toString().length;
            numberedContent = lines.map((line, index) => 
                `${(index + 1).toString().padStart(maxLineNumberWidth, ' ')} | ${line}`
            ).join('\n');
            
            console.log('Numbered content:', numberedContent);
            
            console.log('Received language:', language);
            
            // Use the provided language directly for highlighting
            const highlightLanguage = language.toLowerCase();
            console.log('Using language for highlighting:', highlightLanguage);
            
            // Sanitize the code before setting it
            const sanitizedCode = DOMPurify.sanitize(text, {
                ALLOWED_TAGS: [], // Only allow text content
                ALLOWED_ATTR: []
            });
            codePreview = sanitizedCode;
            
            // Highlight code after render
            setTimeout(() => {
                const codeElement = document.querySelector(`#code-${id}`);
                if (codeElement) {
                    try {
                        const highlighted = hljs.highlight(sanitizedCode, {
                            language: highlightLanguage
                        }).value;
                        // Sanitize the highlighted HTML
                        codeElement.innerHTML = DOMPurify.sanitize(highlighted, {
                            ALLOWED_TAGS: ['span'],
                            ALLOWED_ATTR: ['class']
                        });
                    } catch (error) {
                        console.warn(`Fallback to auto-detection for language: ${highlightLanguage}`);
                        const highlighted = hljs.highlightAuto(sanitizedCode).value;
                        codeElement.innerHTML = DOMPurify.sanitize(highlighted, {
                            ALLOWED_TAGS: ['span'],
                            ALLOWED_ATTR: ['class']
                        });
                    }
                }
            }, 0);
            
            console.log('Code preview loaded:', { filename, language: highlightLanguage, lineCount });
        } catch (error) {
            console.error('Error loading code preview:', error);
            codePreview = 'Error loading code preview';
        }
    });

    // Update the handleFullscreen function
    async function handleFullscreen() {
        console.log('Handling fullscreen request');
        try {
            isTransitioningToFullscreen = true;
            let code: string;
            
            if (content) {
                code = content;
            } else {
                const response = await fetch(src);
                code = await response.text();
            }

            // Calculate line count here to ensure it's accurate
            const actualLineCount = code.split('\n').length;
            
            console.log('Dispatching fullscreen with line count:', actualLineCount);
            
            dispatch('codefullscreen', {
                code: sanitizeCode(code),
                filename,
                language: getLanguageFromFilename(filename),
                lineCount: actualLineCount // Make sure we're passing the line count
            });
            
            setTimeout(() => {
                isTransitioningToFullscreen = false;
            }, 300);
        } catch (error) {
            console.error('Error loading code content:', error);
            isTransitioningToFullscreen = false;
        }
    }

    // Update the handleMenuAction function
    function handleMenuAction(action: string) {
        console.log('Menu action:', action);
        if (action === 'view') {
            handleFullscreen();
        }
    }

    // Function to handle return from fullscreen
    export function handleReturnFromFullscreen() {
        isTransitioningFromFullscreen = true;
        // Reset the flag after animation completes
        setTimeout(() => {
            isTransitioningFromFullscreen = false;
        }, 300);
    }
</script>

<InlinePreviewBase {id} type="code" {src} {filename} height="200px" on:view={e => handleMenuAction('view')} on:fullscreen={handleFullscreen}>
    <div 
        class="preview-container"
        class:transitioning={isTransitioningToFullscreen}
        class:transitioning-in={isTransitioningFromFullscreen}
    >
        <div class="code-preview">
            <pre><code id="code-{id}" class="hljs language-{language}">{codePreview}</code></pre>
        </div>
        <div class="info-bar">
            <div class="text-container">
                <span class="filename">{filename}</span>
                {#if filename !== 'Code snippet'}
                    <span class="language">{language}</span>
                {/if}
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
        transition: transform 300ms cubic-bezier(0.4, 0, 0.2, 1),
                   opacity 300ms cubic-bezier(0.4, 0, 0.2, 1);
        transform-origin: center center;
    }

    .preview-container.transitioning {
        transform: scale(1.15);
        opacity: 0;
    }

    .preview-container.transitioning-in {
        transform: scale(1);
        opacity: 1;
        animation: scaleIn 300ms cubic-bezier(0.4, 0, 0.2, 1);
    }

    @keyframes scaleIn {
        from {
            transform: scale(1.15);
            opacity: 0;
        }
        to {
            transform: scale(1);
            opacity: 1;
        }
    }

    .code-preview {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        padding: 16px;
        overflow: hidden;
        max-height: 100%;
        transition: opacity 300ms cubic-bezier(0.4, 0, 0.2, 1);
    }

    .transitioning .code-preview {
        opacity: 0;
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
        /* align-items: flex-start; */
        transition: opacity 300ms cubic-bezier(0.4, 0, 0.2, 1);
    }

    .transitioning .info-bar {
        opacity: 0;
    }

    /* Create a container for the stacked text */
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
        overflow: hidden;
    }

    :global(.hljs) {
        background: transparent !important;
        padding: 0 !important;
    }
</style>
