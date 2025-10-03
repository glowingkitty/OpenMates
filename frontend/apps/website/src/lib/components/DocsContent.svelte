<script lang="ts">
    /**
     * Documentation Content Component
     * 
     * Renders the main content area for documentation pages.
     * Handles different content types (document, folder index, root index).
     */
    
    // Props
    let { data }: { data: any } = $props();
    
    /**
     * Get content HTML based on data type
     * Content is now pre-rendered as HTML at build time
     */
    let contentHtml = $derived(() => {
        if (data.type === 'document' && data.doc?.content) {
            return data.doc.content; // Already HTML from build process
        }
        return '';
    });
</script>

{#if data.type === 'document'}
    <!-- Single document view -->
    <article class="doc-content">
        <h1 class="doc-title">{data.doc.title}</h1>
        <div class="markdown-body">
            {@html contentHtml()}
        </div>
    </article>
{:else if data.type === 'folder'}
    <!-- Folder index view -->
    <div class="folder-index">
        <h1>📁 {data.folder.name}</h1>
        <p>This folder contains {data.allFiles.length} document(s).</p>
        
        <div class="file-list">
            {#each data.allFiles as file}
                <a href="/docs/{file.slug}" class="file-card">
                    <h3>📄 {file.title}</h3>
                    <p class="file-path">{file.path}</p>
                </a>
            {/each}
        </div>
    </div>
{:else if data.type === 'index'}
    <!-- Root documentation index -->
    <div class="docs-index">
        <h1>📚 Documentation</h1>
        <p>Welcome to the OpenMates documentation. Choose a section from the sidebar to get started.</p>
        
        <div class="sections-grid">
            <!-- Show individual files first -->
            {#each data.structure.files as file}
                <a href="/docs/{file.slug}" class="section-card file-card">
                    <h2>📄 {file.title}</h2>
                    <p>Document</p>
                </a>
            {/each}
            
            <!-- Show folders -->
            {#each data.structure.folders as folder}
                <a href="/docs/{folder.path}" class="section-card folder-card">
                    <h2>📂 {folder.name}</h2>
                    <p>{folder.files.length} document(s)</p>
                </a>
            {/each}
        </div>
    </div>
{/if}

<style>
    /* Document content styles */
    .doc-content {
        max-width: 100%;
    }
    
    .doc-title {
        font-size: 32px;
        font-weight: 700;
        margin-bottom: 30px;
        color: var(--color-grey-90);
        border-bottom: 2px solid var(--color-grey-30);
        padding-bottom: 15px;
    }
    
    /* Markdown body styles */
    .markdown-body {
        line-height: 1.7;
        color: var(--color-grey-80);
    }
    
    .markdown-body :global(h1),
    .markdown-body :global(h2),
    .markdown-body :global(h3),
    .markdown-body :global(h4),
    .markdown-body :global(h5),
    .markdown-body :global(h6) {
        margin-top: 24px;
        margin-bottom: 16px;
        font-weight: 600;
        color: var(--color-grey-90);
    }
    
    .markdown-body :global(h1) { font-size: 28px; }
    .markdown-body :global(h2) { font-size: 24px; }
    .markdown-body :global(h3) { font-size: 20px; }
    .markdown-body :global(h4) { font-size: 18px; }
    
    .markdown-body :global(p) {
        margin-bottom: 16px;
    }
    
    .markdown-body :global(a) {
        color: var(--color-primary);
        text-decoration: underline;
    }
    
    .markdown-body :global(a:hover) {
        color: var(--color-primary-dark);
    }
    
    .markdown-body :global(code) {
        background: var(--color-grey-20);
        padding: 2px 6px;
        border-radius: 3px;
        font-family: 'Courier New', monospace;
        font-size: 0.9em;
    }
    
    .markdown-body :global(pre) {
        background: var(--color-grey-20);
        padding: 16px;
        border-radius: 6px;
        overflow-x: auto;
        margin-bottom: 16px;
    }
    
    .markdown-body :global(pre code) {
        background: transparent;
        padding: 0;
    }
    
    .markdown-body :global(ul),
    .markdown-body :global(ol) {
        margin-bottom: 16px;
        padding-left: 30px;
    }
    
    .markdown-body :global(li) {
        margin-bottom: 8px;
    }
    
    .markdown-body :global(blockquote) {
        border-left: 4px solid var(--color-primary);
        padding-left: 16px;
        margin: 16px 0;
        color: var(--color-grey-70);
        font-style: italic;
    }
    
    .markdown-body :global(table) {
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 16px;
    }
    
    .markdown-body :global(th),
    .markdown-body :global(td) {
        border: 1px solid var(--color-grey-30);
        padding: 8px 12px;
        text-align: left;
    }
    
    .markdown-body :global(th) {
        background: var(--color-grey-20);
        font-weight: 600;
    }
    
    /* Folder index styles */
    .folder-index h1 {
        font-size: 32px;
        margin-bottom: 20px;
    }
    
    .file-list {
        display: grid;
        gap: 15px;
        margin-top: 30px;
    }
    
    .file-card {
        padding: 20px;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        text-decoration: none;
        color: inherit;
        transition: all 0.2s ease;
    }
    
    .file-card:hover {
        border-color: var(--color-primary);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }
    
    .file-card h3 {
        margin: 0 0 8px 0;
        font-size: 18px;
        color: var(--color-grey-90);
    }
    
    .file-path {
        margin: 0;
        font-size: 13px;
        color: var(--color-grey-60);
        font-family: 'Courier New', monospace;
    }
    
    /* Root index styles */
    .docs-index h1 {
        font-size: 36px;
        margin-bottom: 20px;
    }
    
    .sections-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
        gap: 20px;
        margin-top: 30px;
    }
    
    .section-card {
        padding: 30px;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        text-align: center;
        text-decoration: none;
        color: inherit;
        transition: all 0.2s ease;
        display: block;
    }
    
    .section-card:hover {
        border-color: var(--color-primary);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        transform: translateY(-2px);
    }
    
    .section-card h2 {
        margin: 0 0 10px 0;
        font-size: 20px;
        color: var(--color-grey-90);
        text-transform: capitalize;
    }
    
    .section-card p {
        margin: 0;
        color: var(--color-grey-60);
        font-size: 14px;
    }
</style>

