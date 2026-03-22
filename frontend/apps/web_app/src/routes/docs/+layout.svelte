<script lang="ts">
    /**
     * Docs Layout Component
     * 
     * Provides the layout structure for all documentation pages including:
     * - Sidebar navigation (collapsible on mobile)
     * - Main content area
     * - Responsive design with mobile drawer
     * 
     * This layout wraps all /docs/* routes.
     */
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { page } from '$app/state';
    import DocsSidebar from '$lib/components/docs/DocsSidebar.svelte';
    import DocsSearch from '$lib/components/docs/DocsSearch.svelte';
    
    let { children } = $props();
    
    // Sidebar state - open by default on desktop, closed on mobile
    let sidebarOpen = $state(true);
    let isMobile = $state(false);
    
    // Check viewport size on mount and resize
    onMount(() => {
        const checkMobile = () => {
            isMobile = window.innerWidth < 768;
            // Close sidebar by default on mobile
            if (isMobile) {
                sidebarOpen = false;
            }
        };
        
        checkMobile();
        window.addEventListener('resize', checkMobile);
        
        return () => {
            window.removeEventListener('resize', checkMobile);
        };
    });
    
    // Toggle sidebar visibility
    function toggleSidebar() {
        sidebarOpen = !sidebarOpen;
    }
    
    // Track previous path to detect navigation
    let previousPath = '';
    
    // Close sidebar when navigating on mobile
    $effect(() => {
        const currentPath = page.url.pathname;
        if (browser && isMobile && currentPath && currentPath !== previousPath) {
            previousPath = currentPath;
            sidebarOpen = false;
        }
    });
</script>

<div class="docs-layout" class:sidebar-open={sidebarOpen}>
    <!-- Mobile header with menu toggle -->
    <header class="docs-header">
        <button 
            class="menu-toggle" 
            onclick={toggleSidebar}
            aria-label={sidebarOpen ? 'Close menu' : 'Open menu'}
        >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                {#if sidebarOpen}
                    <path d="M18 6L6 18M6 6l12 12"/>
                {:else}
                    <path d="M3 12h18M3 6h18M3 18h18"/>
                {/if}
            </svg>
        </button>
        
        <a href="/docs" class="docs-logo">
            <span class="logo-text">OpenMates Docs</span>
        </a>
        
        <DocsSearch />
    </header>
    
    <!-- Sidebar navigation -->
    <aside class="docs-sidebar" class:open={sidebarOpen}>
        <DocsSidebar onNavigate={() => isMobile && (sidebarOpen = false)} />
    </aside>
    
    <!-- Overlay for mobile when sidebar is open -->
    {#if isMobile && sidebarOpen}
        <button 
            class="sidebar-overlay" 
            onclick={() => sidebarOpen = false}
            aria-label="Close sidebar"
        ></button>
    {/if}
    
    <!-- Main content area -->
    <main class="docs-content">
        {@render children()}
    </main>
</div>

<style>
    .docs-layout {
        display: grid;
        grid-template-columns: 280px 1fr;
        grid-template-rows: auto 1fr;
        grid-template-areas:
            "header header"
            "sidebar content";
        min-height: 100vh;
        background-color: var(--color-grey-0, #fafafa);
    }
    
    .docs-header {
        grid-area: header;
        display: flex;
        align-items: center;
        gap: 1rem;
        padding: 0.75rem 1.5rem;
        background-color: var(--color-grey-50, #ffffff);
        border-bottom: 1px solid var(--color-grey-200, #e5e5e5);
        position: sticky;
        top: 0;
        z-index: 100;
    }
    
    .menu-toggle {
        display: none;
        padding: 0.5rem;
        background: none;
        border: none;
        cursor: pointer;
        color: var(--color-grey-700, #374151);
        border-radius: 0.375rem;
    }
    
    .menu-toggle:hover {
        background-color: var(--color-grey-100, #f3f4f6);
    }
    
    .docs-logo {
        text-decoration: none;
        color: var(--color-grey-900, #111827);
        font-weight: 600;
        font-size: 1.125rem;
    }
    
    .logo-text {
        background: linear-gradient(135deg, var(--color-primary, #3b82f6), var(--color-primary-dark, #2563eb));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    
    .docs-sidebar {
        grid-area: sidebar;
        background-color: var(--color-grey-50, #ffffff);
        border-right: 1px solid var(--color-grey-200, #e5e5e5);
        overflow-y: auto;
        height: calc(100vh - 57px);
        position: sticky;
        top: 57px;
    }
    
    .docs-content {
        grid-area: content;
        padding: 2rem;
        max-width: 900px;
        width: 100%;
    }
    
    .sidebar-overlay {
        display: none;
    }
    
    /* Mobile styles */
    @media (max-width: 767px) {
        .docs-layout {
            grid-template-columns: 1fr;
            grid-template-areas:
                "header"
                "content";
        }
        
        .menu-toggle {
            display: block;
        }
        
        .docs-sidebar {
            position: fixed;
            top: 57px;
            left: 0;
            bottom: 0;
            width: 280px;
            z-index: 200;
            transform: translateX(-100%);
            transition: transform 0.3s ease;
        }
        
        .docs-sidebar.open {
            transform: translateX(0);
        }
        
        .sidebar-overlay {
            display: block;
            position: fixed;
            top: 57px;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: rgba(0, 0, 0, 0.5);
            z-index: 150;
            border: none;
            cursor: pointer;
        }
        
        .docs-content {
            padding: 1rem;
        }
    }
</style>
