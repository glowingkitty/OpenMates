<script lang="ts">
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { externalLinks, routes } from '../config/links';
    import { isPageVisible } from '../config/pages';
    import { replaceOpenMates } from '../actions/replaceText';
    import { waitLocale } from 'svelte-i18n';  // Remove t import
    import { onMount, tick } from 'svelte';
    import { isMenuOpen } from '../stores/menuState';
    import { text } from '@repo/ui';
    import { isInSignupProcess } from '../stores/signupState'; // Import the signup state

    export let context: 'website' | 'webapp' = 'website';
    export let isLoggedIn = false;

    let headerDiv: HTMLElement;
    
    async function initializeContent() {
        await waitLocale();
        await tick();
        if (headerDiv) {
            replaceOpenMates(headerDiv);
        }
    }

    onMount(() => {
        initializeContent();
    });

    // Simplify the websiteNavItems - remove isTranslationsReady check
    $: websiteNavItems = [
        { href: routes.home, text: $text('navigation.for_all.text') },
        { href: routes.developers, text: $text('navigation.for_developers.text') },
        { href: routes.docs.main, text: $text('navigation.docs.text') }
    ].filter(item => item.href && isPageVisible(item.href));

    interface NavItem {
        href: string;
        text: string;
    }

    // Update the webAppNavItems based on login state
    $: webAppNavItems = isLoggedIn ? [
        // { href: '/app/chat', text: $t('navigation.chat.text') },
        // { href: '/app/projects', text: $t('navigation.projects.text') },
        // { href: '/app/workflows', text: $t('navigation.workflows.text') }
    ] : [];

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
    const isActive = (path: string | null) => {
        if (!path || !isPageVisible(path)) return false;
        
        // For docs section, check if current path starts with docs path
        if (path === routes.docs.main) {
            return $page.url.pathname.startsWith(path);
        }
        // For other paths, keep exact matching
        return $page.url.pathname === path;
    };

    const handleClick = async (event: MouseEvent, path: string | null, external: boolean = false) => {
        if (!path || external || event.ctrlKey || event.metaKey || event.button === 1) {
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

    // Add mobile breakpoint check
    let isMobile = false;

    onMount(() => {
        const checkMobile = () => {
            isMobile = window.innerWidth < 730;
        };
        
        checkMobile();
        window.addEventListener('resize', checkMobile);
        
        return () => {
            window.removeEventListener('resize', checkMobile);
        };
    });

    // Update menu toggle logic to only work when logged in and not in signup process
    const toggleMenu = () => {
        if (isLoggedIn && !$isInSignupProcess) {
            isMenuOpen.set(!$isMenuOpen);
        }
    };

    // Add reactive statement to update nav items when auth state changes
    $: {
        if (!isLoggedIn) {
            // Reset to website navigation when logged out
            navItems = websiteNavItems;
        } else if (context === 'webapp') {
            // Use web app navigation when logged in and in webapp context
            navItems = webAppNavItems;
        } else {
            // Otherwise use website nav items
            navItems = websiteNavItems;
        }
    }

    // Add custom transition function
    function slideFade(node: HTMLElement, { 
        duration = 200 
    }) {
        const width = node.offsetWidth; // Get the natural width
        
        return {
            duration,
            css: (t: number) => {
                const eased = t; // Linear easing, but you can use different easing functions
                return `
                    width: ${eased * width}px;
                    opacity: ${eased};
                    overflow: hidden;
                `;
            }
        };
    }
</script>

<header bind:this={headerDiv} class:webapp={context === 'webapp'}>
    {#await waitLocale()}
        <div class="container">
            <!-- Minimal header content while loading -->
            <nav class:webapp={context === 'webapp'}>
                <div class="left-section">
                    <span class="logo-link">OpenMates</span>
                </div>
            </nav>
        </div>
    {:then}
        <div class="container">
            <nav class:webapp={context === 'webapp'}>
                <div class="left-section">
                    {#if context === 'webapp' && isLoggedIn && (isMobile || !$isMenuOpen) && !$isInSignupProcess}
                        <div transition:slideFade={{ duration: 200 }}>
                            <button 
                                class="clickable-icon icon_menu"
                                on:click={toggleMenu}
                                aria-label={$text('header.toggle_menu.text')}
                            ></button>
                        </div>
                    {/if}
                    <a
                        href="/"
                        class="logo-link"
                        on:click={(e) => handleClick(e, '/')}
                    >
                        <strong><mark>Open</mark><span style="color: var(--color-grey-100);">Mates</span></strong>
                    </a>
                </div>

                {#if showNavLinks && (context !== 'webapp' || isLoggedIn)}
                    <!-- Mobile menu button only shown for website -->
                    {#if context === 'website'}
                        <button 
                            class="mobile-menu-button" 
                            on:click={toggleMobileMenu}
                            aria-label={$text('header.toggle_menu.text')}
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
    {/await}
</header>

<style>
    header {
        z-index: 1000;
        padding: 20px;
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
    }

    .logo-link {
        font-size: 1.25rem;
        font-weight: 600;
        display: flex;
        gap: 0.25rem;
        text-decoration: none;
        cursor: pointer;
        color: inherit;
    }

    .logo-link :global(mark),
    .logo-link :global(strong),
    .logo-link :global(span) {
        color: inherit;
        text-decoration: none;
    }

    .logo-link :global(mark) {
        background-color: var(--color-primary);
        color: var(--color-grey-20);
        padding: 0 0.2rem;
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
        background-image: url('@openmates/ui/static/icons/github.svg');
        background-size: contain;
        background-repeat: no-repeat;
    }

    .opencollective-icon {
        width: 24px;
        height: 24px;
        background-image: url('@openmates/ui/static/icons/opencollective.svg');
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

    .left-section {
        display: flex;
        align-items: center;
        gap: 1rem;
    }

    .menu-button {
        all: unset;
        cursor: pointer;
        opacity: 0.6;
        transition: opacity 0.2s ease;
    }

    .menu-button:hover {
        opacity: 1;
    }

    .profile-button {
        all: unset;
        cursor: pointer;
        padding: 0.5rem;
        border-radius: 50%;
        transition: background-color 0.2s;
    }

    .profile-button:hover {
        background-color: var(--color-grey-20);
    }
</style>