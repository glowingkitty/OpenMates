<script lang="ts">
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { externalLinks, routes } from '$lib/config/links';
    import { isPageVisible } from '$lib/config/pages';
    import { replaceOpenMates } from '$lib/actions/replaceText';
    // Updated helper function to check if a path is active and visible
    const isActive = (path: string) => {
        if (!isPageVisible(path)) return false;
        
        // For docs section, check if current path starts with docs path
        if (path === routes.docs.main) {
            return $page.url.pathname.startsWith(path);
        }
        // For other paths, keep exact matching
        return $page.url.pathname === path;
    };

    // Navigation items using centralized routes, filtered by visibility
    const navItems = [
        { href: routes.home, text: 'For all of us' },
        { href: routes.developers, text: 'For Developers' },
        { href: routes.docs.main, text: 'Docs' }
    ].filter(item => isPageVisible(item.href));

    // Social media links
    const socialLinks = [
        {
            href: externalLinks.github,
            ariaLabel: "Visit our GitHub page",
            iconClass: "github"
        }
    ];

    // Only show navigation section if we have at least 2 nav items
    const showNavLinks = navItems.length >= 2;
    // Show social links only if nav section is visible
    const showSocialLinks = showNavLinks && socialLinks.length > 0;

    const handleClick = async (event: MouseEvent, path: string, external: boolean = false) => {
        if (external || event.ctrlKey || event.metaKey || event.button === 1) {
            return;
        }
        event.preventDefault();
        await goto(path, { replaceState: false });
    }
</script>

<header use:replaceOpenMates>
    <div class="container">
        <nav>
            <div class="left-section">
                <a
                    href="/"
                    class="logo-link"
                    on:click={(e) => handleClick(e, '/')}
                >
                    <bold>OpenMates</bold>
                </a>
            </div>
            {#if showNavLinks}
            <div class="nav-links">
                {#each navItems as item}
                    <a
                        href={item.href}
                        class="nav-link"
                        class:active={isActive(item.href)}
                        on:click={(e) => handleClick(e, item.href)}
                    >
                        {item.text}
                    </a>
                {/each}
                {#if showSocialLinks}
                <div class="icon-links">
                    {#each socialLinks as link}
                        <a
                            href={link.href}
                            target="_blank"
                            rel="noopener noreferrer"
                            class="icon-link"
                            aria-label={link.ariaLabel}
                        >
                            <div class="small-icon {link.iconClass}"></div>
                        </a>
                    {/each}
                </div>
                {/if}
            </div>
            {/if}
        </nav>
    </div>
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

    .container {
        /* max-width: 1000px; */
        margin: 0 auto;
        width: 100%;
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
    }

    .icon-link:hover {
        opacity: 1;
    }

    /* Ensure all icon classes have defined styles */
    .github-icon {
        width: 24px;
        height: 24px;
        background-image: url('/icons/github.svg');
        background-size: contain;
        background-repeat: no-repeat;
    }

    .opencollective-icon {
        width: 24px;
        height: 24px;
        background-image: url('/icons/opencollective.svg');
        background-size: contain;
        background-repeat: no-repeat;
    }

    .twitter-icon {
        width: 24px;
        height: 24px;
        background-image: url('/icons/twitter.svg');
        background-size: contain;
        background-repeat: no-repeat;
    }
</style> 