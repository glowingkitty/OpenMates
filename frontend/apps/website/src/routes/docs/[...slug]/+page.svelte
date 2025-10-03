<script lang="ts">
    /**
     * Dynamic Documentation Page
     * 
     * Renders documentation from markdown files with:
     * - Sidebar navigation (reusing web app sidebar style)
     * - Copy button (copy markdown to clipboard)
     * - Download PDF button
     * - Offline support (PWA)
     */
    
    import { Header, MetaTags, getMetaTags } from '@repo/ui';
    import { page } from '$app/stores';
    import DocsSidebar from '$lib/components/DocsSidebar.svelte';
    import DocsContent from '$lib/components/DocsContent.svelte';
    import type { PageData } from './$types';
    
    // Props from +page.ts loader
    let { data }: { data: PageData } = $props();
    
    // Debug logging
    console.log('🔍 [...slug] page data:', data);
    
    // State for sidebar
    let sidebarOpen = $state(true);
    
    // Meta tags
    const meta = getMetaTags('docs');
    
    /**
     * Toggle sidebar visibility
     */
    function toggleSidebar() {
        sidebarOpen = !sidebarOpen;
    }
    
    /**
     * Copy current page or folder as markdown to clipboard
     */
    async function copyToClipboard() {
        let markdown = '';
        
        if (data.type === 'document') {
            // Copy single document - use original markdown if available
            markdown = data.doc.originalMarkdown || data.doc.content;
        } else if (data.type === 'folder' && data.allFiles) {
            // Copy all files in folder - use original markdown if available
            markdown = data.allFiles
                .map((file: any) => file.originalMarkdown || file.content)
                .join('\n\n---\n\n');
        }
        
        try {
            await navigator.clipboard.writeText(markdown);
            console.log('✅ Copied to clipboard');
            // TODO: Show toast notification
        } catch (err) {
            console.error('❌ Failed to copy:', err);
        }
    }
    
    /**
     * Download current page or folder as PDF
     * Using client-side generation for offline support
     */
    async function downloadPDF() {
        const { generatePDF, generateFolderPDF } = await import('$lib/utils/pdfGenerator');
        
        try {
            if (data.type === 'document') {
                // Download single document
                await generatePDF(data.doc.content, data.doc.title);
                console.log('✅ PDF downloaded');
            } else if (data.type === 'folder' && data.allFiles) {
                // Download all files in folder
                await generateFolderPDF(data.allFiles, data.folder.name);
                console.log('✅ Folder PDF downloaded');
            }
        } catch (err) {
            console.error('❌ Failed to generate PDF:', err);
        }
    }
</script>

<MetaTags {...meta} />
<Header context="website" />

<div class="docs-layout">
        <!-- Sidebar (reusing web app sidebar pattern) -->
        <div class="sidebar" class:closed={!sidebarOpen}>
            {#if sidebarOpen}
                <DocsSidebar 
                    structure={data.structure} 
                    currentSlug={$page.params.slug || ''}
                    currentDoc={data.type === 'document' ? data.doc : null}
                />
            {/if}
        </div>
    
    <!-- Main content area -->
    <div class="main-content" class:sidebar-closed={!sidebarOpen}>
        <!-- Toolbar -->
        <div class="toolbar">
            <button 
                class="btn-icon" 
                onclick={toggleSidebar}
                aria-label="Toggle sidebar"
            >
                {sidebarOpen ? '◀' : '▶'}
            </button>
            
            <div class="toolbar-actions">
                <button class="btn-action" onclick={copyToClipboard}>
                    📋 Copy
                </button>
                <button class="btn-action" onclick={downloadPDF}>
                    📥 Download PDF
                </button>
            </div>
        </div>
        
        <!-- Document content -->
        <div class="content-wrapper">
            <DocsContent {data} />
        </div>
    </div>
</div>

<style>
    /* Reuse web app sidebar styling patterns */
    :root {
        --sidebar-width: 325px;
        --sidebar-margin: 10px;
    }
    
    .docs-layout {
        display: flex;
        min-height: 100vh;
        padding-top: 90px; /* Account for Header height */
    }
    
    .sidebar {
        position: fixed;
        left: 0;
        top: 90px;
        bottom: 0;
        width: var(--sidebar-width);
        background-color: var(--color-grey-20);
        z-index: 10;
        overflow-y: auto;
        box-shadow: inset -6px 0 12px -4px rgba(0, 0, 0, 0.25);
        scrollbar-width: thin;
        scrollbar-color: var(--color-grey-40) transparent;
        transition: transform 0.3s ease, opacity 0.3s ease;
        opacity: 1;
    }
    
    .sidebar.closed {
        transform: translateX(-100%);
        opacity: 0;
    }
    
    .sidebar::-webkit-scrollbar {
        width: 8px;
    }
    
    .sidebar::-webkit-scrollbar-track {
        background: transparent;
    }
    
    .sidebar::-webkit-scrollbar-thumb {
        background-color: var(--color-grey-40);
        border-radius: 4px;
        border: 2px solid transparent;
    }
    
    .sidebar::-webkit-scrollbar-thumb:hover {
        background-color: var(--color-grey-50);
    }
    
    .main-content {
        flex: 1;
        margin-left: calc(var(--sidebar-width) + var(--sidebar-margin));
        padding: 20px;
        transition: margin-left 0.3s ease;
        width: calc(100% - var(--sidebar-width) - var(--sidebar-margin));
        max-width: calc(100% - var(--sidebar-width) - var(--sidebar-margin));
        box-sizing: border-box;
    }
    
    .main-content.sidebar-closed {
        margin-left: var(--sidebar-margin);
        width: calc(100% - var(--sidebar-margin));
        max-width: calc(100% - var(--sidebar-margin));
    }
    
    .toolbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 30px;
        padding-bottom: 15px;
        border-bottom: 1px solid var(--color-grey-30);
    }
    
    .btn-icon {
        background: var(--color-grey-20);
        border: 1px solid var(--color-grey-30);
        border-radius: 6px;
        padding: 8px 12px;
        cursor: pointer;
        font-size: 16px;
        transition: background 0.2s ease;
    }
    
    .btn-icon:hover {
        background: var(--color-grey-30);
    }
    
    .toolbar-actions {
        display: flex;
        gap: 10px;
    }
    
    .btn-action {
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        cursor: pointer;
        font-size: 14px;
        transition: background 0.2s ease;
    }
    
    .btn-action:hover {
        background: var(--color-primary-dark);
    }
    
    .content-wrapper {
        background: var(--color-grey-20);
        padding: 40px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        max-width: 100%;
        overflow-x: auto;
        word-wrap: break-word;
        overflow-wrap: break-word;
    }
    
    /* Mobile responsive */
    @media (max-width: 768px) {
        .sidebar {
            width: 100%;
            z-index: 100;
        }
        
        .main-content {
            margin-left: 0;
        }
        
        .main-content.sidebar-closed {
            margin-left: 0;
        }
    }
</style>

