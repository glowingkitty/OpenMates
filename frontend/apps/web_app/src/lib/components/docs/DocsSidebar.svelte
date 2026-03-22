<script lang="ts">
    /**
     * DocsSidebar Component
     * 
     * Tree-based navigation sidebar for documentation.
     * Features:
     * - Collapsible folder structure
     * - Active page highlighting
     * - Keyboard navigation support
     * - Mobile-responsive
     */
    import { page } from '$app/state';
    import { untrack } from 'svelte';
    import docsData from '$lib/generated/docs-data.json';
    import type { DocFolder } from '$lib/types/docs';
    
    // Props
    let { onNavigate = () => {} } = $props<{ onNavigate?: () => void }>();
    
    // Get the documentation structure
    const { structure } = docsData;
    
    // Track expanded folders
    let expandedFolders = $state<Set<string>>(new Set());
    
    // Current path for highlighting active item
    let currentPath = $derived(page.url.pathname);
    
    // Track last processed path to avoid redundant updates
    let lastProcessedPath = '';
    
    // Auto-expand folder containing current page
    // Use untrack when modifying expandedFolders to prevent infinite loop
    $effect(() => {
        const path = currentPath.replace('/docs/', '').replace('/docs', '');
        
        // Only process if path changed (avoid redundant work)
        if (path && path !== lastProcessedPath) {
            lastProcessedPath = path;
            
            const parts = path.split('/');
            // Expand all parent folders
            let parentPath = '';
            const foldersToExpand: string[] = [];
            
            for (const part of parts.slice(0, -1)) {
                parentPath = parentPath ? `${parentPath}/${part}` : part;
                foldersToExpand.push(parentPath);
            }
            
            // Use untrack to prevent this mutation from triggering the effect again
            untrack(() => {
                for (const folder of foldersToExpand) {
                    expandedFolders.add(folder);
                }
                expandedFolders = new Set(expandedFolders);
            });
        }
    });
    
    /**
     * Toggle folder expansion
     */
    function toggleFolder(path: string) {
        if (expandedFolders.has(path)) {
            expandedFolders.delete(path);
        } else {
            expandedFolders.add(path);
        }
        expandedFolders = new Set(expandedFolders);
    }
    
    /**
     * Check if a path is currently active
     */
    function isActive(slug: string): boolean {
        const docPath = `/docs/${slug}`;
        return currentPath === docPath || currentPath === `${docPath}/`;
    }
    
    /**
     * Check if a folder contains the active page
     */
    function folderContainsActive(folder: DocFolder): boolean {
        // Check files
        for (const file of folder.files) {
            if (isActive(file.slug)) {
                return true;
            }
        }
        // Check subfolders
        for (const subfolder of folder.folders) {
            if (folderContainsActive(subfolder)) {
                return true;
            }
        }
        return false;
    }
</script>

<nav class="docs-sidebar-nav" aria-label="Documentation navigation">
    <div class="nav-content">
        <!-- API Reference - special link at top -->
        <a 
            href="/docs/api" 
            class="nav-link api-link" 
            class:active={currentPath === '/docs/api' || currentPath === '/docs/api/'}
            onclick={onNavigate}
        >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" class="api-icon">
                <path d="M4.75 1A1.75 1.75 0 003 2.75v10.5c0 .966.784 1.75 1.75 1.75h6.5A1.75 1.75 0 0013 13.25v-10.5A1.75 1.75 0 0011.25 1h-6.5zM4.5 2.75a.25.25 0 01.25-.25h6.5a.25.25 0 01.25.25v10.5a.25.25 0 01-.25.25h-6.5a.25.25 0 01-.25-.25V2.75zM6 5a.75.75 0 000 1.5h4A.75.75 0 0010 5H6zm0 3a.75.75 0 000 1.5h4A.75.75 0 0010 8H6zm0 3a.75.75 0 000 1.5h4a.75.75 0 000-1.5H6z"/>
            </svg>
            API Reference
        </a>
        
        <div class="nav-separator"></div>
        
        <!-- Top level files (if any) -->
        {#each structure.files as file}
            <a 
                href="/docs/{file.slug}" 
                class="nav-link" 
                class:active={isActive(file.slug)}
                onclick={onNavigate}
            >
                {file.title}
            </a>
        {/each}
        
        <!-- Folders -->
        {#each structure.folders as folder}
            {@const isExpanded = expandedFolders.has(folder.path)}
            {@const containsActive = folderContainsActive(folder)}
            
            <div class="nav-folder" class:expanded={isExpanded} class:contains-active={containsActive}>
                <button 
                    class="folder-toggle"
                    onclick={() => toggleFolder(folder.path)}
                    aria-expanded={isExpanded}
                >
                    <svg class="chevron" width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" fill="none"/>
                    </svg>
                    <span class="folder-title">{folder.title}</span>
                </button>
                
                {#if isExpanded}
                    <div class="folder-content">
                        <!-- Files in folder -->
                        {#each folder.files as file}
                            <a 
                                href="/docs/{file.slug}" 
                                class="nav-link nested" 
                                class:active={isActive(file.slug)}
                                onclick={onNavigate}
                            >
                                {file.title}
                            </a>
                        {/each}
                        
                        <!-- Subfolders -->
                        {#each folder.folders as subfolder}
                            {@const subIsExpanded = expandedFolders.has(subfolder.path)}
                            {@const subContainsActive = folderContainsActive(subfolder)}
                            
                            <div class="nav-folder nested" class:expanded={subIsExpanded} class:contains-active={subContainsActive}>
                                <button 
                                    class="folder-toggle"
                                    onclick={() => toggleFolder(subfolder.path)}
                                    aria-expanded={subIsExpanded}
                                >
                                    <svg class="chevron" width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                                        <path d="M6 4l4 4-4 4" stroke="currentColor" stroke-width="1.5" fill="none"/>
                                    </svg>
                                    <span class="folder-title">{subfolder.title}</span>
                                </button>
                                
                                {#if subIsExpanded}
                                    <div class="folder-content">
                                        {#each subfolder.files as file}
                                            <a 
                                                href="/docs/{file.slug}" 
                                                class="nav-link nested-2" 
                                                class:active={isActive(file.slug)}
                                                onclick={onNavigate}
                                            >
                                                {file.title}
                                            </a>
                                        {/each}
                                    </div>
                                {/if}
                            </div>
                        {/each}
                    </div>
                {/if}
            </div>
        {/each}
    </div>
</nav>

<style>
    .docs-sidebar-nav {
        height: 100%;
        overflow-y: auto;
    }
    
    .nav-content {
        padding: 1rem;
    }
    
    .nav-link {
        display: block;
        padding: 0.5rem 0.75rem;
        color: var(--color-grey-700, #374151);
        text-decoration: none;
        font-size: 0.875rem;
        border-radius: 0.375rem;
        transition: all 0.15s ease;
    }
    
    .nav-link:hover {
        background-color: var(--color-grey-100, #f3f4f6);
        color: var(--color-grey-900, #111827);
    }
    
    .nav-link.active {
        background-color: var(--color-primary-50, #eff6ff);
        color: var(--color-primary, #3b82f6);
        font-weight: 500;
    }
    
    .nav-link.nested {
        padding-left: 1.5rem;
    }
    
    .nav-link.nested-2 {
        padding-left: 2.5rem;
    }
    
    .nav-folder {
        margin-bottom: 0.25rem;
    }
    
    .nav-folder.nested {
        margin-left: 0.75rem;
    }
    
    .folder-toggle {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        width: 100%;
        padding: 0.5rem 0.75rem;
        background: none;
        border: none;
        cursor: pointer;
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--color-grey-800, #1f2937);
        text-align: left;
        border-radius: 0.375rem;
        transition: all 0.15s ease;
    }
    
    .folder-toggle:hover {
        background-color: var(--color-grey-100, #f3f4f6);
    }
    
    .nav-folder.contains-active > .folder-toggle {
        color: var(--color-primary, #3b82f6);
    }
    
    .chevron {
        transition: transform 0.2s ease;
        flex-shrink: 0;
    }
    
    .nav-folder.expanded > .folder-toggle .chevron {
        transform: rotate(90deg);
    }
    
    .folder-title {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    
    .folder-content {
        margin-top: 0.25rem;
    }
    
    .nav-link.api-link {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-weight: 500;
        color: var(--color-grey-800, #1f2937);
    }
    
    .nav-link.api-link:hover {
        background-color: var(--color-primary-50, #eff6ff);
        color: var(--color-primary, #3b82f6);
    }
    
    .nav-link.api-link.active {
        background-color: var(--color-primary-100, #dbeafe);
        color: var(--color-primary-700, #1d4ed8);
    }
    
    .api-icon {
        flex-shrink: 0;
    }
    
    .nav-separator {
        height: 1px;
        background-color: var(--color-grey-200, #e5e5e5);
        margin: 0.75rem 0;
    }
</style>
