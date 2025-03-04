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
        userGuide: import.meta.env.DEV ? "/docs/userguide" : null,
        userGuide_signup_1a: import.meta.env.DEV ? "/docs/userguide/signup/invite-code" : null,
        userGuide_signup_1b: import.meta.env.DEV ? "/docs/userguide/signup/basics" : null,
        userGuide_signup_2: import.meta.env.DEV ? "/docs/userguide/signup/confirm-email" : null,
        userGuide_signup_3: import.meta.env.DEV ? "/docs/userguide/signup/upload-profile-image" : null,
        userGuide_signup_4: import.meta.env.DEV ? "/docs/userguide/signup/2fa" : null,
        userGuide_signup_5: import.meta.env.DEV ? "/docs/userguide/signup/backup-codes" : null,
        userGuide_signup_6: import.meta.env.DEV ? "/docs/userguide/signup/2fa-reminder" : null,
        userGuide_signup_7: import.meta.env.DEV ? "/docs/userguide/signup/settings" : null,
        userGuide_signup_8: import.meta.env.DEV ? "/docs/userguide/signup/mates" : null,
        userGuide_signup_9: import.meta.env.DEV ? "/docs/userguide/signup/pay-per-use" : null,
        userGuide_signup_10_1: import.meta.env.DEV ? "/docs/userguide/signup/limited-refund" : null,
        userGuide_signup_10_2: import.meta.env.DEV ? "/docs/userguide/signup/payment" : null,
        userGuide_settings: import.meta.env.DEV ? "/docs/userguide/settings" : null,
        api: import.meta.env.DEV ? "/docs/api" : null,
        roadmap: import.meta.env.DEV ? "/docs/roadmap" : null,
        designGuidelines: import.meta.env.DEV ? "/docs/designguidelines" : null,
        designSystem: import.meta.env.DEV ? "/docs/designsystem" : null
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