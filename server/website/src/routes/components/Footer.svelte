<script lang="ts">
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { externalLinks, routes } from '$lib/config/links';
    import { isPageVisible } from '$lib/config/pages';
    import { _ } from 'svelte-i18n';
    import { locale, locales } from 'svelte-i18n';
    import { browser } from '$app/environment';
    import { waitLocale } from 'svelte-i18n';

    // Type definition for footer links
    type FooterLink = {
        href: string;
        text: string;
        translation_key: string;
        external?: boolean;
    };

    // Type definition for supported languages
    type Language = {
        code: string;
        name: string;
    };

    // Define supported languages
    const supportedLanguages: Language[] = [
        { code: 'en', name: 'English' },
        { code: 'de', name: 'Deutsch' },
        { code: 'ja', name: '日本語' },
        { code: 'es', name: 'Español' }
        // Add more languages as needed
    ];

    // Define footer sections and their links using the centralized config
    const footerSections: {title: string, title_key: string, links: FooterLink[]}[] = [
        {
            title_key: "footer.sections.website",
            title: "Website",
            links: [
                { href: routes.home, text: "For all of us", translation_key: "footer.sections.for_everyone", external: false },
                { href: routes.developers, text: "For developers", translation_key: "footer.sections.for_developers", external: false }
            ]
        },
        {
            title_key: "footer.sections.docs",
            title: "Docs",
            links: [
                { href: routes.docs.userGuide, text: "User guide", translation_key: "footer.sections.user_guide", external: false },
                { href: routes.docs.api, text: "API docs", translation_key: "footer.sections.api_docs", external: false },
                { href: routes.docs.roadmap, text: "Roadmap", translation_key: "footer.sections.roadmap", external: false },
                { href: routes.docs.designGuidelines, text: "Design guidelines", translation_key: "footer.sections.design_guidelines", external: false }
            ]
        },
        {
            title_key: "footer.sections.legal",
            title: "Legal",
            links: [
                { href: externalLinks.legal.imprint, text: "Imprint", translation_key: "footer.sections.imprint", external: false },
                { href: externalLinks.legal.privacyPolicy, text: "Privacy", translation_key: "footer.sections.privacy", external: false },
                { href: externalLinks.legal.terms, text: "Terms and conditions", translation_key: "footer.sections.terms_and_conditions", external: false }
            ]
        },
        {
            title_key: "footer.sections.contact",
            title: "Contact",
            links: [
                { href: externalLinks.discord, text: "Discord", translation_key: "footer.sections.discord", external: true },
                { href: externalLinks.email, text: "E-Mail", translation_key: "footer.sections.email", external: true }
            ]
        }
    ].map(section => ({
        ...section,
        links: section.links.filter(link => 
            link.external || isPageVisible(link.href)
        )
    })).filter(section => section.links.length > 0); // Remove sections with no visible links

    // Handle click events
    const handleClick = async (event: MouseEvent, path: string, external: boolean = false) => {
        if (external || event.ctrlKey || event.metaKey || event.button === 1) {
            return;
        }
        event.preventDefault();
        await goto(path, { replaceState: false });
    }

    // Helper function to check if a link is active
    const isActive = (href: string): boolean => {
        // Remove trailing slashes for consistent comparison
        const currentPath = $page.url.pathname.replace(/\/$/, '');
        const linkPath = href.replace(/\/$/, '');
        return currentPath === linkPath;
    };

    // Initialize locale from localStorage or default to 'en'
    const initializeLocale = () => {
        if (browser) {  // Only access localStorage in browser environment
            const savedLocale = localStorage.getItem('preferredLanguage');
            if (savedLocale && supportedLanguages.some(lang => lang.code === savedLocale)) {
                locale.set(savedLocale);
            }
        }
    };

    // Call initialization when the component mounts
    initializeLocale();

    // Handle language change
    const handleLanguageChange = async (event: Event) => {
        if (!browser) return;
        
        const select = event.target as HTMLSelectElement;
        const newLocale = select.value;
        
        // Set new locale and wait for translations to load
        await locale.set(newLocale);
        await waitLocale();
        
        localStorage.setItem('preferredLanguage', newLocale);
        
        // Force page reload to ensure all components update
        window.location.reload();
    };
</script>

<footer>
    <div class="footer-content">
        <!-- Logo and Tagline Section -->
        <div class="footer-header">
            <div class="header-content">
                <div class="logo mobile-order-2">
                    <a 
                        href={routes.home} 
                        on:click={(e) => handleClick(e, routes.home)}
                    >
                        <span class="logo-text">Open</span>
                        <span class="logo-text highlight">Mates</span>
                    </a>
                </div>
                <div class="tagline mobile-order-1">
                    <p>{$_('footer.tagline.line1.text')}</p>
                    <p>{$_('footer.tagline.line2.text')}</p>
                    <p>{$_('footer.tagline.line3.text')}</p>
                </div>
                <div class="logo invisible mobile-order-3"></div>
            </div>
        </div>

        <!-- Navigation Sections -->
        <div class="footer-nav">
            {#each footerSections as section}
                <div class="footer-section">
                    <h3>{$_(section.title_key + '.text')}</h3>
                    <ul>
                        {#each section.links as link}
                            <li>
                                <a
                                    href={link.href}
                                    class:active={isActive(link.href)}
                                    {...(link.external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
                                    on:click={(e) => handleClick(e, link.href, link.external)}
                                >
                                    {$_(link.translation_key + '.text')}
                                </a>
                            </li>
                        {/each}
                    </ul>
                </div>
            {/each}
        </div>

        <!-- Add language selector before the Made in EU Section -->
        <div class="language-selector">
            <select 
                value={$locale} 
                on:change={handleLanguageChange}
                aria-label={$_('footer.language_selector.label.text')}
            >
                {#each supportedLanguages as language}
                    <option value={language.code}>
                        {language.name}
                    </option>
                {/each}
            </select>
        </div>

        <!-- Made in EU Section -->
        <div class="footer-bottom">
            <p>{$_('footer.made_in_eu.text')}</p>
            <div class="flag icon_eu"></div>
        </div>
    </div>
</footer>

<style>
    footer {
        background: var(--color-footer);
        color: white;
        padding: 4rem 2rem 2rem;
        margin-top: 40px;
    }

    @media (max-width: 600px) {
        footer {
            padding: 2rem 1rem 1rem;
            margin-top: 20px;
        }
    }

    .footer-content {
        max-width: 1400px;
        margin: 0 auto;
    }

    .footer-header {
        margin-bottom: 3rem;
        width: 100%;
        max-width: 1400px;
        margin: 0 auto;
    }

    .header-content {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 2rem;
        padding: 0 2rem;
        margin-bottom: 20px;
    }

    .logo {
        min-width: 150px;
        font-size: 1.5rem;
        font-weight: 600;
        display: flex;
        align-items: center;
    }

    .logo-text {
        color: white;
    }

    .logo-text.highlight {
        color: #1C1C1C;
        margin-left: 0.25rem;
    }

    .tagline {
        text-align: center;
        flex: 1;
    }

    .tagline p {
        margin: 0;
    }

    .footer-nav {
        max-width: 1400px;
        margin: 0 auto;
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 2rem;
        margin-bottom: 3rem;
        padding: 0 2rem;
    }

    @media (max-width: 600px) {
        .footer-nav {
            grid-template-columns: repeat(2, 1fr);
        }
    }

    .footer-section h3 {
        font-size: 1.2rem;
        margin-bottom: 1rem;
        color: white;
    }

    .footer-section ul {
        list-style: none;
        padding: 0;
        margin: 0;
    }

    .footer-section ul li {
        margin-bottom: 0.5rem;
        padding-left: 0;
    }

    .footer-section ul li a {
        color: rgba(255, 255, 255, 0.7);
        text-decoration: none;
        transition: color 0.2s ease;
    }

    .footer-section ul li a:hover {
        color: white;
    }

    .footer-bottom {
        text-align: center;
        padding-top: 2rem;
        border-top: 1px solid rgba(255, 255, 255, 0.2);
        display: flex;
        align-items: center;
        justify-content: center;
        flex-direction: column;
    }

    .eu-flag {
        width: 40px;
        height: auto;
        margin-top: 0.5rem;
    }

    /* Simplify the active link styles */
    .footer-section ul li a.active {
        color: white;
        font-weight: 600;
    }

    .invisible {
        visibility: hidden;
    }

    /* Add styles for the logo link */
    .logo a {
        text-decoration: none;
        display: flex;
        align-items: center;
        font-size: inherit;
        font-weight: inherit;
        min-width: inherit;
    }

    @media (max-width: 600px) {
        .header-content {
            flex-direction: column;
            text-align: center;
        }

        .mobile-order-1 {
            order: 1;
        }

        .mobile-order-2 {
            order: 2;
        }

        .mobile-order-3 {
            display: none; /* Hide the invisible spacer on mobile */
        }

        .logo {
            justify-content: center;
        }
    }

    .language-selector {
        text-align: center;
        margin-bottom: 2rem;
    }

    .language-selector select {
        background-color: transparent;
        color: white;
        padding: 0.5rem 1rem;
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 4px;
        cursor: pointer;
        font-size: 0.9rem;
    }

    .language-selector select option {
        background-color: var(--color-footer);
        color: white;
    }

    .language-selector select:hover {
        border-color: rgba(255, 255, 255, 0.4);
    }

    .language-selector select:focus {
        outline: none;
        border-color: white;
    }
</style> 