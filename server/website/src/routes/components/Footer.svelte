<script lang="ts">
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { externalLinks, routes } from '$lib/config/links';

    // Type definition for footer links
    type FooterLink = {
        href: string;
        text: string;
        external?: boolean;
    };

    // Define footer sections and their links using the centralized config
    const footerSections: {title: string, links: FooterLink[]}[] = [
        {
            title: "Website",
            links: [
                { href: routes.home, text: "For everyone", external: false },
                { href: routes.developers, text: "For developers", external: false }
            ]
        },
        {
            title: "Docs",
            links: [
                { href: routes.docs.userGuide, text: "User guide", external: false },
                { href: routes.docs.api, text: "API docs", external: false },
                { href: routes.docs.roadmap, text: "Roadmap", external: false },
                { href: routes.docs.designGuidelines, text: "Design guidelines", external: false }
            ]
        },
        {
            title: "Legal",
            links: [
                { href: externalLinks.legal.imprint, text: "Imprint", external: false },
                { href: externalLinks.legal.privacyPolicy, text: "Privacy", external: false },
                { href: externalLinks.legal.terms, text: "Terms and conditions", external: false }
            ]
        },
        {
            title: "Contact",
            links: [
                { href: externalLinks.discord, text: "Discord", external: true },
                { href: externalLinks.email, text: "E-Mail", external: true }
            ]
        }
    ];

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
</script>

<footer>
    <div class="footer-content">
        <!-- Logo and Tagline Section -->
        <div class="footer-header">
            <div class="logo">
                <span class="logo-text">Open</span>
                <span class="logo-text highlight">Mates</span>
            </div>
            <div class="tagline">
                <p>Our world needs change.</p>
                <p>And change requires action.</p>
                <p>So, let us take action.</p>
            </div>
        </div>

        <!-- Navigation Sections -->
        <div class="footer-nav">
            {#each footerSections as section}
                <div class="footer-section">
                    <h3>{section.title}</h3>
                    <ul>
                        {#each section.links as link}
                            <li>
                                <a
                                    href={link.href}
                                    class:active={isActive(link.href)}
                                    {...(link.external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
                                    on:click={(e) => handleClick(e, link.href, link.external)}
                                >
                                    {link.text}
                                </a>
                            </li>
                        {/each}
                    </ul>
                </div>
            {/each}
        </div>

        <!-- Made in EU Section -->
        <div class="footer-bottom">
            <p>Made in the EU</p>
            <img src="/images/eu-flag.png" alt="EU Flag" class="eu-flag" />
        </div>
    </div>
</footer>

<style>
    footer {
        background-color: var(--primary-color, #4361ee);
        color: white;
        padding: 4rem 2rem 2rem;
    }

    .footer-content {
        max-width: 1400px;
        margin: 0 auto;
    }

    .footer-header {
        margin-bottom: 3rem;
        text-align: center;
    }

    .logo {
        font-size: 1.5rem;
        font-weight: 600;
        margin-bottom: 1rem;
    }

    .logo-text {
        color: white;
    }

    .logo-text.highlight {
        color: white;
        margin-left: 0.25rem;
    }

    .tagline {
        font-size: 1.2rem;
        line-height: 1.5;
    }

    .tagline p {
        margin: 0;
    }

    .footer-nav {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 2rem;
        margin-bottom: 3rem;
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
    }

    .eu-flag {
        width: 40px;
        height: auto;
        margin-top: 0.5rem;
    }

    @media (max-width: 768px) {
        .footer-nav {
            grid-template-columns: repeat(2, 1fr);
        }
    }

    @media (max-width: 480px) {
        .footer-nav {
            grid-template-columns: 1fr;
        }
    }

    /* Simplify the active link styles */
    .footer-section ul li a.active {
        color: white;
        font-weight: 600;
    }
</style> 