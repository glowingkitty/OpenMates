<script lang="ts">
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';

    // Props for configurable URLs
    export let githubUrl = "https://github.com/OpenMates/OpenMates";
    export let openCollectiveUrl = "https://opencollective.com/openmates";

    // Helper function to determine if a path is active
    const isActive = (path: string) => {
        return $page.url.pathname === path;
    }

    // Handle click events to prevent full page reload while allowing new tab behavior
    const handleClick = async (event: MouseEvent, path: string) => {
        // Allow default behavior (new tab) if ctrl/cmd/middle click
        if (event.ctrlKey || event.metaKey || event.button === 1) {
            return;
        }

        // Prevent default link behavior
        event.preventDefault();

        // Use SvelteKit's client-side navigation
        await goto(path, { replaceState: false });
    }
</script>

<header>
    <nav>
        <div class="left-section">
            <a
                href="/"
                class="logo-link"
                on:click={(e) => handleClick(e, '/')}
            >
                <span class="logo-text">Open</span>
                <span class="logo-text highlight">Mates</span>
            </a>
        </div>
        <div class="nav-links">
            <a
                href="/"
                class="nav-link"
                class:active={isActive('/')}
                on:click={(e) => handleClick(e, '/')}
            >
                For all of us
            </a>
            <a
                href="/developers"
                class="nav-link"
                class:active={isActive('/developers')}
                on:click={(e) => handleClick(e, '/developers')}
            >
                For developers
            </a>
            <a
                href="/docs"
                class="nav-link"
                class:active={isActive('/docs')}
                on:click={(e) => handleClick(e, '/docs')}
            >
                Docs
            </a>
            <div class="icon-links">
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
        </div>
    </nav>
</header>

<style>
    header {
        width: 100%;
        background: linear-gradient(to top, rgba(255, 255, 255, 0) 0%, rgba(255, 255, 255, 0.8) 100%);
        z-index: 1000;
        padding: 1rem 2rem;
        position: fixed;
        top: 0;
        left: 0;
    }

    nav {
        display: flex;
        justify-content: space-between;
        align-items: center;
        max-width: 1400px;
        margin: 0 auto;
    }

    .left-section {
        flex-shrink: 0;
    }

    .logo-link {
        font-size: 1.25rem;
        font-weight: 600;
        display: flex;
        gap: 0.25rem;
        text-decoration: none;
        cursor: pointer;
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
        align-items: center;
        justify-content: flex-end;
        flex-grow: 1;
    }

    .icon-links {
        display: flex;
        gap: 1rem;
        align-items: center;
        margin-left: 1.5rem;
    }

    .nav-link {
        text-decoration: none;
        color: var(--text-color, #000);
        opacity: 0.5;
        transition: opacity 0.2s ease;
        cursor: pointer;
    }

    .nav-link:hover {
        opacity: 0.75;
    }

    .nav-link.active {
        opacity: 1;
        font-weight: bold;
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