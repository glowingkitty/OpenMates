<script lang="ts">
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { externalLinks, routes, getWebsiteUrl } from '../config/links';
    import { isPageVisible } from '../config/pages';
    import { text } from '@repo/ui';
    import { locale, locales } from 'svelte-i18n';
    import { browser } from '$app/environment';
    import { waitLocale } from 'svelte-i18n';
    import { loadMetaTags, getMetaTags } from '../config/meta';
    import { authStore } from '../stores/authStore';
    import { isInSignupProcess } from '../stores/signupState';
    import { isSignupSettingsStep } from '../stores/signupState';
    import { currentSignupStep } from '../stores/signupState';

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
        { code: 'es', name: 'Español' },
        { code: 'fr', name: 'Français' },
        { code: 'zh', name: '中文' },
        { code: 'ja', name: '日本語' }
        // Add more languages as needed
    ];

    // Define footer sections and their links using the centralized config
    const footerSections = [
        {
            title_key: "footer.sections.website",
            title: "Website",
            links: [
                { href: routes.home, text: "For all of us", translation_key: "footer.sections.for_everyone", external: false },
                // Only include developers link if it exists
                ...(routes.developers ? [{ 
                    href: routes.developers, 
                    text: "For developers", 
                    translation_key: "footer.sections.for_developers", 
                    external: false 
                }] : []),
                // Only include webapp link if it exists
                ...(routes.webapp ? [{ 
                    href: routes.webapp, 
                    text: "Web App", 
                    translation_key: "footer.sections.webapp", 
                    external: true 
                }] : [])
            ]
        },
        {
            title_key: "footer.sections.docs",
            title: "Docs",
            links: [
                // Only include doc links if they exist
                ...(routes.docs.userGuide ? [{ 
                    href: routes.docs.userGuide, 
                    text: "User guide", 
                    translation_key: "footer.sections.user_guide", 
                    external: false 
                }] : []),
                ...(routes.docs.api ? [{ 
                    href: routes.docs.api, 
                    text: "API docs", 
                    translation_key: "footer.sections.api_docs", 
                    external: false 
                }] : []),
                // ... similar pattern for other doc links
            ].filter(Boolean) // Remove any null/undefined entries
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
            link.external || (link.href && isPageVisible(link.href))
        )
    })).filter(section => section.links.length > 0); // Remove sections with no visible links

    // Add prop for meta key
    export let metaKey: string = 'for_all_of_us'; // default to home page
    export let context: 'website' | 'webapp' = 'website';

    // Update footer sections to use full URLs in webapp context
    $: processedFooterSections = footerSections.map(section => ({
        ...section,
        links: section.links.map(link => ({
            ...link,
            // Only transform internal links (non-external) in webapp context
            href: context === 'webapp' && !link.external ? 
                getWebsiteUrl(link.href) : link.href
        }))
    }));

    // Get the processed home URL based on context
    $: homeUrl = context === 'webapp' ? getWebsiteUrl(routes.home) : routes.home;

    // Update click handler to handle external URLs
    const handleClick = (event: MouseEvent, href: string) => {
        event.preventDefault();
        
        // Handle mailto: links
        if (href.startsWith('mailto:')) {
            window.location.href = href;
            return;
        }
        
        // If we're in webapp context or it's an external link, use window.location
        if (context === 'webapp' || href.startsWith('http')) {
            window.location.href = href;
            return;
        }

        // Otherwise use goto for internal navigation in website context
        goto(href);
    };

    // Update isActive check to handle full URLs
    const isActive = (href: string): boolean => {
        if (context === 'webapp') {
            // Never highlight links in webapp context
            return false;
        }
        // Original logic for website context
        const currentPath = $page.url.pathname.replace(/\/$/, '');
        const linkPath = href.replace(/\/$/, '');
        return currentPath === linkPath;
    };

    // Initialize locale from browser language
    const initializeLocale = () => {
        if (browser) {
            const savedLocale = localStorage.getItem('preferredLanguage');
            if (savedLocale && supportedLanguages.some(lang => lang.code === savedLocale)) {
                // Only use saved locale if explicitly set
                locale.set(savedLocale);
            } else {
                // Use browser language
                const browserLang = navigator.language.split('-')[0];
                if (supportedLanguages.some(lang => lang.code === browserLang)) {
                    locale.set(browserLang);
                } else {
                    locale.set('en');
                }
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
        
        // Store preference in localStorage
        localStorage.setItem('preferredLanguage', newLocale);
        
        try {
            // Set new locale and wait for translations to load
            await locale.set(newLocale);
            await waitLocale();

            // Update HTML lang attribute
            document.documentElement.setAttribute('lang', newLocale);

            // Reload meta tags with new language
            await loadMetaTags();

            // Get updated meta tags for the current page
            const metaTags = getMetaTags(metaKey);

            // Update meta tags
            document.title = metaTags.title;
            
            const metaDescription = document.querySelector('meta[name="description"]');
            if (metaDescription) {
                metaDescription.setAttribute('content', metaTags.description);
            }

            const metaKeywords = document.querySelector('meta[name="keywords"]');
            if (metaKeywords) {
                metaKeywords.setAttribute('content', metaTags.keywords.join(', '));
            }

            // Update OpenGraph meta tags if they exist
            const ogTitle = document.querySelector('meta[property="og:title"]');
            if (ogTitle) {
                ogTitle.setAttribute('content', metaTags.title);
            }

            const ogDescription = document.querySelector('meta[property="og:description"]');
            if (ogDescription) {
                ogDescription.setAttribute('content', metaTags.description);
            }

            const ogLocale = document.querySelector('meta[property="og:locale"]');
            if (ogLocale) {
                ogLocale.setAttribute('content', `${newLocale}_${newLocale.toUpperCase()}`);
            }

        } catch (error) {
            console.error('Error changing language:', error);
        }
    };

    // Show footer when not authenticated OR in signup steps 1-6
    $: showFooter = !$authStore.isAuthenticated || 
                   ($isInSignupProcess && $currentSignupStep < 7);
</script>

{#if showFooter}
<footer>
    <div class="footer-content">
        <!-- Logo and Tagline Section -->
        <div class="footer-header">
            <div class="header-content">
                <div class="logo mobile-order-2">
                    <a 
                        href={homeUrl} 
                        on:click={(e) => handleClick(e, homeUrl)}
                    >
                        <span class="logo-text">Open</span>
                        <span class="logo-text highlight">Mates</span>
                    </a>
                </div>
                <div class="tagline mobile-order-1">
                    {@html $text('footer.tagline.text')}
                </div>
                <div class="logo invisible mobile-order-3"></div>
            </div>
        </div>

        <!-- Navigation Sections -->
        <div class="footer-nav">
            {#each processedFooterSections as section}
                <div class="footer-section">
                    <h3>{@html $text(section.title_key + '.text')}</h3>
                    <ul>
                        {#each section.links as link}
                            <li>
                                <a
                                    href={link.href}
                                    class:active={isActive(link.href)}
                                    on:click={(e) => handleClick(e, link.href)}
                                    {...link.external ? { target: '_blank', rel: 'noopener noreferrer' } : {}}
                                >
                                    {$text(link.translation_key + '.text')}
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
                value={localStorage.getItem('preferredLanguage') || navigator.language.split('-')[0]} 
                on:change={handleLanguageChange}
                aria-label={$text('footer.language_selector.label.text')}
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
            <p>{@html $text('footer.made_in_eu.text')}</p>
            <div class="flag icon_eu"></div>
        </div>
    </div>
</footer>
{/if}

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
