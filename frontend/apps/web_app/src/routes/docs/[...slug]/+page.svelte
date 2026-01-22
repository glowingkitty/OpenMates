<script lang="ts">
    /**
     * Dynamic Docs Page
     * 
     * Renders individual documentation pages based on the URL slug.
     * Handles both folder index pages and individual document pages.
     * 
     * URL patterns:
     * - /docs/architecture -> Shows architecture folder index or README
     * - /docs/architecture/chats -> Shows specific document
     */
    import { page } from '$app/state';
    import DocsContent from '$lib/components/docs/DocsContent.svelte';
    import docsData from '$lib/generated/docs-data.json';
    import type { DocFile, DocFolder, DocStructure } from '$lib/types/docs';
    
    // Get the current slug from the URL
    let currentSlug = $derived(page.params.slug || '');
    
    // Find the document or folder matching the slug
    let pageData = $derived(findPageData(currentSlug));
    
    /**
     * Find document data matching the given slug
     * Searches through the nested structure
     */
    function findPageData(slug: string): { type: 'file' | 'folder', data: DocFile | DocFolder } | null {
        const parts = slug.split('/').filter(Boolean);
        
        if (parts.length === 0) {
            return null;
        }
        
        let current: DocStructure | DocFolder = docsData.structure as DocStructure;
        
        // Navigate through folders
        for (let i = 0; i < parts.length; i++) {
            const part = parts[i];
            const isLast = i === parts.length - 1;
            
            // Check if it's a file at this level
            const file = current.files.find((f: DocFile) => 
                f.slug === slug || 
                f.name.replace('.md', '') === part
            );
            
            if (file && isLast) {
                return { type: 'file', data: file };
            }
            
            // Check if it's a folder
            const folder = current.folders.find((f: DocFolder) => f.name === part);
            
            if (folder) {
                if (isLast) {
                    // Return folder with its index file if exists
                    const indexFile = folder.files.find((f: DocFile) => 
                        f.name === 'README.md' || f.name === 'index.md'
                    );
                    
                    if (indexFile) {
                        return { type: 'file', data: indexFile };
                    }
                    
                    return { type: 'folder', data: folder };
                }
                
                current = folder;
            } else {
                // Not found
                return null;
            }
        }
        
        return null;
    }
    
    // Page title
    let pageTitle = $derived(
        pageData?.type === 'file' 
            ? pageData.data.title 
            : pageData?.type === 'folder' 
                ? pageData.data.title 
                : 'Not Found'
    );
</script>

<svelte:head>
    <title>{pageTitle} | OpenMates Docs</title>
</svelte:head>

{#if pageData?.type === 'file'}
    <DocsContent 
        title={pageData.data.title}
        content={pageData.data.content}
        originalMarkdown={pageData.data.originalMarkdown}
    />
{:else if pageData?.type === 'folder'}
    <!-- Folder index page -->
    <div class="folder-index">
        <h1>{pageData.data.title}</h1>
        
        {#if pageData.data.files.length > 0}
            <section class="folder-files">
                <h2>Documents</h2>
                <ul>
                    {#each pageData.data.files as file}
                        <li>
                            <a href="/docs/{file.slug}">{file.title}</a>
                        </li>
                    {/each}
                </ul>
            </section>
        {/if}
        
        {#if pageData.data.folders.length > 0}
            <section class="folder-subfolders">
                <h2>Sections</h2>
                <ul>
                    {#each pageData.data.folders as subfolder}
                        <li>
                            <a href="/docs/{subfolder.path}">{subfolder.title}</a>
                            <span class="count">({subfolder.files.length} docs)</span>
                        </li>
                    {/each}
                </ul>
            </section>
        {/if}
    </div>
{:else}
    <!-- Not found -->
    <div class="not-found">
        <h1>Page Not Found</h1>
        <p>The documentation page you're looking for doesn't exist.</p>
        <a href="/docs">← Back to Documentation</a>
    </div>
{/if}

<style>
    .folder-index h1 {
        font-size: 2rem;
        font-weight: 700;
        color: var(--color-grey-900, #111827);
        margin-bottom: 2rem;
    }
    
    .folder-files,
    .folder-subfolders {
        margin-bottom: 2rem;
    }
    
    .folder-files h2,
    .folder-subfolders h2 {
        font-size: 1.25rem;
        font-weight: 600;
        color: var(--color-grey-800, #1f2937);
        margin-bottom: 1rem;
    }
    
    .folder-files ul,
    .folder-subfolders ul {
        list-style: none;
        padding: 0;
        margin: 0;
    }
    
    .folder-files li,
    .folder-subfolders li {
        padding: 0.75rem 0;
        border-bottom: 1px solid var(--color-grey-200, #e5e5e5);
    }
    
    .folder-files a,
    .folder-subfolders a {
        color: var(--color-primary, #3b82f6);
        text-decoration: none;
        font-weight: 500;
    }
    
    .folder-files a:hover,
    .folder-subfolders a:hover {
        text-decoration: underline;
    }
    
    .count {
        color: var(--color-grey-500, #6b7280);
        font-size: 0.875rem;
        margin-left: 0.5rem;
    }
    
    .not-found {
        text-align: center;
        padding: 4rem 1rem;
    }
    
    .not-found h1 {
        font-size: 2rem;
        font-weight: 700;
        color: var(--color-grey-900, #111827);
        margin-bottom: 1rem;
    }
    
    .not-found p {
        color: var(--color-grey-600, #4b5563);
        margin-bottom: 2rem;
    }
    
    .not-found a {
        color: var(--color-primary, #3b82f6);
        text-decoration: none;
        font-weight: 500;
    }
    
    .not-found a:hover {
        text-decoration: underline;
    }
</style>
