/**
 * Central configuration file for all external links used across the website
 * This makes it easier to maintain and update links in one place
 */
export const externalLinks = {
    // Social/Community
    discord: "https://discord.gg/bHtkxZB5cc",
    github: null,

    // Contact
    email: "mailto:contact@openmates.com",

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
    developers: "/developers",
    webapp: getBaseUrl('webapp'), // Use getBaseUrl directly instead of getWebappUrl
    docs: {
        main: "/docs",
        userGuide: "/docs/user_guide",
        api: "/docs/api",
        roadmap: "/docs/roadmap",
        designGuidelines: "/docs/design_guidelines",
        designSystem: "/docs/design_system"
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