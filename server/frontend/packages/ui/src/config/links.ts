/**
 * Central configuration file for all external links used across the website
 * This makes it easier to maintain and update links in one place
 */
export const externalLinks = {
    // Social/Community
    discord: "https://discord.gg/bHtkxZB5cc",
    github: null,

    // Contact
    email: "mailto:contact@openmates.org",

    // Legal
    legal: {
        privacyPolicy: "/legal/privacy",
        terms: "/legal/terms",
        imprint: "/legal/imprint",
    }
} as const;

// Add base URL configuration first
export const baseUrls = {
    website: {
        development: 'http://localhost:5173', // Default Vite port for website
        production: 'https://openmates.org'
    },
    webapp: {
        development: 'http://localhost:5174', // Separate port for web app
        production: 'https://app.openmates.org'
    }
} as const;

// Add API URL configuration
export const apiUrls = {
    development: 'http://localhost:8000',
    production: 'https://api.openmates.org'
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

// Helper to get API URL
export function getApiUrl(): string {
    const isDev = import.meta.env.DEV;
    return isDev ? apiUrls.development : apiUrls.production;
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