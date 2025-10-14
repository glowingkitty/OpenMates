<script lang="ts">
    /**
     * Documentation Sidebar Component
     * 
     * Displays hierarchical navigation for documentation using
     * the same design pattern as the web app's chat sidebar.
     * 
     * Features:
     * - Collapsible folders
     * - Active page highlighting
     * - Recursive folder rendering
     */
    
    import { page } from '$app/stores';
    
    // Props
    let { 
        structure,
        currentSlug = '',
        currentDoc = null
    }: {
        structure: any;
        currentSlug: string;
        currentDoc?: any;
    } = $props();
    
    // Track open/closed state for folders
    let openFolders = $state(new Set<string>());
    
    /**
     * Toggle folder open/closed state
     */
    function toggleFolder(folderPath: string) {
        if (openFolders.has(folderPath)) {
            openFolders.delete(folderPath);
        } else {
            openFolders.add(folderPath);
        }
    }
    
    /**
     * Check if folder is open
     */
    function isFolderOpen(folderPath: string): boolean {
        return openFolders.has(folderPath);
    }
    
    /**
     * Get the current document's structure for sidebar
     */
    function getCurrentDocStructure() {
        if (currentDoc && currentDoc.content) {
            // Extract headings from the current document
            const headings = extractHeadings(currentDoc.content);
            return headings;
        }
        return [];
    }
    
    /**
     * Extract headings from markdown content
     */
    function extractHeadings(content: string): Array<{level: number, text: string, id: string}> {
        const headings: Array<{level: number, text: string, id: string}> = [];
        const lines = content.split('\n');
        
        for (const line of lines) {
            const match = line.match(/^(#{1,6})\s+(.+)$/);
            if (match) {
                const level = match[1].length;
                const text = match[2].trim();
                const id = text.toLowerCase().replace(/[^a-z0-9]+/g, '-');
                headings.push({ level, text, id });
            }
        }
        
        return headings;
    }
</script>

<div class="docs-sidebar">
    <div class="sidebar-header">
        <h2>📚 Documentation</h2>
    </div>
    
    <nav class="sidebar-nav">
        {#if currentDoc && currentDoc.content}
            <!-- Show current document structure -->
            <div class="current-doc-section">
                <h3>📄 {currentDoc.title}</h3>
                <div class="doc-outline">
                    {#each getCurrentDocStructure() as heading}
                        <a 
                            href="#{heading.id}" 
                            class="outline-item"
                            style="padding-left: {15 + (heading.level - 1) * 15}px"
                        >
                            {heading.text}
                        </a>
                    {/each}
                </div>
            </div>
        {:else}
            <!-- Show general documentation structure -->
            {#each structure.folders as folder}
            <div class="folder-item">
                <button 
                    class="folder-toggle"
                    onclick={() => toggleFolder(folder.path)}
                    style="padding-left: 15px"
                >
                    <span class="folder-icon">
                        {isFolderOpen(folder.path) ? '📂' : '📁'}
                    </span>
                    <span class="folder-name">{folder.name}</span>
                </button>
                
                {#if isFolderOpen(folder.path)}
                    <!-- Files in this folder -->
                    {#each folder.files as file}
                        <a 
                            href="/docs/{file.slug}"
                            class="file-link"
                            class:active={currentSlug === file.slug}
                            style="padding-left: {(folderState.level + 1) * 15 + 15}px"
                        >
                            <span class="file-icon">📄</span>
                            <span class="file-title">{file.title}</span>
                        </a>
                    {/each}
                    
                    <!-- Subfolders (recursive) -->
                    {#each folder.folders as subfolder}
                        <div class="folder-item">
                            <button 
                                class="folder-toggle"
                                onclick={() => toggleFolder(subfolder.path)}
                                style="padding-left: 30px"
                            >
                                <span class="folder-icon">
                                    {isFolderOpen(subfolder.path) ? '📂' : '📁'}
                                </span>
                                <span class="folder-name">{subfolder.name}</span>
                            </button>
                            
                            {#if isFolderOpen(subfolder.path)}
                                {#each subfolder.files as file}
                                    <a 
                                        href="/docs/{file.slug}"
                                        class="file-link"
                                        class:active={currentSlug === file.slug}
                                        style="padding-left: 45px"
                                    >
                                        <span class="file-icon">📄</span>
                                        <span class="file-title">{file.title}</span>
                                    </a>
                                {/each}
                            {/if}
                        </div>
                    {/each}
                {/if}
            </div>
        {/each}
        
        <!-- Root level files -->
        {#each structure.files as file}
            <a 
                href="/docs/{file.slug}"
                class="file-link"
                class:active={currentSlug === file.slug}
                style="padding-left: 15px"
            >
                <span class="file-icon">📄</span>
                <span class="file-title">{file.title}</span>
            </a>
            {/each}
        {/if}
    </nav>
</div>

<style>
    .docs-sidebar {
        height: 100%;
        display: flex;
        flex-direction: column;
    }
    
    .sidebar-header {
        padding: 20px 15px;
        border-bottom: 1px solid var(--color-grey-30);
    }
    
    .sidebar-header h2 {
        margin: 0;
        font-size: 18px;
        font-weight: 600;
        color: var(--color-grey-90);
    }
    
    .sidebar-nav {
        flex: 1;
        overflow-y: auto;
        padding: 10px 0;
    }
    
    .folder-item {
        margin-bottom: 5px;
    }
    
    .folder-toggle {
        width: 100%;
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 15px;
        background: transparent;
        border: none;
        cursor: pointer;
        text-align: left;
        font-size: 14px;
        color: var(--color-grey-80);
        transition: background 0.2s ease;
    }
    
    .folder-toggle:hover {
        background: var(--color-grey-30);
    }
    
    .folder-icon {
        font-size: 16px;
        flex-shrink: 0;
    }
    
    .folder-name {
        font-weight: 500;
        text-transform: capitalize;
    }
    
    .file-link {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 15px;
        text-decoration: none;
        color: var(--color-grey-70);
        font-size: 14px;
        transition: background 0.2s ease, color 0.2s ease;
    }
    
    .file-link:hover {
        background: var(--color-grey-30);
        color: var(--color-grey-90);
    }
    
    .file-link.active {
        background: var(--color-primary-light);
        color: var(--color-primary-dark);
        font-weight: 500;
    }
    
    .file-icon {
        font-size: 14px;
        flex-shrink: 0;
    }
    
    .file-title {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    
    /* Current document outline styles */
    .current-doc-section {
        margin-bottom: 20px;
        padding: 0 15px 15px 15px;
        border-bottom: 1px solid var(--color-grey-30);
    }
    
    .current-doc-section h3 {
        font-size: 16px;
        font-weight: 600;
        margin: 0 0 10px 0;
        padding: 10px 0;
        color: var(--color-grey-90);
    }
    
    .doc-outline {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    
    .outline-item {
        display: block;
        padding: 6px 12px;
        text-decoration: none;
        color: var(--color-grey-70);
        font-size: 13px;
        border-radius: 4px;
        transition: all 0.2s ease;
    }
    
    .outline-item:hover {
        background: var(--color-grey-30);
        color: var(--color-grey-90);
    }
</style>

