<script lang="ts">
    /**
     * DocsSidebar Component
     *
     * Sidebar navigation for documentation, styled to match Chats.svelte.
     * Features:
     * - Integrated search bar at top (same UX as chat search)
     * - Close button matching chat sidebar
     * - Folder groups styled like chat time groups
     * - Doc items styled like chat list items with category gradient circles
     * - Table of contents for active doc page (h2/h3 headings)
     * - Keyboard shortcut: Cmd+K for search focus
     *
     * Architecture: docs/architecture/docs-web-app.md
     * Mirrors: components/chats/Chats.svelte layout pattern
     */
    import { page } from '$app/state';
    import { untrack } from 'svelte';
    import { text } from '@repo/ui';
    import docsData from '$lib/generated/docs-data.json';
    import type { DocFolder, DocFile, DocsData } from '$lib/types/docs';
    import { getDocCategoryInfo, DOCS_FOLDER_ICON } from '$lib/utils/docsCategoryMap';

    interface Props {
        onClose: () => void;
    }

    let { onClose }: Props = $props();

    const { structure, searchIndex } = docsData as unknown as DocsData;

    // Search state
    let searchQuery = $state('');
    let searchInputRef = $state<HTMLInputElement | null>(null);

    // Track expanded folders
    let expandedFolders = $state<Set<string>>(new Set());

    let currentPath = $derived(page.url.pathname);

    // Auto-expand folder containing current page
    let lastProcessedPath = '';
    $effect(() => {
        const path = currentPath.replace('/docs/', '').replace('/docs', '');
        if (path && path !== lastProcessedPath) {
            lastProcessedPath = path;
            const parts = path.split('/');
            let parentPath = '';
            const foldersToExpand: string[] = [];
            for (const part of parts.slice(0, -1)) {
                parentPath = parentPath ? `${parentPath}/${part}` : part;
                foldersToExpand.push(parentPath);
            }
            untrack(() => {
                for (const folder of foldersToExpand) {
                    expandedFolders.add(folder);
                }
                expandedFolders = new Set(expandedFolders);
            });
        }
    });

    // Search results
    let searchResults = $derived.by(() => {
        if (!searchQuery.trim()) return [];
        const query = searchQuery.toLowerCase().trim();
        const words = query.split(/\s+/);

        return searchIndex
            .filter((entry: { title: string; content: string; slug: string }) => {
                const titleLower = entry.title.toLowerCase();
                const contentLower = entry.content.toLowerCase();
                return words.every((word: string) => titleLower.includes(word) || contentLower.includes(word));
            })
            .sort((a: { title: string }, b: { title: string }) => {
                const aTitle = a.title.toLowerCase();
                const bTitle = b.title.toLowerCase();
                const aExact = aTitle.includes(query) ? 1 : 0;
                const bExact = bTitle.includes(query) ? 1 : 0;
                return bExact - aExact;
            })
            .slice(0, 20);
    });

    let isSearchActive = $derived(searchQuery.trim().length > 0);

    // TOC headings for the active doc page
    let tocHeadings = $state<Array<{ id: string; text: string; level: number }>>([]);
    let activeDocSlug = $derived(currentPath.replace('/docs/', '').replace('/docs', ''));

    // Extract TOC headings when the page changes
    $effect(() => {
        // Trigger on path change
        const _path = currentPath;
        // Use a microtask to wait for DOM render
        if (typeof window !== 'undefined') {
            setTimeout(() => {
                const container = document.querySelector('.active-docs-container');
                if (!container) {
                    tocHeadings = [];
                    return;
                }
                const headings = container.querySelectorAll('h2, h3');
                tocHeadings = Array.from(headings)
                    .filter((h) => h.id)
                    .map((h) => ({
                        id: h.id,
                        text: h.textContent || '',
                        level: parseInt(h.tagName.charAt(1))
                    }));
            }, 200);
        }
    });

    function isActive(slug: string): boolean {
        const docPath = `/docs/${slug}`;
        return currentPath === docPath || currentPath === `${docPath}/`;
    }

    function folderContainsActive(folder: DocFolder): boolean {
        for (const file of folder.files) {
            if (isActive(file.slug)) return true;
        }
        for (const subfolder of folder.folders) {
            if (folderContainsActive(subfolder)) return true;
        }
        return false;
    }

    function toggleFolder(path: string) {
        if (expandedFolders.has(path)) {
            expandedFolders.delete(path);
        } else {
            expandedFolders.add(path);
        }
        expandedFolders = new Set(expandedFolders);
    }

    function getSnippet(content: string, maxLen = 60): string {
        const clean = content.replace(/[#*_`\[\]()]/g, '').trim();
        return clean.length > maxLen ? clean.substring(0, maxLen) + '...' : clean;
    }

    function handleKeydown(event: KeyboardEvent) {
        if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
            event.preventDefault();
            searchInputRef?.focus();
        }
        if (event.key === 'Escape' && searchQuery) {
            searchQuery = '';
            searchInputRef?.blur();
        }
    }

    function scrollToHeading(id: string) {
        const element = document.getElementById(id);
        if (element) {
            element.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
</script>

<svelte:window on:keydown={handleKeydown} />

<div class="sidebar-wrapper">
    <!-- Top bar: search + close button -->
    <div class="top-bar">
        <div class="search-container">
            <svg class="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
            </svg>
            <input
                bind:this={searchInputRef}
                bind:value={searchQuery}
                type="text"
                class="search-input"
                placeholder={$text('documentation.search.placeholder')}
            />
            {#if searchQuery}
                <button class="clear-btn" onclick={() => { searchQuery = ''; }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M18 6 6 18M6 6l12 12" />
                    </svg>
                </button>
            {:else}
                <kbd class="shortcut-badge">⌘K</kbd>
            {/if}
        </div>
        <button class="close-btn" onclick={onClose} aria-label="Close sidebar">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 6 6 18M6 6l12 12" />
            </svg>
        </button>
    </div>

    <!-- Scrollable content -->
    <div class="nav-scroll">
        {#if isSearchActive}
            <!-- Search results -->
            <div class="search-results">
                {#if searchResults.length === 0}
                    <div class="no-results">{$text('documentation.search.no_results')}</div>
                {:else}
                    {#each searchResults as result (result.slug)}
                        {@const catInfo = getDocCategoryInfo(result.slug)}
                        <a
                            href="/docs/{result.slug}"
                            class="doc-item"
                            class:active={isActive(result.slug)}
                        >
                            <div class="doc-icon mate-profile {catInfo.category}" style="width: 28px; height: 28px; margin: 0; animation: none; opacity: 1;"></div>
                            <div class="doc-content">
                                <span class="doc-title">{result.title}</span>
                                <span class="doc-preview">{getSnippet(result.content)}</span>
                            </div>
                        </a>
                    {/each}
                {/if}
            </div>
        {:else}
            <!-- TOC for active doc page -->
            {#if tocHeadings.length > 0 && activeDocSlug && activeDocSlug !== '' && !activeDocSlug.startsWith('api')}
                <div class="toc-section">
                    <h2 class="group-title">{$text('documentation.toc.title')}</h2>
                    {#each tocHeadings as heading (heading.id)}
                        <button
                            class="toc-item"
                            class:toc-h3={heading.level === 3}
                            onclick={() => scrollToHeading(heading.id)}
                        >
                            {heading.text}
                        </button>
                    {/each}
                </div>
                <div class="nav-separator"></div>
            {/if}

            <!-- API Reference special link -->
            <a
                href="/docs/api"
                class="doc-item api-item"
                class:active={currentPath === '/docs/api' || currentPath === '/docs/api/'}
            >
                <div class="doc-icon-simple">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M4.75 1A1.75 1.75 0 003 2.75v10.5c0 .966.784 1.75 1.75 1.75h6.5A1.75 1.75 0 0013 13.25v-10.5A1.75 1.75 0 0011.25 1h-6.5zM4.5 2.75a.25.25 0 01.25-.25h6.5a.25.25 0 01.25.25v10.5a.25.25 0 01-.25.25h-6.5a.25.25 0 01-.25-.25V2.75zM6 5a.75.75 0 000 1.5h4A.75.75 0 0010 5H6zm0 3a.75.75 0 000 1.5h4A.75.75 0 0010 8H6zm0 3a.75.75 0 000 1.5h4a.75.75 0 000-1.5H6z"/>
                    </svg>
                </div>
                <div class="doc-content">
                    <span class="doc-title">{$text('documentation.api_reference')}</span>
                </div>
            </a>

            <div class="nav-separator"></div>

            <!-- Top-level files -->
            {#each structure.files as file (file.slug)}
                {@const catInfo = getDocCategoryInfo(file.slug)}
                <a
                    href="/docs/{file.slug}"
                    class="doc-item"
                    class:active={isActive(file.slug)}
                >
                    <div class="doc-icon mate-profile {catInfo.category}" style="width: 28px; height: 28px; margin: 0; animation: none; opacity: 1;"></div>
                    <div class="doc-content">
                        <span class="doc-title">{file.title}</span>
                    </div>
                </a>
            {/each}

            <!-- Folder groups -->
            {#each structure.folders as folder (folder.path)}
                {@const isExpanded = expandedFolders.has(folder.path)}
                {@const containsActive = folderContainsActive(folder)}
                {@const folderIcon = DOCS_FOLDER_ICON[folder.path] || 'folder'}
                <div class="folder-group">
                    <button
                        class="group-header"
                        class:contains-active={containsActive}
                        onclick={() => toggleFolder(folder.path)}
                        aria-expanded={isExpanded}
                    >
                        <svg class="chevron" class:expanded={isExpanded} width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M6 4l4 4-4 4" />
                        </svg>
                        <h2 class="group-title">{folder.title}</h2>
                    </button>

                    {#if isExpanded}
                        <div class="folder-items">
                            {#each folder.files as file (file.slug)}
                                {@const catInfo = getDocCategoryInfo(file.slug)}
                                <a
                                    href="/docs/{file.slug}"
                                    class="doc-item nested"
                                    class:active={isActive(file.slug)}
                                >
                                    <div class="doc-icon mate-profile {catInfo.category}" style="width: 28px; height: 28px; margin: 0; animation: none; opacity: 1;"></div>
                                    <div class="doc-content">
                                        <span class="doc-title">{file.title}</span>
                                    </div>
                                </a>
                            {/each}

                            {#each folder.folders as subfolder (subfolder.path)}
                                {@const subIsExpanded = expandedFolders.has(subfolder.path)}
                                {@const subContainsActive = folderContainsActive(subfolder)}

                                <button
                                    class="sub-folder-header"
                                    class:contains-active={subContainsActive}
                                    onclick={() => toggleFolder(subfolder.path)}
                                    aria-expanded={subIsExpanded}
                                >
                                    <svg class="chevron" class:expanded={subIsExpanded} width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M6 4l4 4-4 4" />
                                    </svg>
                                    <span class="sub-folder-title">{subfolder.title}</span>
                                </button>

                                {#if subIsExpanded}
                                    {#each subfolder.files as file (file.slug)}
                                        {@const catInfo = getDocCategoryInfo(file.slug)}
                                        <a
                                            href="/docs/{file.slug}"
                                            class="doc-item nested-2"
                                            class:active={isActive(file.slug)}
                                        >
                                            <div class="doc-icon mate-profile {catInfo.category}" style="width: 28px; height: 28px; margin: 0; animation: none; opacity: 1;"></div>
                                            <div class="doc-content">
                                                <span class="doc-title">{file.title}</span>
                                            </div>
                                        </a>
                                    {/each}
                                {/if}
                            {/each}
                        </div>
                    {/if}
                </div>
            {/each}
        {/if}
    </div>
</div>

<style>
    .sidebar-wrapper {
        display: flex;
        flex-direction: column;
        height: 100%;
        background-color: var(--color-grey-20);
    }

    /* Top bar: search + close */
    .top-bar {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.75rem;
        border-bottom: 1px solid var(--color-grey-30);
        flex-shrink: 0;
    }

    .search-container {
        flex: 1;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        background-color: var(--color-grey-10);
        border-radius: 8px;
        padding: 0.5rem 0.75rem;
        border: 1px solid var(--color-grey-30);
        transition: border-color 0.15s ease;
    }

    .search-container:focus-within {
        border-color: var(--color-primary);
    }

    .search-icon {
        color: var(--color-font-secondary);
        flex-shrink: 0;
    }

    .search-input {
        flex: 1;
        background: none;
        border: none;
        outline: none;
        color: var(--color-font-primary);
        font-size: 0.875rem;
        min-width: 0;
    }

    .search-input::placeholder {
        color: var(--color-font-secondary);
    }

    .shortcut-badge {
        font-size: 0.65rem;
        padding: 0.15rem 0.35rem;
        border-radius: 4px;
        background-color: var(--color-grey-30);
        color: var(--color-font-secondary);
        font-family: inherit;
        white-space: nowrap;
    }

    .clear-btn {
        background: none;
        border: none;
        cursor: pointer;
        color: var(--color-font-secondary);
        padding: 2px;
        display: flex;
        border-radius: 4px;
    }

    .clear-btn:hover {
        color: var(--color-font-primary);
    }

    .close-btn {
        background: none;
        border: none;
        cursor: pointer;
        color: var(--color-font-secondary);
        padding: 0.25rem;
        border-radius: 6px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: all 0.15s ease;
    }

    .close-btn:hover {
        background-color: var(--color-grey-30);
        color: var(--color-font-primary);
    }

    /* Scrollable nav area */
    .nav-scroll {
        flex: 1;
        overflow-y: auto;
        padding: 0.5rem;
    }

    .nav-scroll::-webkit-scrollbar {
        width: 6px;
    }

    .nav-scroll::-webkit-scrollbar-track {
        background: transparent;
    }

    .nav-scroll::-webkit-scrollbar-thumb {
        background-color: var(--color-grey-40);
        border-radius: 3px;
    }

    /* Search results */
    .search-results {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .no-results {
        padding: 2rem 1rem;
        text-align: center;
        color: var(--color-font-secondary);
        font-size: 0.875rem;
    }

    /* Doc items — matches Chat.svelte item style */
    .doc-item {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.625rem 0.75rem;
        border-radius: 10px;
        text-decoration: none;
        color: var(--color-font-primary);
        transition: background-color 0.15s ease;
        cursor: pointer;
    }

    .doc-item:hover {
        background-color: var(--color-grey-30);
    }

    .doc-item.active {
        background-color: var(--color-grey-30);
    }

    .doc-item.nested {
        padding-inline-start: 1.5rem;
    }

    .doc-item.nested-2 {
        padding-inline-start: 2.25rem;
    }

    /* Avatar circle — reuses global .mate-profile CSS for gradients */
    .doc-icon {
        flex-shrink: 0;
        /* The ::after and ::before pseudo-elements from mates.css add
           the AI badge — hide them for docs items */
    }

    .doc-icon::after,
    .doc-icon::before {
        display: none !important;
    }

    .doc-icon-simple {
        width: 28px;
        height: 28px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        color: var(--color-font-secondary);
    }

    .doc-content {
        display: flex;
        flex-direction: column;
        min-width: 0;
        flex: 1;
    }

    .doc-title {
        font-size: 0.875rem;
        font-weight: 500;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .doc-preview {
        font-size: 0.75rem;
        color: var(--color-font-secondary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* API item special style */
    .api-item {
        font-weight: 500;
    }

    /* Folder groups — matches chat time groups */
    .folder-group {
        margin-bottom: 0.25rem;
    }

    .group-header {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        width: 100%;
        padding: 0.5rem 0.75rem;
        background: none;
        border: none;
        cursor: pointer;
        text-align: start;
        border-radius: 8px;
        transition: background-color 0.15s ease;
    }

    .group-header:hover {
        background-color: var(--color-grey-30);
    }

    .group-header.contains-active {
        color: var(--color-primary);
    }

    .group-title {
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        color: var(--color-font-secondary);
        letter-spacing: 0.05em;
        margin: 0;
    }

    .group-header.contains-active .group-title {
        color: var(--color-primary);
    }

    .chevron {
        flex-shrink: 0;
        color: var(--color-font-secondary);
        transition: transform 0.2s ease;
    }

    .chevron.expanded {
        transform: rotate(90deg);
    }

    .folder-items {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .sub-folder-header {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        width: 100%;
        padding: 0.375rem 0.75rem;
        padding-inline-start: 1.5rem;
        background: none;
        border: none;
        cursor: pointer;
        text-align: start;
        border-radius: 8px;
        transition: background-color 0.15s ease;
    }

    .sub-folder-header:hover {
        background-color: var(--color-grey-30);
    }

    .sub-folder-header.contains-active {
        color: var(--color-primary);
    }

    .sub-folder-title {
        font-size: 0.8125rem;
        font-weight: 500;
        color: var(--color-font-secondary);
    }

    .sub-folder-header.contains-active .sub-folder-title {
        color: var(--color-primary);
    }

    .nav-separator {
        height: 1px;
        background-color: var(--color-grey-30);
        margin: 0.5rem 0.75rem;
    }

    /* TOC section */
    .toc-section {
        padding: 0.5rem;
    }

    .toc-section .group-title {
        padding: 0.25rem 0.5rem;
        margin-bottom: 0.25rem;
    }

    .toc-item {
        display: block;
        width: 100%;
        padding: 0.375rem 0.75rem;
        background: none;
        border: none;
        cursor: pointer;
        text-align: start;
        font-size: 0.8125rem;
        color: var(--color-font-secondary);
        border-radius: 6px;
        transition: all 0.15s ease;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .toc-item:hover {
        background-color: var(--color-grey-30);
        color: var(--color-font-primary);
    }

    .toc-item.toc-h3 {
        padding-inline-start: 1.5rem;
        font-size: 0.75rem;
    }
</style>
