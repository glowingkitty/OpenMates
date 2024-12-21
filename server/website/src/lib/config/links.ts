/**
 * Central configuration file for all external links used across the website
 * This makes it easier to maintain and update links in one place
 */
export const externalLinks = {
    // Social/Community
    discord: "https://discord.gg/bHtkxZB5cc",
    github: null,

    // Contact
    email: "contact@openmates.com",

    // Legal
    legal: {
        privacyPolicy: "/legal/privacy",
        terms: "/legal/terms",
        imprint: "/legal/imprint",
    }
} as const;

/**
 * Internal route paths used across the website
 * Centralizing these makes it easier to update routes if they change
 */
export const routes = {
    home: "/",
    developers: "/developers",
    docs: {
        main: "/docs",
        userGuide: "/docs/user_guide",
        api: "/docs/api",
        roadmap: "/docs/roadmap",
        designGuidelines: "/docs/design_guidelines",
        designSystem: "/docs/design_system"
    }
} as const;