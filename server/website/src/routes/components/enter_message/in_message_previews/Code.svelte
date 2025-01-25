<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    import { onMount } from 'svelte';
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
    import 'highlight.js/lib/languages/xml';
    import 'highlight.js/lib/languages/markdown';
    import 'highlight.js/lib/languages/bash';
    import 'highlight.js/lib/languages/shell';
    import 'highlight.js/lib/languages/sql';
    import { createEventDispatcher } from 'svelte';

    export let src: string;
    export let filename: string;
    export let id: string;
    export let language: string = 'plaintext';

    let codePreview: string = '';

    const dispatch = createEventDispatcher();

    // Helper function to determine language from filename
    function getLanguageFromFilename(filename: string): string {
        const ext = filename.split('.').pop()?.toLowerCase() || '';

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
        
        console.log('Detected file extension:', ext);
        console.log('Mapped language:', languageMap[ext] || 'Plaintext');
        
        return languageMap[ext] || 'Plaintext';
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
    });

    // Update the handleFullscreen function
    async function handleFullscreen() {
        try {
            const response = await fetch(src);
            const code = await response.text();
            
            dispatch('fullscreen', {
                code,
                filename,
                language: getLanguageFromFilename(filename)
            });
            
            console.log('Dispatched fullscreen event:', { filename, language });
        } catch (error) {
            console.error('Error loading code content:', error);
        }
    }

    // Update the handleMenuAction function
    function handleMenuAction(action: string) {
        if (action === 'view') {
            handleFullscreen();
        }
    }
</script>

<InlinePreviewBase {id} type="code" {src} {filename} height="200px" on:view={e => handleMenuAction('view')} on:fullscreen={handleFullscreen}>
    <div class="preview-container">
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
    }

    :global(.hljs) {
        background: transparent !important;
        padding: 0 !important;
    }
</style>
