<script lang="ts">
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { externalLinks, routes } from '../config/links';
    import { isPageVisible } from '../config/pages';
    import { waitLocale } from 'svelte-i18n';
    import { onMount } from 'svelte';
    import { isMenuOpen } from '../stores/menuState';
    import { text } from '@repo/ui';
    import { isInSignupProcess, isLoggingOut } from '../stores/signupState'; // Import the signup state and logging out state
    import { panelState } from '../stores/panelStateStore'; // Import panel state store
    import { isMobileView, loginInterfaceOpen } from '../stores/uiStateStore'; // Import mobile view state and login interface visibility
    import { authStore } from '../stores/authStore'; // Import auth store to check login status

    // Props using Svelte 5 runes
    let { 
        context = 'website',
        isLoggedIn = false
    }: {
        context?: 'website' | 'webapp';
        isLoggedIn?: boolean;
    } = $props();
    
    // Server edition state - will be fetched on mount
    let serverEdition = $state<string | null>(null);

    let headerDiv: HTMLElement;

    // Simplify the websiteNavItems - remove isTranslationsReady check using Svelte 5 runes
    let websiteNavItems = $derived([
        { href: routes.home, text: $text('navigation.for_all.text') },
        { href: routes.developers, text: $text('navigation.for_developers.text') },
        { href: routes.docs.main, text: $text('navigation.docs.text') }
    ].filter(item => item.href && isPageVisible(item.href)));

    interface NavItem {
        href: string;
        text: string;
    }

    // Update the webAppNavItems based on login state using Svelte 5 runes
    let webAppNavItems = $derived(isLoggedIn ? [
        // { href: '/app/chat', text: $t('navigation.chat.text') },
        // { href: '/app/projects', text: $t('navigation.projects.text') },
        // { href: '/app/workflows', text: $t('navigation.workflows.text') }
    ] : []);

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

    // Use appropriate nav items based on context using Svelte 5 runes
    let navItems = $derived(context === 'webapp' ? webAppNavItems : websiteNavItems);

    // Only show navigation section if we have at least 2 nav items using Svelte 5 runes
    let showNavLinks = $derived(navItems?.length >= 2);
    
    // Show social links only if nav section is visible and we have social links using Svelte 5 runes
    let showSocialLinks = $derived(showNavLinks && socialLinks?.length > 0);
    
    // Show social section only for website and if we have social links using Svelte 5 runes
    let showSocialSection = $derived(context === 'website' && showSocialLinks);

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

    /**
     * Handle logo click - behavior depends on server edition:
     * - If self_hosted or development: open GitHub repo in new tab
     * - Otherwise: if toggle menu is visible, trigger it; otherwise navigate to home
     */
    const handleLogoClick = (event: MouseEvent) => {
        // Check if this is a self-hosted or development server edition
        if (serverEdition === 'self_hosted' || serverEdition === 'development') {
            // Open GitHub repo in new tab
            event.preventDefault();
            window.open(externalLinks.github, '_blank', 'noopener,noreferrer');
            return;
        }

        // For regular edition, check if toggle menu is visible
        const isMenuButtonVisible = context === 'webapp' && 
            !$isInSignupProcess && 
            !$loginInterfaceOpen && 
            !$panelState.isActivityHistoryOpen;

        if (isMenuButtonVisible) {
            // Trigger toggle menu
            event.preventDefault();
            panelState.toggleChats();
        } else {
            // Default behavior: navigate to home
            handleClick(event, '/');
        }
    }

    // Add state for mobile menu using Svelte 5 runes
    let isMobileMenuOpen = $state(false);
    
    // Function to toggle mobile menu
    const toggleMobileMenu = () => {
        isMobileMenuOpen = !isMobileMenuOpen;
    };

    // Close mobile menu when route changes using Svelte 5 runes
    $effect(() => {
        if ($page.url.pathname) {
            isMobileMenuOpen = false;
        }
    });

    // Add mobile breakpoint check
    let isMobile = $state(false);

    onMount(() => {
        const checkMobile = () => {
            isMobile = window.innerWidth < 730;
        };

        checkMobile();
        window.addEventListener('resize', checkMobile);
        
        // Fetch server status to display server edition (async, fire and forget)
        (async () => {
            try {
                const { getApiEndpoint } = await import('../config/api');
                const response = await fetch(getApiEndpoint('/v1/settings/server-status'));
                if (response.ok) {
                    const status = await response.json();
                    // Use server_edition from request-based validation (includes "development" for dev subdomains)
                    // server_edition can be: "production" | "development" | "self_hosted"
                    serverEdition = status.server_edition || null;
                    console.log(`[Header] Server edition: ${serverEdition}, domain: ${status.domain || 'localhost'}, is_self_hosted: ${status.is_self_hosted}`);
                }
            } catch (error) {
                console.error('[Header] Error fetching server status:', error);
            }
        })();

        return () => {
            window.removeEventListener('resize', checkMobile);
        };
    });

    // Derive button text based on viewport size
    let loginButtonText = $derived(isMobile ? $text('signup.sign_up.text') : `${$text('login.login.text')} / ${$text('signup.sign_up.text')}`);

    // Update menu toggle logic to consider the logging out state as well
    const toggleMenu = () => {
        if (isLoggedIn && !$isInSignupProcess && !$isLoggingOut) {
            isMenuOpen.set(!$isMenuOpen);
        }
    };

    // Add reactive statement to update nav items when auth state changes using Svelte 5 runes
    $effect(() => {
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
    });

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
                    <!-- Menu button container - always rendered to maintain header height -->
                    <!-- Show menu button for both authenticated and non-authenticated users (to access demo chats) -->
                    <!-- Hide menu button visually when login interface is open, during signup, or when chats panel is open -->
                    <div 
                        class="menu-button-container"
                        class:hidden={context !== 'webapp' || $isInSignupProcess || $loginInterfaceOpen || $panelState.isActivityHistoryOpen}
                    >
                        <button
                            class="clickable-icon icon_menu"
                            onclick={panelState.toggleChats}
                            aria-label={$text('header.toggle_menu.text')}
                        ></button>
                    </div>
                    <div class="logo-container">
                        <a
                            href={serverEdition === 'self_hosted' || serverEdition === 'development' ? externalLinks.github : '/'}
                            class="logo-link"
                            onclick={handleLogoClick}
                            target={serverEdition === 'self_hosted' || serverEdition === 'development' ? '_blank' : undefined}
                            rel={serverEdition === 'self_hosted' || serverEdition === 'development' ? 'noopener noreferrer' : undefined}
                        >
                            <strong><mark>Open</mark><span style="color: var(--color-grey-100);">Mates</span></strong>
                        </a>
                        {#if serverEdition === 'self_hosted'}
                            <div 
                                class="server-edition"
                                onclick={handleLogoClick}
                                role="button"
                                tabindex="0"
                                onkeydown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        handleLogoClick(e as any);
                                    }
                                }}
                            >
                                {$text('header.self_hosting_edition.text')}
                            </div>
                        {:else if serverEdition === 'development'}
                            <div 
                                class="server-edition"
                                onclick={handleLogoClick}
                                role="button"
                                tabindex="0"
                                onkeydown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        handleLogoClick(e as any);
                                    }
                                }}
                            >
                                {$text('header.development_server.text')}
                            </div>
                        {/if}
                    </div>
                </div>
                  
                {#if showNavLinks && (context !== 'webapp' || isLoggedIn)}
                    <!-- Mobile menu button only shown for website -->
                    {#if context === 'website'}
                        <button 
                            class="mobile-menu-button" 
                            onclick={toggleMobileMenu}
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
                                onclick={(e) => handleClick(e, item.href)}
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
                
                <!-- Login button for non-authenticated users in webapp context -->
                <!-- Opens login interface which also provides signup option -->
                <!-- Always render to maintain header height, but hide visually when not needed -->
                <div
                    class="right-section"
                    class:hidden={context !== 'webapp' || $authStore.isAuthenticated || $loginInterfaceOpen}
                >
                    <button
                        class="login-signup-button"
                        onclick={(e) => {
                            e.preventDefault();
                            // Dispatch event to open login interface
                            window.dispatchEvent(new CustomEvent('openLoginInterface'));
                        }}
                        aria-label={loginButtonText}
                    >
                        {loginButtonText}
                    </button>
                </div>
            </nav>
        </div>
    {/await}
</header>

<style>
    header {
        z-index: 1000;
        padding: 20px 20px 10px;
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        display: flex;
        align-items: center;
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
        align-items: center; /* Keep items centered vertically */
        max-width: 1400px;
        margin: 0 auto;
        position: relative; /* Enable absolute positioning for child elements */
    }

    /* Remove max-width constraint for webapp navigation */
    nav.webapp {
        max-width: none;
    }

    .left-section {
        flex-shrink: 0;
    }

    /* Container for logo and server edition text */
    /* Logo container uses relative positioning to allow absolute positioning of server edition text */
    /* Absolutely positioned text will not affect header height */
    .logo-container {
        position: relative;
        display: flex;
        align-items: center;
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
    
    /* Server edition text displayed under the logo - absolutely positioned to not affect header height */
    .server-edition {
        position: absolute;
        left: 0;
        font-size: 0.75rem;
        color: var(--color-grey-60);
        font-weight: 400;
        text-align: left;
        line-height: 1.2;
        cursor: pointer;
        white-space: nowrap;
        /* Add padding to make clickable area larger */
        padding: 0.125rem 0;
        left: 4px;
        top: 24px;
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

    .left-section {
        display: flex;
        align-items: center;
        gap: 1rem;
        transition: gap 0.2s ease; /* Smooth transition for gap when menu button is hidden */
    }

    /* When menu button is hidden, collapse the gap smoothly */
    .left-section:has(.menu-button-container.hidden) {
        gap: 0;
    }

    /* Menu button container - maintains header height when visible */
    .menu-button-container {
        display: flex;
        align-items: center;
        width: 25px; /* Match the button width */
        height: 25px; /* Match the button height */
        min-width: 25px; /* Prevent shrinking below button width when visible */
        overflow: hidden; /* Clip button when width collapses */
        transition: opacity 0.2s ease, visibility 0.2s ease, width 0.2s ease, min-width 0.2s ease;
    }

    /* Hide the menu button visually but keep it in layout flow to maintain header height */
    /* Collapse width to 0 to allow logo to smoothly move left */
    .menu-button-container.hidden {
        opacity: 0;
        visibility: hidden;
        pointer-events: none; /* Prevent interaction when hidden */
        width: 0;
        min-width: 0; /* Allow full collapse */
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

        /* Mobile-specific styles for left section and logo */
        .left-section {
            gap: 0.5rem;
        }

        .logo-link {
            font-size: 0.9rem;
        }

        .server-edition {
            top: 18px;
        }
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

    .right-section {
        position: absolute;
        right: 50px; /* Space for settings menu button */
        top: 50%; /* Center vertically */
        transform: translateY(-50%); /* Center vertically */
        display: flex;
        align-items: center;
        gap: 0.75rem; /* Add gap between sign in button and language icon */
        transition: opacity 0.2s ease, visibility 0.2s ease;
        /* Absolutely positioned so it doesn't affect header height, but we keep it rendered for smooth transitions */
    }

    /* Hide the right section visually but keep it rendered to prevent layout shifts */
    .right-section.hidden {
        opacity: 0;
        visibility: hidden;
        pointer-events: none; /* Prevent interaction when hidden */
    }

    .login-signup-button {
        all: unset;
        padding: 8px 12px;
        border-radius: 8px;
        background-color: var(--color-button-primary);
        cursor: pointer;
        transition: all 0.2s ease;
        white-space: nowrap;
    }

    .login-signup-button:hover {
        transform: scale(1.02);
    }

    .login-signup-button:active {
        background-color: var(--color-button-primary-pressed);
        transform: scale(0.98);
    }
</style>