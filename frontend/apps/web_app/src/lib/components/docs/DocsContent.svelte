<script lang="ts">
    /**
     * DocsContent Component
     * 
     * Renders documentation content with:
     * - HTML content from processed markdown
     * - Table of contents generation
     * - Copy to clipboard functionality
     * - PDF download option
     * - Edit on GitHub link
     */
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    
    // Props
    let { 
        title, 
        content, 
        originalMarkdown
    } = $props<{
        title: string;
        content: string;
        originalMarkdown: string;
    }>();
    
    // State
    let copied = $state(false);
    let tocItems = $state<Array<{ id: string; text: string; level: number }>>([]);
    let contentElement: HTMLDivElement | null = $state(null);
    
    /**
     * Extract table of contents from content
     */
    onMount(() => {
        if (contentElement) {
            const headings = contentElement.querySelectorAll('h2, h3');
            tocItems = Array.from(headings).map(heading => ({
                id: heading.id || '',
                text: heading.textContent || '',
                level: parseInt(heading.tagName.charAt(1))
            }));
        }
    });
    
    /**
     * Copy markdown content to clipboard
     */
    async function copyToClipboard() {
        if (!browser) return;
        
        try {
            await navigator.clipboard.writeText(originalMarkdown);
            copied = true;
            setTimeout(() => {
                copied = false;
            }, 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    }
    
    /**
     * Download content as PDF
     * Uses client-side PDF generation with jsPDF
     * Gracefully handles if jsPDF is not installed
     */
    async function downloadPdf() {
        if (!browser) return;
        
        try {
            // Dynamically import jsPDF (optional dependency)
            // Use string-based import to prevent Vite from statically analyzing it
            const moduleName = 'jspdf';
            const jsPDFModule = await import(/* @vite-ignore */ moduleName).catch(() => null);
            if (!jsPDFModule) {
                alert('PDF generation is not available. Please install jspdf package to enable this feature.');
                return;
            }
            const { jsPDF } = jsPDFModule;
            
            const doc = new jsPDF();
            const pageWidth = doc.internal.pageSize.getWidth();
            const margin = 20;
            const maxWidth = pageWidth - 2 * margin;
            
            // Add title
            doc.setFontSize(20);
            doc.text(title, margin, margin);
            
            // Add content (simplified - strips HTML for basic text)
            doc.setFontSize(12);
            const plainText = originalMarkdown
                .replace(/^#+ /gm, '')  // Remove heading markers
                .replace(/\*\*([^*]+)\*\*/g, '$1')  // Remove bold
                .replace(/\*([^*]+)\*/g, '$1')  // Remove italic
                .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');  // Remove links
            
            const lines = doc.splitTextToSize(plainText, maxWidth);
            let yPosition = margin + 15;
            
            for (const line of lines) {
                if (yPosition > doc.internal.pageSize.getHeight() - margin) {
                    doc.addPage();
                    yPosition = margin;
                }
                doc.text(line, margin, yPosition);
                yPosition += 7;
            }
            
            // Generate filename from title - replace spaces and special chars with dashes
            const filename = title.toLowerCase()
                .replace(/[^a-z0-9]+/g, '-')
                .replace(/^-+|-+$/g, '');
            doc.save(`${filename}.pdf`);
        } catch (err) {
            console.error('Failed to generate PDF:', err);
        }
    }
    
    /**
     * Scroll to heading when clicking TOC link
     */
    function scrollToHeading(id: string) {
        const element = document.getElementById(id);
        if (element) {
            element.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
</script>

<article class="docs-article">
    <!-- Toolbar -->
    <div class="docs-toolbar">
        <button class="toolbar-btn" onclick={copyToClipboard} title="Copy markdown">
            {#if copied}
                <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 111.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z"/>
                </svg>
                <span>Copied!</span>
            {:else}
                <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 010 1.5h-1.5a.25.25 0 00-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 00.25-.25v-1.5a.75.75 0 011.5 0v1.5A1.75 1.75 0 019.25 16h-7.5A1.75 1.75 0 010 14.25v-7.5z"/>
                    <path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0114.25 11h-7.5A1.75 1.75 0 015 9.25v-7.5zm1.75-.25a.25.25 0 00-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 00.25-.25v-7.5a.25.25 0 00-.25-.25h-7.5z"/>
                </svg>
                <span>Copy</span>
            {/if}
        </button>
        
        <button class="toolbar-btn" onclick={downloadPdf} title="Download as PDF">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                <path d="M2.75 14A1.75 1.75 0 011 12.25v-2.5a.75.75 0 011.5 0v2.5c0 .138.112.25.25.25h10.5a.25.25 0 00.25-.25v-2.5a.75.75 0 011.5 0v2.5A1.75 1.75 0 0113.25 14H2.75z"/>
                <path d="M7.25 7.689V2a.75.75 0 011.5 0v5.689l1.97-1.969a.749.749 0 111.06 1.06l-3.25 3.25a.749.749 0 01-1.06 0L4.22 6.78a.749.749 0 111.06-1.06l1.97 1.969z"/>
            </svg>
            <span>PDF</span>
        </button>
    </div>
    
    <!-- Table of Contents (if there are headings) -->
    {#if tocItems.length > 2}
        <nav class="docs-toc">
            <h4>On this page</h4>
            <ul>
                {#each tocItems as item}
                    <li class:nested={item.level === 3}>
                        <button onclick={() => scrollToHeading(item.id)}>
                            {item.text}
                        </button>
                    </li>
                {/each}
            </ul>
        </nav>
    {/if}
    
    <!-- Main content -->
    <!-- Content is pre-processed at build time from trusted markdown sources -->
    <div class="docs-content-body" bind:this={contentElement}>
        <h1>{title}</h1>
        <!-- eslint-disable-next-line svelte/no-at-html-tags -- Content is sanitized at build time from trusted markdown sources -->
        {@html content}
    </div>
</article>

<style>
    .docs-article {
        position: relative;
    }
    
    .docs-toolbar {
        display: flex;
        gap: 0.5rem;
        margin-bottom: 1.5rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid var(--color-grey-200, #e5e5e5);
    }
    
    .toolbar-btn {
        display: inline-flex;
        align-items: center;
        gap: 0.375rem;
        padding: 0.5rem 0.75rem;
        background-color: var(--color-grey-50, #ffffff);
        border: 1px solid var(--color-grey-200, #e5e5e5);
        border-radius: 0.375rem;
        color: var(--color-grey-700, #374151);
        font-size: 0.875rem;
        cursor: pointer;
        text-decoration: none;
        transition: all 0.15s ease;
    }
    
    .toolbar-btn:hover {
        background-color: var(--color-grey-100, #f3f4f6);
        border-color: var(--color-grey-300, #d1d5db);
    }
    
    .docs-toc {
        position: sticky;
        top: 5rem;
        float: right;
        width: 200px;
        margin-left: 2rem;
        margin-bottom: 1rem;
        padding: 1rem;
        background-color: var(--color-grey-50, #ffffff);
        border: 1px solid var(--color-grey-200, #e5e5e5);
        border-radius: 0.5rem;
        font-size: 0.8125rem;
    }
    
    .docs-toc h4 {
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--color-grey-500, #6b7280);
        margin-bottom: 0.75rem;
    }
    
    .docs-toc ul {
        list-style: none;
        padding: 0;
        margin: 0;
    }
    
    .docs-toc li {
        margin-bottom: 0.375rem;
    }
    
    .docs-toc li.nested {
        padding-left: 0.75rem;
    }
    
    .docs-toc button {
        display: block;
        width: 100%;
        text-align: left;
        padding: 0.25rem 0;
        background: none;
        border: none;
        color: var(--color-grey-600, #4b5563);
        cursor: pointer;
        transition: color 0.15s ease;
    }
    
    .docs-toc button:hover {
        color: var(--color-primary, #3b82f6);
    }
    
    .docs-content-body {
        /* Markdown content styles */
    }
    
    .docs-content-body h1 {
        font-size: 2rem;
        font-weight: 700;
        color: var(--color-grey-900, #111827);
        margin-bottom: 1.5rem;
        line-height: 1.2;
    }
    
    .docs-content-body :global(h2) {
        font-size: 1.5rem;
        font-weight: 600;
        color: var(--color-grey-900, #111827);
        margin-top: 2rem;
        margin-bottom: 1rem;
        padding-top: 1rem;
        border-top: 1px solid var(--color-grey-200, #e5e5e5);
    }
    
    .docs-content-body :global(h3) {
        font-size: 1.25rem;
        font-weight: 600;
        color: var(--color-grey-800, #1f2937);
        margin-top: 1.5rem;
        margin-bottom: 0.75rem;
    }
    
    .docs-content-body :global(h4) {
        font-size: 1rem;
        font-weight: 600;
        color: var(--color-grey-800, #1f2937);
        margin-top: 1.25rem;
        margin-bottom: 0.5rem;
    }
    
    .docs-content-body :global(p) {
        margin-bottom: 1rem;
        line-height: 1.7;
        color: var(--color-grey-700, #374151);
    }
    
    .docs-content-body :global(ul),
    .docs-content-body :global(ol) {
        margin-bottom: 1rem;
        padding-left: 1.5rem;
    }
    
    .docs-content-body :global(li) {
        margin-bottom: 0.5rem;
        line-height: 1.6;
        color: var(--color-grey-700, #374151);
    }
    
    .docs-content-body :global(a) {
        color: var(--color-primary, #3b82f6);
        text-decoration: none;
    }
    
    .docs-content-body :global(a:hover) {
        text-decoration: underline;
    }
    
    .docs-content-body :global(code) {
        font-family: 'SF Mono', 'Fira Code', monospace;
        font-size: 0.875em;
        padding: 0.2em 0.4em;
        background-color: var(--color-grey-100, #f3f4f6);
        border-radius: 0.25rem;
    }
    
    .docs-content-body :global(pre) {
        margin-bottom: 1rem;
        padding: 1rem;
        background-color: var(--color-grey-900, #111827);
        border-radius: 0.5rem;
        overflow-x: auto;
    }
    
    .docs-content-body :global(pre code) {
        background: none;
        padding: 0;
        font-size: 0.875rem;
        color: var(--color-grey-100, #f3f4f6);
    }
    
    .docs-content-body :global(blockquote) {
        margin: 1rem 0;
        padding: 0.75rem 1rem;
        border-left: 4px solid var(--color-primary, #3b82f6);
        background-color: var(--color-grey-50, #f9fafb);
        color: var(--color-grey-700, #374151);
    }
    
    .docs-content-body :global(blockquote p) {
        margin-bottom: 0;
    }
    
    .docs-content-body :global(img) {
        max-width: 100%;
        height: auto;
        border-radius: 0.5rem;
        margin: 1rem 0;
    }
    
    .docs-content-body :global(table) {
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 1rem;
    }
    
    .docs-content-body :global(th),
    .docs-content-body :global(td) {
        padding: 0.75rem;
        text-align: left;
        border-bottom: 1px solid var(--color-grey-200, #e5e5e5);
    }
    
    .docs-content-body :global(th) {
        font-weight: 600;
        background-color: var(--color-grey-50, #f9fafb);
    }
    
    .docs-content-body :global(hr) {
        margin: 2rem 0;
        border: none;
        border-top: 1px solid var(--color-grey-200, #e5e5e5);
    }
    
    @media (max-width: 1024px) {
        .docs-toc {
            display: none;
        }
    }
</style>
