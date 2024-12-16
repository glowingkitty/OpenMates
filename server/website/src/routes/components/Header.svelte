<script lang="ts">
    import { page } from '$app/stores';
    
    // Props for configurable URLs
    export let githubUrl = "https://github.com/OpenMates/OpenMates";
    export let openCollectiveUrl = "https://opencollective.com/openmates";
    
    // Helper function to determine if a path is active
    const isActive = (path: string) => {
        return $page.url.pathname === path;
    }
</script>

<header>
    <nav>
        <div class="left-section">
            <a href="/" class="logo-link">
                <span class="logo-text">Open</span>
                <span class="logo-text highlight">Mates</span>
            </a>
            <div class="nav-links">
                <a 
                    href="/" 
                    class="nav-link"
                    class:active={isActive('/')}
                >
                    For all of us
                </a>
                <a 
                    href="/developers" 
                    class="nav-link"
                    class:active={isActive('/developers')}
                >
                    For developers
                </a>
                <a 
                    href="/docs" 
                    class="nav-link"
                    class:active={isActive('/docs')}
                >
                    Docs
                </a>
            </div>
        </div>
        <div class="right-section">
            <a 
                href={githubUrl} 
                target="_blank" 
                rel="noopener noreferrer" 
                class="icon-link"
                aria-label="Visit our GitHub page"
            >
                <div class="github-icon"></div>
            </a>
            <a 
                href={openCollectiveUrl} 
                target="_blank" 
                rel="noopener noreferrer" 
                class="icon-link"
                aria-label="Support us on OpenCollective"
            >
                <div class="opencollective-icon"></div>
            </a>
        </div>
    </nav>
</header>

<style>
    header {
        width: 100%;
        background: var(--background, rgba(255, 255, 255, 0.8));
        backdrop-filter: blur(10px);
        z-index: 1000;
        padding: 1rem 2rem;
    }

    nav {
        display: flex;
        justify-content: space-between;
        align-items: center;
        max-width: 1400px;
        margin: 0 auto;
    }

    .left-section {
        display: flex;
        align-items: center;
        gap: 2rem;
    }

    .logo-link {
        font-size: 1.25rem;
        font-weight: 600;
        text-decoration: none;
        display: flex;
        gap: 0.25rem;
    }

    .logo-text {
        color: var(--text-color, #000);
    }

    .logo-text.highlight {
        color: var(--primary-color, #4361ee);
    }

    .nav-links {
        display: flex;
        gap: 1.5rem;
    }

    .nav-link {
        text-decoration: none;
        color: var(--text-color, #000);
        opacity: 0.5;
        transition: opacity 0.2s ease;
    }

    .nav-link:hover {
        opacity: 0.75;
    }

    .nav-link.active {
        opacity: 1;
    }

    .right-section {
        display: flex;
        gap: 1rem;
        align-items: center;
    }

    .icon-link {
        opacity: 0.5;
        transition: opacity 0.2s ease;
        line-height: 0;
    }

    .icon-link:hover {
        opacity: 1;
    }
</style> 