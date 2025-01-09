<script lang="ts">
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { externalLinks, routes } from '../../lib/config/links';
    import { isPageVisible } from '../../lib/config/pages';
    import { replaceOpenMates } from '../../lib/actions/replaceText';

    // Add context prop
    export let context: 'website' | 'webapp' = 'website';

    // Separate navigation items for web app and website
    const websiteNavItems = [
        { href: routes.home, text: 'For all of us' },
        { href: routes.developers, text: 'For Developers' },
        { href: routes.docs.main, text: 'Docs' }
    ].filter(item => isPageVisible(item.href));

    // Define interface for nav items
    interface NavItem {
        href: string;
        text: string;
    }

    // Add type annotation to webAppNavItems
    const webAppNavItems: NavItem[] = [
        // { href: '/app/chat', text: 'Chat' },
        // { href: '/app/projects', text: 'Projects' },
        // { href: '/app/workflows', text: 'Workflows' }
    ]; // TODO add those pages later

    // Define the type for social links
    type SocialLink = {
        href: string;
        ariaLabel: string;
        iconClass: string;
    };

    // Social media links with explicit type
    const socialLinks: SocialLink[] = [
        // {
        //     href: externalLinks.github,
        //     ariaLabel: "Visit our GitHub page",
        //     iconClass: "github"
        // }
    ];

    // Use appropriate nav items based on context
    $: navItems = context === 'webapp' ? webAppNavItems : websiteNavItems;

    // Only show navigation section if we have at least 2 nav items
    $: showNavLinks = navItems?.length >= 2;
    
    // Show social links only if nav section is visible and we have social links
    $: showSocialLinks = showNavLinks && socialLinks?.length > 0;
    
    // Show social section only for website and if we have social links
    $: showSocialSection = context === 'website' && showSocialLinks;

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

    const handleClick = async (event: MouseEvent, path: string, external: boolean = false) => {
        if (external || event.ctrlKey || event.metaKey || event.button === 1) {
            return;
        }
        event.preventDefault();
        await goto(path, { replaceState: false });
    }

    // Add state for mobile menu
    let isMobileMenuOpen = false;
    
    // Function to toggle mobile menu
    const toggleMobileMenu = () => {
        isMobileMenuOpen = !isMobileMenuOpen;
    };

    // Close mobile menu when route changes
    $: if ($page.url.pathname) {
        isMobileMenuOpen = false;
    }
</script>

<header use:replaceOpenMates class:webapp={context === 'webapp'}>
    <div class="container">
        <nav class:webapp={context === 'webapp'}>
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
                <!-- Mobile menu button only shown for website -->
                {#if context === 'website'}
                    <button 
                        class="mobile-menu-button" 
                        on:click={toggleMobileMenu}
                        aria-label="Toggle navigation menu"
                    >
                        <div class:open={isMobileMenuOpen} class="hamburger">
                            <span></span>
                            <span></span>
                            <span></span>
                        </div>
                    </button>
                {/if}

                <div class="nav-links" 
                     class:mobile-open={isMobileMenuOpen} 
                     class:webapp={context === 'webapp'}>
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
                    
                    {#if showSocialSection}
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
        z-index: 1000;
        padding: 1rem 2rem;
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
    }

    /* Add website-specific gradient */
    header:not(.webapp) {
        background: linear-gradient(to top, rgba(255, 255, 255, 0) 0%, var(--color-grey-20) 100%);
    }

    /* Update webapp header styles */
    header.webapp {
        position: relative;
    }

    .container {
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

    /* Remove max-width constraint for webapp navigation */
    nav.webapp {
        max-width: none;
    }

    .left-section {
        flex-shrink: 0;
        user-select: none;
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
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
        color: var(--color-font-primary);
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

    /* Add mobile menu styles */
    .mobile-menu-button {
        all: unset;
        display: none;
        background: none;
        border: none;
        cursor: pointer;
        z-index: 1001;
    }

    .hamburger {
        width: 24px;
        height: 20px;
        position: relative;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }

    .hamburger span {
        display: block;
        height: 2px;
        width: 100%;
        background-color: var(--color-font-primary);
        transition: all 0.3s ease;
    }

    .hamburger.open span:nth-child(1) {
        transform: translateY(9px) rotate(45deg);
    }

    .hamburger.open span:nth-child(2) {
        opacity: 0;
    }

    .hamburger.open span:nth-child(3) {
        transform: translateY(-9px) rotate(-45deg);
    }

    @media (max-width: 600px) {
        .mobile-menu-button {
            display: block;
        }

        .nav-links {
            display: none;
            position: fixed;
            top: 4rem;
            left: 0;
            right: 0;
            bottom: 0;
            backdrop-filter: blur(10px);
            flex-direction: column;
            justify-content: flex-start;
            align-items: center;
            padding: 2rem;
            gap: 2rem;
            z-index: 1000;
        }

        .nav-links.mobile-open {
            display: flex;
        }

        .icon-links {
            margin: 1rem 0 0 0;
        }
    }

    /* Add context-specific styles */
    nav.webapp {
        grid-template-columns: auto 1fr auto;
    }

    .nav-links.webapp {
        justify-content: center;
        padding: 0 70px; /* Make space for the profile icon */
    }

    .user-profile {
        position: absolute;
        right: 0;
        top: 50%;
        transform: translateY(-50%);
    }

    .profile-icon {
        width: 70px;
        height: 70px;
        border-radius: 50%;
        background-color: var(--color-grey-40);
        background-image: url('/icons/user-profile.svg');
        background-size: 60%;
        background-position: center;
        background-repeat: no-repeat;
        cursor: pointer;
    }

    @media (max-width: 600px) {
        .nav-links.webapp {
            display: flex;
            position: static;
            padding: 0 70px;
            flex-direction: row;
            background: none;
            backdrop-filter: none;
        }
    }
</style> 