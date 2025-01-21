<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    import { onMount } from 'svelte';
    import hljs from 'highlight.js';
    import 'highlight.js/styles/github-dark.css';
    
    export let src: string;
    export let filename: string;
    export let id: string;
    export let language: string = 'plaintext';

    let codePreview: string = '';
    let fileExtension: string = '';

    // Helper function to determine language from filename
    function getLanguageFromFilename(filename: string): string {
        const ext = filename.split('.').pop()?.toLowerCase() || '';
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
            'kt': 'kotlin'
        };
        return languageMap[ext] || 'plaintext';
    }

    onMount(async () => {
        try {
            // Fetch and process the code file
            const response = await fetch(src);
            const text = await response.text();
            
            // Get file extension and language
            fileExtension = filename.split('.').pop()?.toLowerCase() || '';
            language = getLanguageFromFilename(filename);
            
            // Create preview (first few lines, max 200 chars)
            codePreview = text.split('\n').slice(0, 8).join('\n').substring(0, 200);
            if (text.length > 200) codePreview += '...';
            
            // Highlight the code after the next render cycle
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
    <div class="code-preview-container">
        <div class="code-header">
            <div class="file-icon"></div>
            <span class="filename">{filename}</span>
            <span class="language-badge">{language}</span>
        </div>
        <pre class="code-content"><code id="code-{id}" class="hljs language-{language}">{codePreview}</code></pre>
    </div>
</InlinePreviewBase>

<style>
    .code-preview-container {
        width: 100%;
        height: 100%;
        background-color: var(--color-grey-10);
        border-radius: 16px;
        overflow: hidden;
        display: flex;
        flex-direction: column;
    }

    .code-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px;
        background-color: var(--color-grey-20);
        border-bottom: 1px solid var(--color-grey-30);
    }

    .file-icon {
        width: 20px;
        height: 20px;
        background-image: var(--icon-code);
        background-size: contain;
        background-repeat: no-repeat;
        opacity: 0.7;
    }

    .filename {
        flex: 1;
        font-size: 14px;
        color: var(--color-font-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .language-badge {
        font-size: 12px;
        padding: 2px 6px;
        background-color: var(--color-grey-30);
        border-radius: 4px;
        color: var(--color-font-secondary);
    }

    .code-content {
        flex: 1;
        margin: 0;
        padding: 12px;
        overflow: auto;
        font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
        line-height: 1.4;
        background-color: transparent;
    }

    :global(.hljs) {
        background: transparent !important;
        padding: 0 !important;
    }

    code {
        white-space: pre;
        tab-size: 4;
    }
</style>
