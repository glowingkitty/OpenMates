<script lang="ts">
    /**
     * DocsSearch Component
     * 
     * Full-text search within documentation.
     * Features:
     * - Keyboard shortcut (Cmd/Ctrl + K)
     * - Search results with context snippets
     * - Navigate with keyboard
     */
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { goto } from '$app/navigation';
    import docsData from '$lib/generated/docs-data.json';
    
    // State
    let isOpen = $state(false);
    let query = $state('');
    let results = $state<Array<{ id: string; title: string; slug: string; snippet: string }>>([]);
    let selectedIndex = $state(0);
    let inputElement: HTMLInputElement | null = $state(null);
    let dialogElement: HTMLDivElement | null = $state(null);
    
    // Search index from generated data
    const searchIndex = docsData.searchIndex || [];
    
    /**
     * Open search dialog
     */
    function openSearch() {
        isOpen = true;
        query = '';
        results = [];
        selectedIndex = 0;
        // Focus input after dialog opens
        setTimeout(() => inputElement?.focus(), 50);
    }
    
    /**
     * Close search dialog
     */
    function closeSearch() {
        isOpen = false;
        query = '';
        results = [];
    }
    
    /**
     * Perform search
     */
    function performSearch() {
        if (!query.trim()) {
            results = [];
            return;
        }
        
        const searchTerms = query.toLowerCase().split(/\s+/).filter(Boolean);
        
        // Simple search implementation
        // For better performance, consider using FlexSearch
        const scored = searchIndex
            .map(item => {
                let score = 0;
                const titleLower = item.title.toLowerCase();
                const contentLower = item.content.toLowerCase();
                
                for (const term of searchTerms) {
                    // Title matches score higher
                    if (titleLower.includes(term)) {
                        score += 10;
                    }
                    // Content matches
                    if (contentLower.includes(term)) {
                        score += 1;
                    }
                }
                
                // Extract snippet around first match
                let snippet = '';
                if (score > 0) {
                    const firstTerm = searchTerms[0];
                    const matchIndex = contentLower.indexOf(firstTerm);
                    if (matchIndex >= 0) {
                        const start = Math.max(0, matchIndex - 50);
                        const end = Math.min(item.content.length, matchIndex + 100);
                        snippet = (start > 0 ? '...' : '') + 
                                  item.content.substring(start, end) + 
                                  (end < item.content.length ? '...' : '');
                    }
                }
                
                return { ...item, score, snippet };
            })
            .filter(item => item.score > 0)
            .sort((a, b) => b.score - a.score)
            .slice(0, 10);
        
        results = scored;
        selectedIndex = 0;
    }
    
    /**
     * Handle keyboard navigation
     */
    function handleKeydown(event: KeyboardEvent) {
        switch (event.key) {
            case 'ArrowDown':
                event.preventDefault();
                selectedIndex = Math.min(selectedIndex + 1, results.length - 1);
                break;
            case 'ArrowUp':
                event.preventDefault();
                selectedIndex = Math.max(selectedIndex - 1, 0);
                break;
            case 'Enter':
                event.preventDefault();
                if (results[selectedIndex]) {
                    navigateTo(results[selectedIndex].slug);
                }
                break;
            case 'Escape':
                closeSearch();
                break;
        }
    }
    
    /**
     * Navigate to selected result
     */
    function navigateTo(slug: string) {
        closeSearch();
        goto(`/docs/${slug}`);
    }
    
    // Watch query changes for search
    $effect(() => {
        if (query) {
            performSearch();
        } else {
            results = [];
        }
    });
    
    // Global keyboard shortcut
    onMount(() => {
        if (!browser) return;
        
        const handleGlobalKeydown = (event: KeyboardEvent) => {
            // Cmd/Ctrl + K to open search
            if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
                event.preventDefault();
                openSearch();
            }
        };
        
        document.addEventListener('keydown', handleGlobalKeydown);
        
        return () => {
            document.removeEventListener('keydown', handleGlobalKeydown);
        };
    });
    
    // Close when clicking outside
    function handleBackdropClick(event: MouseEvent) {
        if (event.target === dialogElement) {
            closeSearch();
        }
    }
</script>

<button class="search-trigger" onclick={openSearch}>
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
        <path d="M10.68 11.74a6 6 0 01-8.46-8.46 6 6 0 018.46 8.46l4.07 4.07a.75.75 0 01-1.06 1.06l-4.07-4.07zm-1.22-1.22A4.5 4.5 0 106.5 2a4.5 4.5 0 003.46 8.46z"/>
    </svg>
    <span class="search-placeholder">Search docs...</span>
    <kbd>⌘K</kbd>
</button>

{#if isOpen}
    <div 
        class="search-dialog" 
        bind:this={dialogElement}
        onclick={handleBackdropClick}
        onkeydown={handleKeydown}
        role="dialog"
        aria-modal="true"
        aria-label="Search documentation"
        tabindex="-1"
    >
        <div class="search-content">
            <div class="search-input-wrapper">
                <svg width="20" height="20" viewBox="0 0 16 16" fill="currentColor" class="search-icon">
                    <path d="M10.68 11.74a6 6 0 01-8.46-8.46 6 6 0 018.46 8.46l4.07 4.07a.75.75 0 01-1.06 1.06l-4.07-4.07zm-1.22-1.22A4.5 4.5 0 106.5 2a4.5 4.5 0 003.46 8.46z"/>
                </svg>
                <input 
                    type="text"
                    bind:this={inputElement}
                    bind:value={query}
                    placeholder="Search documentation..."
                    class="search-input"
                />
                <button class="search-close" onclick={closeSearch}>
                    <kbd>Esc</kbd>
                </button>
            </div>
            
            {#if results.length > 0}
                <ul class="search-results">
                    {#each results as result, index}
                        <li class:selected={index === selectedIndex}>
                            <button onclick={() => navigateTo(result.slug)}>
                                <span class="result-title">{result.title}</span>
                                <span class="result-snippet">{result.snippet}</span>
                            </button>
                        </li>
                    {/each}
                </ul>
            {:else if query.trim()}
                <div class="no-results">
                    No results found for "{query}"
                </div>
            {:else}
                <div class="search-hint">
                    Type to search documentation
                </div>
            {/if}
        </div>
    </div>
{/if}

<style>
    .search-trigger {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 0.75rem;
        background-color: var(--color-grey-100, #f3f4f6);
        border: 1px solid var(--color-grey-200, #e5e5e5);
        border-radius: 0.5rem;
        color: var(--color-grey-500, #6b7280);
        font-size: 0.875rem;
        cursor: pointer;
        transition: all 0.15s ease;
        min-width: 200px;
    }
    
    .search-trigger:hover {
        background-color: var(--color-grey-200, #e5e5e5);
        border-color: var(--color-grey-300, #d1d5db);
    }
    
    .search-placeholder {
        flex: 1;
        text-align: left;
    }
    
    .search-trigger kbd {
        padding: 0.125rem 0.375rem;
        background-color: var(--color-grey-50, #ffffff);
        border: 1px solid var(--color-grey-200, #e5e5e5);
        border-radius: 0.25rem;
        font-family: inherit;
        font-size: 0.75rem;
    }
    
    .search-dialog {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: flex-start;
        justify-content: center;
        padding-top: 10vh;
        z-index: 1000;
    }
    
    .search-content {
        width: 100%;
        max-width: 600px;
        margin: 0 1rem;
        background-color: var(--color-grey-50, #ffffff);
        border-radius: 0.75rem;
        box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3);
        overflow: hidden;
    }
    
    .search-input-wrapper {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 1rem;
        border-bottom: 1px solid var(--color-grey-200, #e5e5e5);
    }
    
    .search-icon {
        color: var(--color-grey-400, #9ca3af);
        flex-shrink: 0;
    }
    
    .search-input {
        flex: 1;
        border: none;
        background: none;
        font-size: 1rem;
        color: var(--color-grey-900, #111827);
        outline: none;
    }
    
    .search-input::placeholder {
        color: var(--color-grey-400, #9ca3af);
    }
    
    .search-close {
        background: none;
        border: none;
        cursor: pointer;
        padding: 0.25rem;
    }
    
    .search-close kbd {
        padding: 0.125rem 0.5rem;
        background-color: var(--color-grey-100, #f3f4f6);
        border: 1px solid var(--color-grey-200, #e5e5e5);
        border-radius: 0.25rem;
        font-family: inherit;
        font-size: 0.75rem;
        color: var(--color-grey-500, #6b7280);
    }
    
    .search-results {
        list-style: none;
        padding: 0;
        margin: 0;
        max-height: 400px;
        overflow-y: auto;
    }
    
    .search-results li button {
        display: block;
        width: 100%;
        padding: 0.75rem 1rem;
        background: none;
        border: none;
        text-align: left;
        cursor: pointer;
        transition: background-color 0.1s ease;
    }
    
    .search-results li:hover button,
    .search-results li.selected button {
        background-color: var(--color-grey-100, #f3f4f6);
    }
    
    .result-title {
        display: block;
        font-weight: 500;
        color: var(--color-grey-900, #111827);
        margin-bottom: 0.25rem;
    }
    
    .result-snippet {
        display: block;
        font-size: 0.8125rem;
        color: var(--color-grey-500, #6b7280);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    
    .no-results,
    .search-hint {
        padding: 2rem 1rem;
        text-align: center;
        color: var(--color-grey-500, #6b7280);
    }
    
    @media (max-width: 767px) {
        .search-trigger {
            min-width: auto;
            padding: 0.5rem;
        }
        
        .search-placeholder,
        .search-trigger kbd {
            display: none;
        }
    }
</style>
