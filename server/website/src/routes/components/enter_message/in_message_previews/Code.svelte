<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    import { onMount } from 'svelte';
    import hljs from 'highlight.js';
    import 'highlight.js/styles/github-dark.css';
    import 'highlight.js/lib/languages/dockerfile';

    export let src: string;
    export let filename: string;
    export let id: string;
    export let language: string = 'plaintext';

    let codePreview: string = '';

    // Helper function to determine language from filename
    function getLanguageFromFilename(filename: string): string {
        const ext = filename.split('.').pop()?.toLowerCase() || '';

        // Special case for Dockerfile (no extension)
        if (filename.toLowerCase() === 'dockerfile') {
            return 'dockerfile';
        }

        const languageMap: { [key: string]: string } = {
            'py': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'html': 'html',
            'css': 'css',
            'json': 'json',
            'svelte': 'svelte',
            'java': 'java',
            'cpp': 'cpp',
            'c': 'c',
            'rs': 'rust',
            'go': 'go',
            'rb': 'ruby',
            'php': 'php',
            'swift': 'swift',
            'kt': 'kotlin',
            'yml': 'yaml',
            'yaml': 'yaml',
            'dockerfile': 'dockerfile'  // Add support for Dockerfile
        };
        return languageMap[ext] || 'plaintext';
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
</script>

<InlinePreviewBase {id} type="code" {src} {filename} height="200px">
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
