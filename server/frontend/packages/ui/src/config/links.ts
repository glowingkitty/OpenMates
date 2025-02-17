/**
 * Central configuration file for all external links used across the website
 * This makes it easier to maintain and update links in one place
 */

// Update contact email from environment
export const contactEmail = import.meta.env.VITE_CONTACT_EMAIL || 'contact@openmates.org';

// Create external links with dynamic email
export const externalLinks = {
    // Social/Community
    discord: "https://discord.gg/bHtkxZB5cc",
    github: null,

    // Contact
    get email() {
        return `mailto:${contactEmail}`;
    },

    // Legal
    legal: {
        privacyPolicy: "/legal/privacy",
        terms: "/legal/terms",
        imprint: "/legal/imprint",
    }
} as const;

// Load base URLs from environment
export const baseUrls = {
    website: {
        development: import.meta.env.VITE_WEBSITE_URL_DEV || 'http://localhost:5173',
        production: import.meta.env.VITE_WEBSITE_URL_PROD || 'https://openmates.org'
    },
    webapp: {
        development: import.meta.env.VITE_WEBAPP_URL_DEV || 'http://localhost:5174',
        production: import.meta.env.VITE_WEBAPP_URL_PROD || 'https://app.openmates.org'
    }
} as const;

// Helper to get correct base URL
export function getBaseUrl(app: 'website' | 'webapp'): string {
    const isDev = import.meta.env.DEV;
    return isDev ? baseUrls[app].development : baseUrls[app].production;
}

// Helper to get webapp URL
export function getWebappUrl(): string {
    return getBaseUrl('webapp');
}

export const routes = {
    home: "/",
    developers: import.meta.env.DEV ? "/developers" : null,
    webapp: import.meta.env.DEV ? getBaseUrl('webapp') : null,
    docs: {
        main: import.meta.env.DEV ? "/docs" : null,
        userGuide: import.meta.env.DEV ? "/docs/user_guide" : null,
        api: import.meta.env.DEV ? "/docs/api" : null,
        roadmap: import.meta.env.DEV ? "/docs/roadmap" : null,
        designGuidelines: import.meta.env.DEV ? "/docs/design_guidelines" : null,
        designSystem: import.meta.env.DEV ? "/docs/design_system" : null
    }
} as const;

export const privacyPolicyLinks = {
    vercel: 'https://vercel.com/legal/privacy-policy',
    discord: 'https://discord.com/privacy'
} as const;

// Update routes to include full URLs when needed
export function getWebsiteUrl(path: string): string {
    return `${getBaseUrl('website')}${path}`;
}