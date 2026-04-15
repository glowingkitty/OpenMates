/**
 * Central configuration file for all external links used across the website
 * This makes it easier to maintain and update links in one place
 */
import { parse } from "yaml";

// Load shared URL configuration
interface SharedUrls {
  urls: {
    base: Record<string, { development: string; production: string }>;
    legal: Record<string, string>;
    contact: Record<string, string>;
  };
}
let sharedUrls: SharedUrls = {
  urls: { base: {}, legal: {}, contact: {} },
};

// Try to load the shared YAML file
try {
  const yamlModule = import.meta.glob(
    "/../../../../../../shared/config/urls.yml",
    { eager: true, query: "?raw", import: "default" },
  );
  const yamlPath = Object.keys(yamlModule)[0];
  if (yamlPath) {
    const yamlContent = yamlModule[yamlPath] as string;
    sharedUrls = parse(yamlContent);
  }
} catch (error) {
  console.error("Failed to load shared URL configuration:", error);
}

// Use contact email from shared config or environment variable
export const contactEmail =
  import.meta.env.VITE_CONTACT_EMAIL ||
  sharedUrls?.urls?.contact?.email ||
  "contact@openmates.org";

// Create external links with dynamic email
export const externalLinks = {
  // Social/Community
  discord:
    sharedUrls?.urls?.contact?.discord || "https://discord.gg/bHtkxZB5cc",
  instagram:
    sharedUrls?.urls?.contact?.instagram ||
    "https://instagram.com/openmates_official",
  github:
    sharedUrls?.urls?.contact?.github ||
    "https://github.com/glowingkitty/OpenMates",
  mastodon:
    sharedUrls?.urls?.contact?.mastodon || "https://mastodon.social/@OpenMates",
  meetup:
    sharedUrls?.urls?.contact?.meetup ||
    "https://www.meetup.com/openmates-meetup-group/",
  pixelfed:
    sharedUrls?.urls?.contact?.pixelfed || "https://pixelfed.social/@openmates",
  signal:
    sharedUrls?.urls?.contact?.signal ||
    "https://signal.group/#CjQKIOlYZ63Rz7sibDjQ680wO1a0NcKxtfL0in2BA6Yvbr82EhDNd6GJYtaPfHn4BFcsETQq",
  // element: sharedUrls?.urls?.contact?.element || "????",

  // Contact
  get email() {
    return `mailto:${contactEmail}`;
  },

  // Legal
  legal: {
    privacyPolicy: sharedUrls?.urls?.legal?.privacy || "/legal/privacy",
    terms: sharedUrls?.urls?.legal?.terms || "/legal/terms",
    imprint: sharedUrls?.urls?.legal?.imprint || "/legal/imprint",
  },
} as const;

// Load base URLs from shared config or environment
export const baseUrls = {
  website: {
    development:
      import.meta.env.VITE_WEBSITE_URL_DEV ||
      sharedUrls?.urls?.base?.website?.development ||
      "http://localhost:5173",
    production:
      import.meta.env.VITE_WEBSITE_URL_PROD ||
      sharedUrls?.urls?.base?.website?.production ||
      "https://openmates.org",
  },
  webapp: {
    development:
      import.meta.env.VITE_WEBAPP_URL_DEV ||
      sharedUrls?.urls?.base?.webapp?.development ||
      "http://localhost:5173",
    production:
      import.meta.env.VITE_WEBAPP_URL_PROD ||
      sharedUrls?.urls?.base?.webapp?.production ||
      "https://openmates.org",
  },
} as const;

// Helper to get correct base URL
export function getBaseUrl(app: "website" | "webapp"): string {
  const isDev = import.meta.env.DEV;
  return isDev ? baseUrls[app].development : baseUrls[app].production;
}

export const routes = {
  home: "/",
  developers: import.meta.env.DEV ? "/developers" : null,
  webapp: import.meta.env.DEV ? getBaseUrl("webapp") : null,
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
    selfhosted: "/docs/selfhosted",
  },
} as const;

// Privacy-policy links for every third-party provider referenced in the
// privacy policy. Grouped to mirror shared/docs/privacy_policy.yml
// provider_groups (Group A-J). When adding a new provider to a skill or
// app.yml, add its privacy-policy link here AND update:
//   - shared/docs/privacy_policy.yml
//   - frontend/packages/ui/src/i18n/sources/legal/privacy.yml
//   - frontend/packages/ui/src/legal/buildLegalContent.ts
export const privacyPolicyLinks = {
  // Group A — Always active
  vercel: "https://vercel.com/legal/privacy-policy",
  hetzner: "https://www.hetzner.com/legal/privacy-policy",
  brevo: "https://www.brevo.com/legal/privacypolicy",
  ipApi: "https://members.ip-api.com/privacy-policy",
  sightengine: "https://sightengine.com/policies/privacy",
  apiVideo: "https://api.video/privacy-policy/", // verified 2026-04-14

  // Group B — Payments
  stripe: "https://stripe.com/privacy",
  polar: "https://polar.sh/legal/privacy-policy",
  revolutBusiness: "https://www.revolut.com/en-LT/legal/privacy/", // Revolut Bank UAB (Lithuania) — verified 2026-04-14

  // Group C — AI models
  mistral: "https://legal.mistral.ai/terms/privacy-policy", // moved to legal.mistral.ai subdomain — verified 2026-04-14
  aws: "https://aws.amazon.com/privacy/",
  anthropic: "https://www.anthropic.com/legal/privacy",
  openai: "https://openai.com/policies/privacy-policy",
  openrouter: "https://openrouter.ai/privacy",
  cerebras: "https://www.cerebras.ai/privacy-policy",
  google: "https://policies.google.com/privacy",
  googleVertexMaas: "https://cloud.google.com/terms/cloud-privacy-notice",
  together: "https://www.together.ai/privacy",
  groq: "https://groq.com/privacy-policy",

  // Group D — Image generation
  fal: "https://fal.ai/legal/privacy-policy", // verified 2026-04-14
  recraft: "https://www.recraft.ai/privacy", // verified 2026-04-14

  // Group E — Web, search, content retrieval
  brave: "https://brave.com/privacy/",
  firecrawl: "https://www.firecrawl.dev/privacy-policy",
  webshare: "https://www.webshare.io/privacy-policy",
  googleMaps: "https://policies.google.com/privacy",

  // Group F — Travel
  serpapi: "https://serpapi.com/legal#privacy-policy", // embedded in legal page — verified 2026-04-14
  flightradar24: "https://www.flightradar24.com/terms-and-conditions",

  // Group G — Events
  meetup: "https://www.meetup.com/privacy/",
  luma: "https://lu.ma/privacy",
  residentAdvisor: "https://ra.co/about/privacy",

  // Group H — Health
  doctolib: "https://www.doctolib.de/terms/privacy",
  jameda: "https://www.jameda.de/datenschutz/",

  // Group I — Shopping
  rewe: "https://www.rewe.de/datenschutz/",
  amazon: "https://www.amazon.com/privacy",

  // Group J — Community
  discord: "https://discord.com/privacy",
} as const;

// Update routes to include full URLs when needed
export function getWebsiteUrl(path: string): string {
  return `${getBaseUrl("website")}${path}`;
}
