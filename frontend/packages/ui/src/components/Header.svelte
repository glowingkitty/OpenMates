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
    import { loginInterfaceOpen, introBannerVisible } from '../stores/uiStateStore'; // Import mobile view state and login interface visibility
    import { authStore } from '../stores/authStore'; // Import auth store to check login status
    import { demoMode } from '../stores/demoModeStore';

    // Props using Svelte 5 runes
    let { 
        context = 'website',
        isLoggedIn = false,
        /**
         * When true (docs mode): hamburger is always visible, toggles the docs sidebar,
         * and the right section shows a "Back to chats" link instead of Login/Signup.
         */
        docsMode = false,
        /** Override toggle action for the hamburger button (used in docs mode). */
        onToggleSidebar = undefined as (() => void) | undefined,
        /** Whether the controlled sidebar is currently open (used in docs mode for aria state). */
        isSidebarOpen = false,
    }: {
        context?: 'website' | 'webapp';
        isLoggedIn?: boolean;
        docsMode?: boolean;
        onToggleSidebar?: () => void;
        isSidebarOpen?: boolean;
    } = $props();
    
    // Server edition state - will be fetched on mount
    let serverEdition = $state<string | null>(null);
    let serverEditionLabel = $derived(
        serverEdition === 'self_hosted'
            ? $text('header.self_hosting_edition')
            : serverEdition === 'development' && !$demoMode
              ? $text('header.development_server')
              : $text('signup.version_title')
    );

    let headerDiv: HTMLElement;

    // Simplify the websiteNavItems - remove isTranslationsReady check using Svelte 5 runes
    let websiteNavItems = $derived([
        { href: routes.home, text: $text('navigation.for_all') },
        { href: routes.developers, text: $text('navigation.for_developers') },
        { href: routes.docs.main, text: $text('common.docs') }
    ].filter(item => item.href && isPageVisible(item.href)));

    interface _NavItem {
        href: string;
        text: string;
    }

    let isProjectsRoute = $derived($page.url.pathname.startsWith('/projects'));
    let webappWorkspaceTabs = $derived([
        {
            href: '/',
            testId: 'chats-nav-link',
            label: $text('common.chat'),
            iconClass: 'chat-icon',
            active: !isProjectsRoute,
            disabled: false,
        },
        {
            href: '/projects',
            testId: 'projects-nav-link',
            label: $text('navigation.projects'),
            iconClass: 'project-icon',
            active: isProjectsRoute,
            disabled: false,
        },
        {
            href: '',
            testId: 'workflows-nav-link',
            label: $text('navigation.workflows'),
            iconClass: 'workflow-icon',
            active: false,
            disabled: true,
        },
        {
            href: '',
            testId: 'tasks-nav-link',
            label: $text('navigation.tasks'),
            iconClass: 'task-icon',
            active: false,
            disabled: true,
        },
    ]);

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
    let navItems = $derived(context === 'webapp' ? [] : websiteNavItems);

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
                    // server_edition detection logged for debugging: production | development | self_hosted
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
    let loginButtonText = $derived(isMobile ? $text('signup.sign_up') : `${$text('login.login')} / ${$text('signup.sign_up')}`);

    // Update menu toggle logic to consider the logging out state as well
    const _toggleMenu = () => {
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
            navItems = [];
        } else {
            // Otherwise use website nav items
            navItems = websiteNavItems;
        }
    });

    // Add custom transition function
    function _slideFade(node: HTMLElement, { 
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
                    <!-- In docs mode: always visible, controls docs sidebar via onToggleSidebar -->
                    <!-- In webapp mode: hide when login interface is open, during signup, or when chats panel is open -->
                    <div 
                        class="menu-button-container"
                        class:hidden={(docsMode && isSidebarOpen) || (!docsMode && (context !== 'webapp' || $isInSignupProcess || $loginInterfaceOpen || $panelState.isActivityHistoryOpen))}
                    >
                        <button
                            class="clickable-icon icon_menu"
                            data-testid="sidebar-toggle"
                            onclick={docsMode && onToggleSidebar ? onToggleSidebar : panelState.toggleChats}
                            aria-label={$text('header.toggle_menu')}
                            aria-expanded={docsMode ? isSidebarOpen : $panelState.isActivityHistoryOpen}
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
                            <span class="mobile-logo-icon" aria-hidden="true">
                                <span class="mobile-logo-mate"></span>
                                <span class="mobile-logo-badge"></span>
                                <span class="mobile-logo-ai"></span>
                            </span>
                        </a>
                        {#if serverEdition === 'self_hosted' || serverEdition === 'development'}
                            <div
                                class="server-edition"
                                onclick={handleLogoClick}
                                role="button"
                                tabindex="0"
                                onkeydown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        handleLogoClick(e as unknown as MouseEvent);
                                    }
                                }}
                            >
                                {serverEditionLabel}
                            </div>
                        {:else}
                            <div class="server-edition">{serverEditionLabel}</div>
                        {/if}
                    </div>
                </div>
                  
                {#if showNavLinks && (context !== 'webapp' || isLoggedIn)}
                    <!-- Mobile menu button only shown for website -->
                    {#if context === 'website'}
                        <button 
                            class="mobile-menu-button" 
                            onclick={toggleMobileMenu}
                            aria-label={$text('header.toggle_menu')}
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
                
                <!-- Center section: docs mode shows Docs/Chat tab toggle -->
                {#if docsMode}
                    <div class="docs-tabs">
                        <a href="/docs" class="docs-tab active">{$text('common.docs')}</a>
                        <a href="/" class="docs-tab">{$text('common.chat')}</a>
                    </div>
                {:else if context === 'webapp' && isLoggedIn}
                    <div class="webapp-center-tabs" aria-label="Workspace switcher">
                        {#each webappWorkspaceTabs as item}
                            {#if item.disabled}
                                <button
                                    type="button"
                                    class="workspace-tab"
                                    class:active={item.active}
                                    data-testid={item.testId}
                                    aria-label={item.label}
                                    aria-disabled="true"
                                >
                                    <span class={`workspace-icon ${item.iconClass}`} aria-hidden="true"></span>
                                </button>
                            {:else}
                                <a
                                    href={item.href}
                                    class="workspace-tab"
                                    class:active={item.active}
                                    data-testid={item.testId}
                                    aria-label={item.label}
                                    onclick={(e) => handleClick(e, item.href)}
                                >
                                    <span class={`workspace-icon ${item.iconClass}`} aria-hidden="true"></span>
                                </a>
                            {/if}
                        {/each}
                    </div>
                {/if}

                <!-- Right section: webapp shows Login/Signup when not authenticated -->
                {#if !docsMode}
                    <div
                        class="right-section"
                        class:hidden={context !== 'webapp' || $authStore.isAuthenticated || $demoMode || $loginInterfaceOpen || $introBannerVisible}
                    >
                        {#if !isMobile}
                            <a
                                class="github-repo-button"
                                href="https://github.com/glowingkitty/OpenMates"
                                target="_blank"
                                rel="noopener noreferrer"
                                aria-label="Open OpenMates GitHub repository"
                            >
                                <svg
                                    aria-hidden="true"
                                    viewBox="0 0 24 24"
                                    width="20"
                                    height="20"
                                    fill="currentColor"
                                >
                                    <path d="M12 0C5.37 0 0 5.5 0 12.28c0 5.42 3.44 10.02 8.2 11.65.6.11.82-.27.82-.59 0-.29-.01-1.06-.02-2.08-3.34.74-4.04-1.65-4.04-1.65-.55-1.42-1.34-1.8-1.34-1.8-1.09-.77.08-.76.08-.76 1.2.09 1.84 1.27 1.84 1.27 1.07 1.87 2.81 1.33 3.5 1.02.11-.79.42-1.33.76-1.64-2.66-.31-5.46-1.36-5.46-6.07 0-1.34.47-2.44 1.24-3.3-.12-.31-.54-1.56.12-3.25 0 0 1.01-.33 3.3 1.26A11.2 11.2 0 0 1 12 5.93c1.02.01 2.05.14 3.01.41 2.29-1.59 3.3-1.26 3.3-1.26.66 1.69.24 2.94.12 3.25.77.86 1.24 1.96 1.24 3.3 0 4.72-2.8 5.75-5.48 6.06.43.38.81 1.12.81 2.27 0 1.64-.02 2.96-.02 3.36 0 .33.22.71.83.59C20.57 22.3 24 17.7 24 12.28 24 5.5 18.63 0 12 0Z" />
                                </svg>
                            </a>
                        {/if}
                        <button
                            class="login-signup-button"
                            data-testid="header-login-signup-btn"
                            onclick={(e) => {
                                e.preventDefault();
                                // Dispatch event to open signup interface (shows signup tab by default)
                                window.dispatchEvent(new CustomEvent('openSignupInterface'));
                            }}
                            aria-label={loginButtonText}
                        >
                            {loginButtonText}
                        </button>
                    </div>
                {/if}
            </nav>
        </div>
    {/await}
</header>

<style>
    header {
        z-index: var(--z-index-modal);
        padding: var(--spacing-10) var(--spacing-10) var(--spacing-5);
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
        gap: var(--spacing-4);
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

    .mobile-logo-icon {
        display: none;
        position: relative;
        width: 30px;
        height: 30px;
        flex-shrink: 0;
    }

    .mobile-logo-mate {
        position: absolute;
        inset: 0;
        border-radius: 50%;
        background: var(--gradient-primary, linear-gradient(135deg, var(--color-primary), var(--color-button-primary)));
        box-shadow: 0 3px 8px rgba(0, 0, 0, 0.2);
    }

    .mobile-logo-mate::after {
        content: "";
        position: absolute;
        inset: 6px;
        background: var(--color-grey-0);
        -webkit-mask-image: url('@openmates/ui/static/icons/mate.svg');
        mask-image: url('@openmates/ui/static/icons/mate.svg');
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-position: center;
        mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
    }

    .mobile-logo-badge {
        position: absolute;
        right: -3px;
        bottom: -3px;
        width: 13px;
        height: 13px;
        border-radius: 50%;
        background: var(--color-grey-0);
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.12);
    }

    .mobile-logo-ai {
        position: absolute;
        right: 0;
        bottom: 0;
        width: 8px;
        height: 8px;
        background: var(--color-primary);
        -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
        mask-image: url('@openmates/ui/static/icons/ai.svg');
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-position: center;
        mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
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

    /* RTL: pin the subtitle to the right edge of the logo container and
       right-align the text so it mirrors the LTR layout. */
    :global([dir="rtl"]) .server-edition {
        left: auto;
        right: 4px;
        text-align: right;
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
        transition: opacity var(--duration-normal) var(--easing-default);
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
        transition: opacity var(--duration-normal) var(--easing-default);
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
        z-index: var(--z-index-modal-above);
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
        transition: all var(--duration-slow) var(--easing-default);
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
            z-index: var(--z-index-modal);
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
        transition: gap var(--duration-normal) var(--easing-default); /* Smooth transition for gap when menu button is hidden */
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
        transition: opacity var(--duration-normal) var(--easing-default), visibility var(--duration-normal) var(--easing-default), width var(--duration-normal) var(--easing-default), min-width var(--duration-normal) var(--easing-default);
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
        transition: opacity var(--duration-normal) var(--easing-default);
    }

    .menu-button:hover {
        opacity: 1;
    }

    .right-section {
        position: absolute;
        right: 50px; /* Space for settings menu button */
        top: 50%; /* Center vertically */
        transform: translateY(-50%) translateX(0);
        display: flex;
        align-items: center;
        gap: 0.75rem; /* Add gap between sign in button and language icon */
        transition:
            opacity var(--duration-normal) var(--easing-default),
            visibility var(--duration-normal) var(--easing-default),
            transform var(--duration-normal) var(--easing-default);
        margin-right: var(--spacing-5);
        /* Absolutely positioned so it doesn't affect header height, but we keep it rendered for smooth transitions */
    }

    /* Hide the right section visually but keep it rendered to prevent layout shifts */
    .right-section.hidden {
        opacity: 0;
        visibility: hidden;
        pointer-events: none; /* Prevent interaction when hidden */
        transform: translateY(-50%) translateX(16px);
    }

    .github-repo-button {
        all: unset;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 36px;
        height: 36px;
        color: var(--color-grey-60);
        cursor: pointer;
        transition:
            color var(--duration-normal) var(--easing-default),
            transform var(--duration-normal) var(--easing-default);
    }

    .github-repo-button:hover {
        color: var(--color-grey-80);
        transform: scale(1.05);
    }

    .github-repo-button:active {
        transform: scale(0.98);
    }

    .login-signup-button {
        all: unset;
        padding: var(--spacing-4) var(--spacing-6);
        border-radius: var(--radius-3);
        background-color: var(--color-button-primary);
        color: white;
        cursor: pointer;
        transition: all var(--duration-normal) var(--easing-default);
        white-space: nowrap;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    }

    .login-signup-button:hover {
        transform: scale(1.02);
    }

    .login-signup-button:active {
        background-color: var(--color-button-primary-pressed);
        transform: scale(0.98);
        box-shadow: none;
    }

    /* Docs/Chat tab toggle — centered in header when in docs mode */
    .docs-tabs,
    .webapp-center-tabs {
        display: flex;
        align-items: center;
        gap: var(--spacing-2);
        background-color: var(--color-grey-20);
        border-radius: var(--radius-4);
        padding: 3px;
        /* Center in header using absolute positioning so left/right sections aren't affected */
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
    }

    .docs-tab,
    .workspace-tab {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: var(--spacing-3) var(--spacing-8);
        border-radius: var(--radius-3);
        text-decoration: none;
        color: var(--color-font-secondary);
        font-size: 0.8125rem;
        font-weight: 500;
        transition: all var(--duration-fast) var(--easing-default);
        white-space: nowrap;
    }

    .workspace-tab {
        appearance: none;
        width: 44px;
        height: 44px;
        min-width: 44px;
        min-height: 44px;
        flex: 0 0 44px;
        padding: 0;
        border: 0;
        background: transparent;
        cursor: pointer;
        box-sizing: border-box;
        font: inherit;
        margin: 0;
    }

    .workspace-tab[aria-disabled="true"] {
        cursor: default;
        opacity: 0.7;
    }

    .docs-tab:hover,
    .workspace-tab:hover {
        color: var(--color-font-primary);
    }

    .docs-tab.active,
    .workspace-tab.active {
        background-color: color-mix(in srgb, var(--color-grey-60) 30%, transparent);
        color: var(--color-font-primary);
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }

    .workspace-icon {
        width: 20px;
        height: 20px;
        background: var(--color-primary);
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-position: center;
        mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
    }

    .chat-icon {
        -webkit-mask-image: url('@openmates/ui/static/icons/chat.svg');
        mask-image: url('@openmates/ui/static/icons/chat.svg');
    }

    .project-icon {
        -webkit-mask-image: url('@openmates/ui/static/icons/project.svg');
        mask-image: url('@openmates/ui/static/icons/project.svg');
    }

    .workflow-icon {
        -webkit-mask-image: url('@openmates/ui/static/icons/workflow.svg');
        mask-image: url('@openmates/ui/static/icons/workflow.svg');
    }

    .task-icon {
        -webkit-mask-image: url('@openmates/ui/static/icons/task.svg');
        mask-image: url('@openmates/ui/static/icons/task.svg');
    }

    @media (max-width: 600px) {
        nav.webapp {
            min-height: 36px;
        }

        .logo-link :global(strong) {
            display: none;
        }

        .mobile-logo-icon {
            display: block;
        }

        .server-edition {
            display: none;
        }

        .webapp-center-tabs {
            position: absolute;
            left: 50%;
            transform: translateX(-50%);
            gap: 1px;
            padding: 2px;
        }

        .docs-tabs {
            position: static;
            transform: none;
        }

        .workspace-tab {
            width: 44px;
            height: 44px;
            min-width: 44px;
            min-height: 44px;
            flex-basis: 44px;
        }

        .workspace-icon {
            width: 18px;
            height: 18px;
        }
    }
</style>
