/**
 * Central configuration file for all external links used across the website
 * This makes it easier to maintain and update links in one place
 */
import { parse } from 'yaml';

// Load shared URL configuration
let sharedUrls: Record<string, any> = { urls: { base: {}, legal: {}, contact: {} } };

// Try to load the shared YAML file
try {
  const yamlModule = import.meta.glob('/../../../../../../shared/config/urls.yml', { eager: true, as: 'raw' });
  const yamlPath = Object.keys(yamlModule)[0];
  if (yamlPath) {
    const yamlContent = yamlModule[yamlPath] as string;
    sharedUrls = parse(yamlContent);
  }
} catch (error) {
  console.error('Failed to load shared URL configuration:', error);
}

// Use contact email from shared config or environment variable
export const contactEmail = import.meta.env.VITE_CONTACT_EMAIL || 
  sharedUrls?.urls?.contact?.email || 'contact@openmates.org';

// Create external links with dynamic email
export const externalLinks = {
  // Social/Community
  discord: sharedUrls?.urls?.contact?.discord || "https://discord.gg/bHtkxZB5cc",
  github: sharedUrls?.urls?.contact?.github || null,

  // Contact
  get email() {
    return `mailto:${contactEmail}`;
  },

  // Legal
  legal: {
    privacyPolicy: sharedUrls?.urls?.legal?.privacy || "/legal/privacy",
    terms: sharedUrls?.urls?.legal?.terms || "/legal/terms",
    imprint: sharedUrls?.urls?.legal?.imprint || "/legal/imprint",
  }
} as const;

// Load base URLs from shared config or environment
export const baseUrls = {
  website: {
    development: import.meta.env.VITE_WEBSITE_URL_DEV || 
      sharedUrls?.urls?.base?.website?.development || 'http://localhost:5173',
    production: import.meta.env.VITE_WEBSITE_URL_PROD || 
      sharedUrls?.urls?.base?.website?.production || 'https://openmates.org'
  },
  webapp: {
    development: import.meta.env.VITE_WEBAPP_URL_DEV || 
      sharedUrls?.urls?.base?.webapp?.development || 'http://localhost:5174',
    production: import.meta.env.VITE_WEBAPP_URL_PROD || 
      sharedUrls?.urls?.base?.webapp?.production || 'https://app.openmates.org'
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
        userGuide_signup_1a: "/docs/userguide/signup/invite-code",
        userGuide_signup_1b: "/docs/userguide/signup/basics",
        userGuide_signup_2: "/docs/userguide/signup/confirm-email",
        userGuide_signup_3: "/docs/userguide/signup/upload-profile-image",
        userGuide_signup_4: "/docs/userguide/signup/2fa",
        userGuide_signup_5: "/docs/userguide/signup/backup-codes",
        userGuide_signup_6: "/docs/userguide/signup/2fa-reminder",
        userGuide_signup_7: "/docs/userguide/signup/settings",
        userGuide_signup_8: "/docs/userguide/signup/mates",
        userGuide_signup_9: "/docs/userguide/signup/pay-per-use",
        userGuide_signup_10_1: "/docs/userguide/signup/limited-refund",
        userGuide_signup_10_2: "/docs/userguide/signup/payment",
        userGuide_settings: "/docs/userguide/settings",
        api: import.meta.env.DEV ? "/docs/api" : null,
        roadmap: import.meta.env.DEV ? "/docs/roadmap" : null,
        designGuidelines: import.meta.env.DEV ? "/docs/designguidelines" : null,
        designSystem: import.meta.env.DEV ? "/docs/designsystem" : null,
        selfhosted: "/docs/selfhosted"
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