# Web App Refactor TODO

## Overview

This document tracks the refactoring of the web app to combine the informative website and chat app into a single unified experience with demo chats for non-authenticated users. The app will be fully static, SEO-optimized, near-instant loading, and work as a Progressive Web App (PWA).

**Reference Documents:**

- [web_app.md](../architecture/web-app.md) - Target architecture
- [onboarding.md](../user-guide/onboarding.md) - Related onboarding features

**Key Requirements:**

- ✅ Static SvelteKit build using `adapter-static`
- ✅ SEO optimized with prerendered content, meta tags, JSON-LD schema
- ✅ Near-instant loading with pre-rendered demo chats
- ✅ Progressive enhancement: show demo chats → detect auth → swap to user chats
- ✅ Offline-ready & installable PWA
- ✅ Core Web Vitals optimized (LCP, TTI, CLS, FCP)

---

## Phase 0: SvelteKit Static Setup & PWA Foundation

### 0.1 Migrate to Static Adapter

- [ ] Install `@sveltejs/adapter-static`
  ```bash
  npm install -D @sveltejs/adapter-static
  ```
- [ ] Update `svelte.config.js`

  ```javascript
  import adapter from "@sveltejs/adapter-static";

  export default {
    kit: {
      adapter: adapter({
        pages: "build",
        assets: "build",
        fallback: "index.html", // SPA fallback for client-side routing
        precompress: true, // Compress for production
        strict: true,
      }),
      prerender: {
        default: true,
        entries: [
          "/",
          "/chat/welcome",
          "/chat/what-makes-different",
          "/chat/october-2025-updates",
          "/chat/example-learn-something",
          "/chat/example-power-of-apps",
          "/chat/example-personalized-privacy",
          "/chat/developers",
          "/chat/stay-up-to-date",
          "/settings",
          "/privacy",
          "/terms",
        ],
        handleMissingId: "warn",
      },
    },
  };
  ```

- [ ] Add `+layout.ts` to enable SPA mode for authenticated routes
  ```typescript
  export const ssr = false; // Disable SSR for dynamic user content
  export const prerender = true; // But prerender static content
  ```

### 0.2 Install PWA Support

- [ ] Install `@vite-pwa/sveltekit`
  ```bash
  npm install -D @vite-pwa/sveltekit
  ```
- [ ] Configure `vite.config.ts` with PWA plugin

  ```typescript
  import { sveltekit } from "@sveltejs/kit/vite";
  import { SvelteKitPWA } from "@vite-pwa/sveltekit";
  import { defineConfig } from "vite";

  export default defineConfig({
    plugins: [
      sveltekit(),
      SvelteKitPWA({
        srcDir: "./src",
        mode: "production",
        strategies: "generateSW",
        manifest: {
          name: "OpenMates - Your AI Team",
          short_name: "OpenMates",
          description:
            "Digital teammates with Apps for everyday tasks and learning",
          theme_color: "#your-theme-color",
          background_color: "#ffffff",
          display: "standalone",
          scope: "/",
          start_url: "/",
          orientation: "portrait-primary",
          icons: [
            {
              src: "/icons/icon-72x72.png",
              sizes: "72x72",
              type: "image/png",
              purpose: "any maskable",
            },
            {
              src: "/icons/icon-96x96.png",
              sizes: "96x96",
              type: "image/png",
              purpose: "any maskable",
            },
            {
              src: "/icons/icon-128x128.png",
              sizes: "128x128",
              type: "image/png",
              purpose: "any maskable",
            },
            {
              src: "/icons/icon-144x144.png",
              sizes: "144x144",
              type: "image/png",
              purpose: "any maskable",
            },
            {
              src: "/icons/icon-152x152.png",
              sizes: "152x152",
              type: "image/png",
              purpose: "any maskable",
            },
            {
              src: "/icons/icon-192x192.png",
              sizes: "192x192",
              type: "image/png",
              purpose: "any maskable",
            },
            {
              src: "/icons/icon-384x384.png",
              sizes: "384x384",
              type: "image/png",
              purpose: "any maskable",
            },
            {
              src: "/icons/icon-512x512.png",
              sizes: "512x512",
              type: "image/png",
              purpose: "any maskable",
            },
          ],
        },
        workbox: {
          globPatterns: ["**/*.{js,css,html,ico,png,svg,webp,woff,woff2}"],
          runtimeCaching: [
            {
              urlPattern: /^https:\/\/api\.openmates\.org\/.*/i,
              handler: "NetworkFirst",
              options: {
                cacheName: "api-cache",
                expiration: {
                  maxEntries: 100,
                  maxAgeSeconds: 60 * 60, // 1 hour
                },
              },
            },
            {
              urlPattern: /^https:\/\/.*\.(?:png|jpg|jpeg|svg|gif|webp)$/,
              handler: "CacheFirst",
              options: {
                cacheName: "image-cache",
                expiration: {
                  maxEntries: 100,
                  maxAgeSeconds: 60 * 60 * 24 * 30, // 30 days
                },
              },
            },
          ],
        },
        devOptions: {
          enabled: true,
          type: "module",
        },
      }),
    ],
  });
  ```

- [ ] Create PWA icons in required sizes (72, 96, 128, 144, 152, 192, 384, 512)
- [ ] Test PWA installability on mobile and desktop
- [ ] Add PWA install prompt component (optional)

### 0.3 Performance Optimization Setup

- [ ] Configure Vite build optimizations in `vite.config.ts`
  ```typescript
  export default defineConfig({
    build: {
      target: "es2020",
      cssCodeSplit: true,
      minify: "terser",
      terserOptions: {
        compress: {
          drop_console: true,
          drop_debugger: true,
        },
      },
      rollupOptions: {
        output: {
          manualChunks: {
            "svelte-vendor": ["svelte", "svelte/transition", "svelte/easing"],
            "ui-components": [
              "./src/lib/components/ActiveChat.svelte",
              "./src/lib/components/Chats.svelte",
              "./src/lib/components/Settings.svelte",
            ],
          },
        },
      },
    },
  });
  ```
- [ ] Enable code splitting for routes
- [ ] Add lazy loading for non-critical components
- [ ] Set up asset optimization (images, fonts)
- [ ] Configure CDN deployment (Cloudflare Pages or Netlify)

---

## Phase 1: Demo Chats Infrastructure (SEO-First)

### 1.1 Create Demo Chat System

- [ ] Create `/frontend/packages/ui/src/demo_chats/` directory structure
- [ ] Create `demo_chats/types.ts` with DemoChat interface

  ```typescript
  export interface DemoChat {
    chat_id: string; // Unique ID
    slug: string; // URL-friendly slug
    title: string; // SEO title
    description: string; // SEO description
    keywords: string[]; // SEO keywords
    messages: DemoMessage[];
    metadata: {
      category: string;
      featured: boolean;
      order: number;
      lastUpdated: string;
    };
  }

  export interface DemoMessage {
    id: string;
    role: "user" | "assistant";
    content: string; // Markdown content
    timestamp: string;
    metadata?: {
      apps_used?: string[];
      has_video?: boolean;
      video_url?: string;
    };
  }
  ```

- [ ] Create `demo_chats/data/` directory for chat content
  - [ ] `welcome.ts` - "Welcome to OpenMates!" chat
  - [ ] `what-makes-different.ts` - "What makes OpenMates different?"
  - [ ] `october-2025-updates.ts` - "October 2025: New features & changes"
  - [ ] `example-learn-something.ts` - "Example: Learn something new"
  - [ ] `example-power-of-apps.ts` - "Example: The power of apps"
  - [ ] `example-personalized-privacy.ts` - "Example: Personalized, but privacy preserving"
  - [ ] `developers.ts` - "OpenMates for developers"
  - [ ] `stay-up-to-date.ts` - "Stay up to date & contribute"
- [ ] Create `demo_chats/index.ts` to export all demo chats
  ```typescript
  export { DEMO_CHATS, getDemoChatBySlug, getDemoChatById } from "./data";
  export type { DemoChat, DemoMessage } from "./types";
  ```
- [ ] Create `demo_chats/store.ts` for demo chat state management

  ```typescript
  import { writable, derived } from "svelte/store";
  import type { DemoChat } from "./types";

  export const demoChatStore = writable<DemoChat[]>([]);
  export const activeDemoChatStore = writable<DemoChat | null>(null);
  export const isDemoMode = derived(
    activeDemoChatStore,
    ($activeDemo) => $activeDemo !== null,
  );
  ```

### 1.2 Demo Chat Content Creation

- [ ] Write welcome message introducing OpenMates (use content from web_app.md lines 33-40)
  - [ ] Include animated greeting message
  - [ ] Add quick feature overview
  - [ ] Link to other demo chats
- [ ] Write "What makes OpenMates different?" content (use web_app.md lines 42-76)
  - [ ] Cover Mates feature
  - [ ] Cover Apps feature
  - [ ] Cover Privacy features
  - [ ] Cover Accessibility features
  - [ ] Add links to example chats
- [ ] Create "October 2025 updates" from changelog
  - [ ] Fetch latest changes from GitHub
  - [ ] Format as assistant message
  - [ ] Include links to PRs/issues
- [ ] Create "Learn something new" example
  - [ ] Show multi-turn conversation
  - [ ] Demonstrate learning flow
- [ ] Create "Power of apps" example
  - [ ] Show video transcript app usage
  - [ ] Demonstrate web research app
  - [ ] Show fact-checking workflow
- [ ] Create "Personalized privacy" example
  - [ ] Show memory/preferences usage
  - [ ] Demonstrate privacy features
  - [ ] Show trip planning with personal data
- [ ] Create "For developers" content
  - [ ] List developer features
  - [ ] Add links to GitHub, docs
  - [ ] Link to Signal dev group
- [ ] Create "Stay up to date" content
  - [ ] Add all social media links
  - [ ] Link to Signal, Discord, Meetup, Luma
  - [ ] Link to Instagram, YouTube, Mastodon, Pixelfed
- [ ] Add embedded YouTube clips where needed
  - [ ] Create YouTube embed component
  - [ ] Add lazy loading for videos
- [ ] Ensure all content is SEO-friendly
  - [ ] Use semantic HTML
  - [ ] Add proper headings hierarchy
  - [ ] Include internal links

### 1.3 Demo Chat Rendering

- [ ] Update `ActiveChat.svelte` to support demo chat mode
  - [ ] Add `isDemoMode` state
  - [ ] Modify to render demo chats without authentication
  - [ ] Disable message input in demo mode
  - [ ] Show "Signup to send" button instead of regular send button
  - [ ] Ensure demo content is in initial HTML (no hydration delay)
- [ ] Update `ChatHistory.svelte` to render demo messages
  - [ ] Ensure demo messages display correctly
  - [ ] Handle assistant message animations appropriately
  - [ ] Optimize rendering performance
- [ ] Update `MessageInput.svelte` to show signup button
  - [ ] Replace "Send" button with "Signup to send" when not authenticated
  - [ ] Save draft message when signup button is clicked
  - [ ] Store draft in localStorage with encryption
  - [ ] Restore draft after signup completion

---

## Phase 2: Non-Authenticated User Experience (Progressive Enhancement)

### 2.1 Update Main Page Layout

- [ ] Create `+page.server.ts` for SSR demo chat data

  ```typescript
  import { DEMO_CHATS } from "$lib/demo_chats";

  export const prerender = true;

  export async function load() {
    return {
      demoChats: DEMO_CHATS,
      defaultChat: DEMO_CHATS.find((c) => c.slug === "welcome"),
    };
  }
  ```

- [ ] Update `+page.svelte` to implement progressive enhancement

  ```svelte
  <script lang="ts">
    import { onMount } from 'svelte';
    import { authStore } from '$lib/stores/authStore';

    export let data; // SSR data with demo chats

    let displayChats = data.demoChats;
    let activeChat = data.defaultChat;

    onMount(async () => {
      // Check authentication state
      if ($authStore.isAuthenticated) {
        // Instantly swap to user chats (no loading state)
        const userChats = await loadUserChats();
        displayChats = userChats;
        activeChat = getLastOpenedChat(userChats);
      }
      // If not authenticated, continue showing demo chats
    });
  </script>
  ```

- [ ] Implement seamless swap from demo to user chats
  - [ ] No loading spinner or transition
  - [ ] Instant replacement of chat list
  - [ ] Preserve scroll position if possible
- [ ] Pre-select "Welcome to OpenMates!" chat on first load
  - [ ] Trigger welcome message animation on load
  - [ ] Only animate on first visit (use localStorage flag)

### 2.2 Update Chats.svelte for Demo Support

- [ ] Display demo chats in list with proper styling
  - [ ] Add visual indicator for demo chats (subtle badge)
  - [ ] Use different styling for demo vs real chats
  - [ ] Support clicking demo chats to view them
- [ ] Keep demo chats after signup (with deletion option)
  - [ ] Merge demo chats with user chats
  - [ ] Add "Delete all demo chats" option
- [ ] Optimize list rendering performance
  - [ ] Use virtual scrolling for large lists
  - [ ] Lazy load chat previews

### 2.3 Welcome Message Animation

- [ ] Create animated message appearance for welcome chat
  - [ ] Simulate typing effect for first message (CSS-only if possible)
  - [ ] Show assistant avatar and typing indicator
  - [ ] Smooth scroll to show new message
  - [ ] Ensure animation only plays on first visit (localStorage flag)
- [ ] Make animation optional/skippable
  - [ ] Add "Skip animation" button
  - [ ] Respect prefers-reduced-motion

### 2.4 Progressive Enhancement Strategy

- [ ] Ensure demo chats are in initial HTML (SSR)
  - [ ] No "loading" state for unauthenticated users
  - [ ] Instant first paint with demo content
- [ ] Add authentication check in onMount()
  - [ ] Check for auth token/session
  - [ ] If authenticated → fetch user chats
  - [ ] Seamlessly replace demo chats with user chats
- [ ] Handle auth state changes reactively
  - [ ] Listen for login events
  - [ ] Update chat list immediately on auth change
- [ ] Optimize for perceived performance
  - [ ] Preload critical resources
  - [ ] Use resource hints (preconnect, prefetch)

---

## Phase 3: SEO Optimization (Core Web Vitals Focus)

### 3.1 Meta Tags & Structured Data

- [ ] Create `+page.svelte` meta tags

  ```svelte
  <svelte:head>
    <title>OpenMates - Your AI Team for Learning & Tasks</title>
    <meta name="description" content="Meet your digital teammates. AI experts with Apps for everyday tasks, learning, and work. Privacy-first, accessible, and built for everyone." />
    <meta name="keywords" content="AI assistant, chatbot, learning tool, task automation, privacy-first AI" />

    <!-- Open Graph -->
    <meta property="og:type" content="website" />
    <meta property="og:title" content="OpenMates - Your AI Team" />
    <meta property="og:description" content="Digital teammates with Apps for everyday tasks and learning" />
    <meta property="og:image" content="/og-image.png" />
    <meta property="og:url" content="https://openmates.org" />

    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="OpenMates - Your AI Team" />
    <meta name="twitter:description" content="Digital teammates with Apps for everyday tasks and learning" />
    <meta name="twitter:image" content="/og-image.png" />

    <!-- JSON-LD Structured Data -->
    {@html structuredData}
  </svelte:head>
  ```

- [ ] Create JSON-LD structured data
  ```typescript
  const structuredData = `
  {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "name": "OpenMates",
    "applicationCategory": "ProductivityApplication",
    "offers": {
      "@type": "Offer",
      "price": "0",
      "priceCurrency": "USD"
    },
    "operatingSystem": "Web, iOS, Android",
    "description": "AI-powered digital teammates with Apps for learning and task automation",
    "aggregateRating": {
      "@type": "AggregateRating",
      "ratingValue": "4.8",
      "ratingCount": "1200"
    }
  }
  `;
  ```
- [ ] Add meta tags for each demo chat route
  - [ ] Unique title for each chat
  - [ ] Descriptive meta description
  - [ ] Relevant keywords
  - [ ] Unique OG image for social sharing

### 3.2 Prerender Demo Chat Routes

- [ ] Create `/chat/[slug]/+page.server.ts`

  ```typescript
  import { getDemoChatBySlug } from "$lib/demo_chats";
  import { error } from "@sveltejs/kit";

  export const prerender = true;

  export async function load({ params }) {
    const demoChat = getDemoChatBySlug(params.slug);

    if (!demoChat) {
      throw error(404, "Demo chat not found");
    }

    return {
      demoChat,
      seo: {
        title: demoChat.title,
        description: demoChat.description,
        keywords: demoChat.keywords.join(", "),
      },
    };
  }
  ```

- [ ] Create `/chat/[slug]/+page.svelte`

  ```svelte
  <script lang="ts">
    export let data;

    $: ({ demoChat, seo } = data);
  </script>

  <svelte:head>
    <title>{seo.title} | OpenMates</title>
    <meta name="description" content={seo.description} />
    <meta name="keywords" content={seo.keywords} />
    <!-- Additional meta tags -->
  </svelte:head>

  <ActiveChat chat={demoChat} demoMode={true} />
  ```

- [ ] Ensure all demo chat content is in initial HTML
  - [ ] No client-side hydration required for demo content
  - [ ] Optimize for LCP (Largest Contentful Paint)

### 3.3 Generate Sitemap

- [ ] Create `sitemap.xml` generation script

  ```typescript
  // src/routes/sitemap.xml/+server.ts
  import { DEMO_CHATS } from "$lib/demo_chats";

  export const prerender = true;

  export async function GET() {
    const pages = [
      "/",
      "/settings",
      "/privacy",
      "/terms",
      ...DEMO_CHATS.map((chat) => `/chat/${chat.slug}`),
    ];

    const sitemap = `<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      ${pages
        .map(
          (page) => `
      <url>
        <loc>https://openmates.org${page}</loc>
        <lastmod>${new Date().toISOString()}</lastmod>
        <changefreq>weekly</changefreq>
        <priority>${page === "/" ? "1.0" : "0.8"}</priority>
      </url>
    `,
        )
        .join("")}
    </urlset>`;

    return new Response(sitemap, {
      headers: {
        "Content-Type": "application/xml",
        "Cache-Control": "max-age=3600",
      },
    });
  }
  ```

- [ ] Create `robots.txt`

  ```typescript
  // src/routes/robots.txt/+server.ts
  export const prerender = true;

  export async function GET() {
    return new Response(
      `
      User-agent: *
      Allow: /
      Sitemap: https://openmates.org/sitemap.xml
    `,
      {
        headers: {
          "Content-Type": "text/plain",
        },
      },
    );
  }
  ```

- [ ] Submit sitemap to Google Search Console
- [ ] Submit sitemap to Bing Webmaster Tools

### 3.4 Core Web Vitals Optimization

- [ ] Optimize Largest Contentful Paint (LCP)
  - [ ] Ensure demo chat content loads immediately
  - [ ] Preload critical fonts and images
  - [ ] Use optimized image formats (WebP, AVIF)
  - [ ] Target: LCP < 2.5s
- [ ] Optimize First Input Delay (FID) / Interaction to Next Paint (INP)
  - [ ] Minimize JavaScript execution time
  - [ ] Use code splitting and lazy loading
  - [ ] Defer non-critical scripts
  - [ ] Target: INP < 200ms
- [ ] Optimize Cumulative Layout Shift (CLS)
  - [ ] Reserve space for images (use aspect-ratio)
  - [ ] Avoid injecting content above existing content
  - [ ] Use font-display: swap for custom fonts
  - [ ] Target: CLS < 0.1
- [ ] Optimize First Contentful Paint (FCP)
  - [ ] Inline critical CSS
  - [ ] Minimize render-blocking resources
  - [ ] Use preconnect for external resources
  - [ ] Target: FCP < 1.8s
- [ ] Optimize Time to First Byte (TTFB)
  - [ ] Use CDN for static assets
  - [ ] Enable HTTP/3
  - [ ] Optimize server response time
  - [ ] Target: TTFB < 800ms

### 3.5 Image Optimization

- [ ] Convert images to modern formats (WebP, AVIF)
- [ ] Generate responsive images with srcset
- [ ] Implement lazy loading for below-fold images
- [ ] Add loading="eager" for above-fold images
- [ ] Optimize icon assets (use SVG sprites)
- [ ] Create optimized Open Graph images

### 3.6 Font Optimization

- [ ] Use system fonts as fallback
- [ ] Subset custom fonts to reduce size
- [ ] Use font-display: swap
- [ ] Preload critical font files
- [ ] Consider using variable fonts

---

## Phase 4: Signup Flow Integration

### 4.1 Preserve Demo Chats After Signup

- [ ] Update signup completion handler
  - [ ] Keep demo chats after successful signup
  - [ ] Add assistant message: "Thanks for signing up! If you don't want to see the example chats anymore, you can right click & delete them - or ask me to delete them."
  - [ ] Store flag indicating user has seen welcome message
  - [ ] Merge demo chats with user's new chat list
- [ ] Update chat deletion to support demo chats
  - [ ] Allow right-click deletion of demo chats
  - [ ] Add "Delete all demo chats" option in settings
  - [ ] Support AI-assisted deletion via chat commands
  - [ ] Confirm before deleting all demos

### 4.2 Draft Message Preservation

- [ ] Implement draft message storage during signup
  - [ ] Save draft when "Signup to send" is clicked
  - [ ] Store draft in localStorage (encrypted if contains sensitive data)
  - [ ] Associate draft with specific chat ID
  - [ ] Add timestamp to draft
- [ ] Restore draft after signup
  - [ ] Load draft message after authentication
  - [ ] Focus message input with draft content
  - [ ] Clear draft after successful send
  - [ ] Show "Continue your message" indicator

### 4.3 Optimize Signup Flow for Performance

- [ ] Lazy load signup form components
- [ ] Split signup steps into separate chunks
- [ ] Prefetch next step in background
- [ ] Minimize signup flow JS bundle size
- [ ] Add loading states for async operations

### 4.4 Move Signup Steps to Settings Menu (Future Phase)

**Note:** This is a major refactor - consider doing in separate phase

- [ ] Analyze current signup flow structure
  - [ ] Document all signup steps from `Signup.svelte`
  - [ ] Map signup steps to settings menu structure
  - [ ] Identify which steps can be optional after initial account creation
- [ ] Create settings-based signup flow
  - [ ] Move profile picture upload to settings
  - [ ] Move preferences to settings
  - [ ] Keep essential security steps in signup (password, 2FA)
  - [ ] Create guided tour through settings after account creation
- [ ] Update `Settings.svelte` to support signup mode
  - [ ] Add `isSignupMode` prop
  - [ ] Show required vs optional settings
  - [ ] Add progress indicator for setup
  - [ ] Add skip/continue navigation

---

## Phase 5: URL Consolidation & Routing

### 5.1 Domain Routing

- [ ] Update DNS/hosting configuration
  - [ ] Make `openmates.org` serve the web app
  - [x] Remove redirect from `openmates.org` to `app.openmates.org` (DONE - app.openmates.org retired)
  - [ ] Set up proper SSL certificates
  - [ ] Configure HTTP → HTTPS redirect
- [ ] Update all internal links
  - [ ] Update navigation links to use `openmates.org`
  - [ ] Update API endpoints configuration
  - [ ] Update OAuth redirect URLs
  - [ ] Update email templates with new URLs
- [ ] Set up redirect rules on old domain
  - [x] Redirect `app.openmates.org` → `openmates.org` (301 permanent) (DONE - app.openmates.org retired)
  - [ ] Preserve query parameters and hash fragments
  - [ ] Maintain for at least 6 months

### 5.2 Deep Linking

- [ ] Implement chat deep linking
  - [ ] Support `/chat/[slug]` URLs for demo chats (prerendered)
  - [ ] Support `/chat/[chat_id]` URLs for user chats (client-side)
  - [ ] Handle routing for shared chat links
  - [ ] Add proper 404 handling for invalid chat IDs
- [ ] Update settings deep linking
  - [ ] Support `/settings/[section]` URLs
  - [ ] Maintain existing `#settings/[path]` hash-based routing for backwards compatibility
  - [ ] Implement smooth transitions between settings sections
- [ ] Add canonical URLs to prevent duplicate content
  - [ ] Set canonical URL for each page
  - [ ] Handle trailing slashes consistently

### 5.3 Client-Side Routing Optimization

- [ ] Use SvelteKit's preloadData for instant navigation
- [ ] Implement route transitions with view transitions API
- [ ] Add loading states for slow connections
- [ ] Prefetch likely next routes on hover
- [ ] Handle browser back/forward navigation smoothly

---

## Phase 6: Offline Support & PWA Features

### 6.1 Service Worker Configuration

- [ ] Configure Workbox for offline caching
  - [ ] Cache demo chat content for offline access
  - [ ] Cache static assets (CSS, JS, images)
  - [ ] Cache API responses with NetworkFirst strategy
  - [ ] Implement cache versioning for updates
- [ ] Add offline fallback page
  - [ ] Design offline UI showing cached chats
  - [ ] Show sync status indicator
  - [ ] Queue messages for sending when online
- [ ] Test offline functionality
  - [ ] Test on Chrome, Firefox, Safari
  - [ ] Test on Android and iOS
  - [ ] Verify cache updates work correctly

### 6.2 Background Sync

- [ ] Implement background sync for pending messages
  - [ ] Queue messages sent while offline
  - [ ] Sync when connection is restored
  - [ ] Show sync status in UI
  - [ ] Handle sync failures gracefully
- [ ] Add periodic background sync for chat updates (if supported)
  - [ ] Fetch new messages in background
  - [ ] Update badge count for new messages
  - [ ] Respect user battery and data settings

### 6.3 Push Notifications (Optional)

- [ ] Request notification permission
- [ ] Register push subscription
- [ ] Handle incoming push notifications
- [ ] Show notification badges
- [ ] Allow customization in settings

### 6.4 App Install Prompt

- [ ] Create custom install prompt UI
  - [ ] Show at appropriate time (not immediately)
  - [ ] Explain benefits of installing
  - [ ] Remember if user dismissed
- [ ] Handle beforeinstallprompt event
- [ ] Track installation analytics
- [ ] Show "Open in app" banner for installed users

---

## Phase 7: Performance Monitoring & Testing

### 7.1 Core Web Vitals Monitoring

- [ ] Set up Lighthouse CI in GitHub Actions
  - [ ] Run on every PR
  - [ ] Set performance budgets
  - [ ] Fail builds that regress performance
- [ ] Add RUM (Real User Monitoring)
  - [ ] Use web-vitals library to measure CWV
  - [ ] Send metrics to analytics
  - [ ] Set up alerts for regressions
- [ ] Monitor key metrics
  - [ ] LCP < 2.5s
  - [ ] FID/INP < 200ms
  - [ ] CLS < 0.1
  - [ ] FCP < 1.8s
  - [ ] TTFB < 800ms

### 7.2 Bundle Size Monitoring

- [ ] Set up bundlesize GitHub Action
- [ ] Set size limits for main chunks
  - [ ] Main bundle < 100KB (gzipped)
  - [ ] Vendor chunk < 150KB (gzipped)
  - [ ] Route chunks < 50KB each (gzipped)
- [ ] Monitor bundle composition
  - [ ] Use webpack-bundle-analyzer
  - [ ] Identify large dependencies
  - [ ] Look for duplicate code

### 7.3 Load Testing

- [ ] Test on slow 3G connection
  - [ ] Throttle to 400Kbps
  - [ ] Measure load time and interactivity
  - [ ] Target: usable in < 5s on 3G
- [ ] Test on different devices
  - [ ] Low-end Android (budget phones)
  - [ ] Mid-range devices
  - [ ] High-end devices
  - [ ] Desktop browsers
- [ ] Test with different cache states
  - [ ] First visit (cold cache)
  - [ ] Repeat visit (warm cache)
  - [ ] After service worker update

### 7.4 SEO Testing

- [ ] Use Google Search Console
  - [ ] Check for indexing issues
  - [ ] Monitor Core Web Vitals
  - [ ] Check mobile usability
  - [ ] Review structured data
- [ ] Use Bing Webmaster Tools
- [ ] Test with SEO tools
  - [ ] Screaming Frog
  - [ ] Ahrefs Site Audit
  - [ ] Semrush
- [ ] Check meta tags and OG images
  - [ ] Test sharing on social media
  - [ ] Verify preview cards look correct

### 7.5 PWA Testing

- [ ] Use Lighthouse PWA audit
  - [ ] Score 100/100 on PWA checklist
  - [ ] Fix any failing criteria
- [ ] Test installation on platforms
  - [ ] Chrome on Android
  - [ ] Safari on iOS
  - [ ] Chrome on desktop
  - [ ] Edge on desktop
- [ ] Test offline functionality
  - [ ] Verify app works offline
  - [ ] Test background sync
  - [ ] Test push notifications

### 7.6 Cross-Browser Testing

- [ ] Test on major browsers
  - [ ] Chrome (latest 2 versions)
  - [ ] Firefox (latest 2 versions)
  - [ ] Safari (latest 2 versions)
  - [ ] Edge (latest version)
- [ ] Test on mobile browsers
  - [ ] Chrome on Android
  - [ ] Safari on iOS
  - [ ] Samsung Internet
- [ ] Check for browser-specific issues
  - [ ] CSS compatibility
  - [ ] JavaScript API support
  - [ ] Service worker support

---

## Phase 8: Deployment & Infrastructure

### 8.1 CDN Setup

- [ ] Choose CDN provider
  - [ ] Option A: Cloudflare Pages (recommended)
    - [ ] Free tier includes unlimited bandwidth
    - [ ] Automatic SSL
    - [ ] Global CDN
    - [ ] GitHub integration
  - [ ] Option B: Netlify
    - [ ] Similar features to Cloudflare Pages
    - [ ] Good developer experience
  - [ ] Option C: Vercel
    - [ ] Excellent SvelteKit support
    - [ ] May have bandwidth limits on free tier
- [ ] Configure CDN
  - [ ] Set up custom domain
  - [ ] Configure SSL certificate
  - [ ] Set cache headers
  - [ ] Enable HTTP/3
  - [ ] Enable Brotli compression
  - [ ] Configure security headers

### 8.2 Build & Deploy Pipeline

- [ ] Set up GitHub Actions for CI/CD

  ```yaml
  # .github/workflows/deploy.yml
  name: Deploy to Production

  on:
    push:
      branches: [main]

  jobs:
    build-and-deploy:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v3

        - name: Setup Node.js
          uses: actions/setup-node@v3
          with:
            node-version: "18"
            cache: "npm"

        - name: Install dependencies
          run: npm ci

        - name: Run tests
          run: npm test

        - name: Build
          run: npm run build

        - name: Run Lighthouse CI
          run: npm run lighthouse

        - name: Deploy to Cloudflare Pages
          uses: cloudflare/wrangler-action@v3
          with:
            apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
  ```

- [ ] Set up preview deployments for PRs
- [ ] Configure environment variables
- [ ] Set up deployment notifications (Slack/Discord)

### 8.3 Monitoring & Analytics

- [ ] Set up error tracking (Sentry)
  - [ ] Track JavaScript errors
  - [ ] Track unhandled promise rejections
  - [ ] Set up error alerts
- [ ] Set up analytics (privacy-friendly)
  - [ ] Consider Plausible or Fathom Analytics
  - [ ] Track page views and navigation
  - [ ] Track signup conversions
  - [ ] Track demo chat engagement
- [ ] Set up uptime monitoring
  - [ ] Use UptimeRobot or similar
  - [ ] Monitor main page and API
  - [ ] Set up alerts for downtime

### 8.4 Security Headers

- [ ] Configure security headers in CDN
  ```
  Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' https://www.youtube.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https://api.openmates.org wss://api.openmates.org; frame-src https://www.youtube.com;
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
  ```
- [ ] Test security headers with securityheaders.com
- [ ] Submit for HSTS preload if applicable

---

## Phase 9: Documentation & Training

### 9.1 User Documentation

- [ ] Update user guide for new onboarding
  - [ ] Document demo chat experience
  - [ ] Update signup flow screenshots
  - [ ] Add PWA installation guide
- [ ] Create video tutorials
  - [ ] Getting started with OpenMates
  - [ ] How to install as PWA
  - [ ] Feature overviews
- [ ] Update FAQ
  - [ ] What are demo chats?
  - [ ] How to delete demo chats?
  - [ ] How to install on mobile?

### 9.2 Developer Documentation

- [ ] Document demo chat system
  - [ ] How to add new demo chats
  - [ ] Demo chat data format
  - [ ] SEO best practices
- [ ] Document architecture changes
  - [ ] Static generation approach
  - [ ] Progressive enhancement strategy
  - [ ] PWA implementation
- [ ] Update contribution guide
  - [ ] How to run locally
  - [ ] How to test changes
  - [ ] Performance requirements

### 9.3 Migration Guide

- [ ] Create guide for existing users
  - [ ] URL changes
  - [ ] New features
  - [ ] PWA installation
- [ ] Create announcement post
  - [ ] Highlight benefits
  - [ ] Explain changes
  - [ ] Provide support resources

---

## Phase 10: Launch & Optimization

### 10.1 Soft Launch

- [ ] Deploy to staging environment
- [ ] Test with beta users
- [ ] Collect feedback
- [ ] Fix critical issues
- [ ] Monitor performance metrics

### 10.2 Production Launch

- [ ] Deploy to production
- [ ] Monitor error rates closely
- [ ] Watch Core Web Vitals in real-time
- [ ] Check SEO indexing
- [ ] Verify PWA installation works
- [ ] Announce launch on social media

### 10.3 Post-Launch Optimization

- [ ] Analyze user behavior
  - [ ] Which demo chats are most popular?
  - [ ] Where do users drop off?
  - [ ] What's the signup conversion rate?
- [ ] A/B test improvements
  - [ ] Different demo chat content
  - [ ] CTA placement
  - [ ] Signup flow variations
- [ ] Optimize based on data
  - [ ] Improve low-performing demo chats
  - [ ] Simplify complex flows
  - [ ] Add missing content

### 10.4 SEO Iteration

- [ ] Monitor search rankings
  - [ ] Track target keywords
  - [ ] Identify ranking opportunities
  - [ ] Create content for long-tail keywords
- [ ] Build backlinks
  - [ ] Reach out to tech blogs
  - [ ] Submit to directories
  - [ ] Engage with AI/tech communities
- [ ] Update content regularly
  - [ ] Keep demo chats current
  - [ ] Add seasonal content
  - [ ] Refresh based on user feedback

---

## Success Metrics

### Key Performance Indicators

#### Performance Metrics

- [ ] Lighthouse Score > 95 (all categories)
- [ ] LCP < 2.5s (target: < 1.5s)
- [ ] FID/INP < 100ms (target: < 50ms)
- [ ] CLS < 0.1 (target: < 0.05)
- [ ] FCP < 1.8s (target: < 1.0s)
- [ ] TTFB < 800ms (target: < 400ms)
- [ ] Bundle size < 100KB (main, gzipped)
- [ ] Time to Interactive < 3.5s

#### SEO Metrics

- [ ] First page ranking for "AI chatbot" within 3 months
- [ ] First page ranking for "OpenMates" within 1 week
- [ ] Organic traffic increase by 300% in 3 months
- [ ] 1000+ monthly organic visitors within 6 months
- [ ] All demo chats indexed within 1 week

#### User Engagement Metrics

- [ ] Bounce rate < 30% (target: < 20%)
- [ ] Time on site > 3 minutes (target: > 5 minutes)
- [ ] > 70% of new users view at least 2 demo chats
- [ ] > 30% of visitors click "Signup to send"
- [ ] Signup conversion rate > 15% (target: > 20%)

#### PWA Metrics

- [ ] PWA install rate > 10% of mobile users
- [ ] Offline visit rate > 5% of total visits
- [ ] Push notification opt-in rate > 30%

#### Technical Metrics

- [ ] Error rate < 0.1%
- [ ] 99.9% uptime
- [ ] API response time < 200ms (p95)
- [ ] Zero console errors on production

---

## Timeline Estimate

**Aggressive Timeline:** 4-5 weeks full-time development
**Conservative Timeline:** 6-8 weeks full-time development

### Week-by-Week Breakdown

#### Week 1: Foundation

- Phase 0: SvelteKit Static Setup & PWA Foundation (3-4 days)
- Phase 1: Demo Chats Infrastructure (2-3 days)

#### Week 2: Content & Enhancement

- Phase 1: Demo Chat Content Creation (2-3 days)
- Phase 2: Non-Authenticated User Experience (2-3 days)

#### Week 3: SEO & Performance

- Phase 3: SEO Optimization (3-4 days)
- Phase 6: Offline Support & PWA Features (1-2 days)

#### Week 4: Integration & Routing

- Phase 4: Signup Flow Integration (2-3 days)
- Phase 5: URL Consolidation & Routing (2 days)

#### Week 5: Testing & Deployment

- Phase 7: Performance Monitoring & Testing (3-4 days)
- Phase 8: Deployment & Infrastructure (1-2 days)

#### Week 6: Documentation & Launch (if needed)

- Phase 9: Documentation & Training (2-3 days)
- Phase 10: Launch & Optimization (ongoing)

### Critical Path

1. ✅ Phase 0 (Foundation) - **MUST BE FIRST**
2. ✅ Phase 1 (Demo Chats) - **BLOCKS Phase 2 & 3**
3. ✅ Phase 2 (User Experience) - **BLOCKS Phase 4**
4. ✅ Phase 3 (SEO) - **CAN BE PARALLEL WITH Phase 2**
5. ✅ Phase 4 (Signup) - **BLOCKS Phase 10**
6. ✅ Phase 5 (Routing) - **CAN BE PARALLEL WITH Phase 4**
7. ✅ Phase 6 (PWA) - **CAN BE PARALLEL WITH Phase 4-5**
8. ✅ Phase 7 (Testing) - **BEFORE Phase 10**
9. ✅ Phase 8 (Deploy) - **BEFORE Phase 10**
10. ✅ Phase 10 (Launch) - **FINAL PHASE**

---

## Current Status

**Last Updated:** 2025-10-29

### Phase Completion Status

- [x] Architecture planning completed
- [x] TODO document created
- [ ] Phase 0: SvelteKit Static & PWA Setup
- [ ] Phase 1: Demo Chats Infrastructure
- [ ] Phase 2: Non-Auth User Experience
- [ ] Phase 3: SEO Optimization
- [ ] Phase 4: Signup Integration
- [ ] Phase 5: URL Consolidation
- [ ] Phase 6: Offline & PWA
- [ ] Phase 7: Testing
- [ ] Phase 8: Deployment
- [ ] Phase 9: Documentation
- [ ] Phase 10: Launch

### Blockers & Risks

- [ ] No current blockers identified
- [ ] Risk: Static adapter may not support all current dynamic features → **Mitigation:** Use hybrid approach (static for public, dynamic for authenticated)
- [ ] Risk: PWA cache strategy may conflict with real-time chat → **Mitigation:** Use NetworkFirst for chat API, cache only UI assets
- [ ] Risk: SEO might be affected during domain transition → **Mitigation:** Use 301 redirects, maintain old domain for 6+ months

---

## Related Files

### Key Files to Modify

- `frontend/apps/web_app/svelte.config.js` - **Add static adapter configuration**
- `frontend/apps/web_app/vite.config.ts` - **Add PWA plugin**
- `frontend/apps/web_app/src/routes/+page.svelte` - Main page with progressive enhancement
- `frontend/apps/web_app/src/routes/+page.server.ts` - **CREATE NEW** - SSR demo chats
- `frontend/apps/web_app/src/routes/+layout.svelte` - SEO meta tags
- `frontend/apps/web_app/src/routes/+layout.ts` - **CREATE NEW** - Layout config
- `frontend/packages/ui/src/components/ActiveChat.svelte` - Demo chat support
- `frontend/packages/ui/src/components/chats/Chats.svelte` - Demo chat list
- `frontend/packages/ui/src/components/signup/Signup.svelte` - Draft preservation
- `frontend/packages/ui/src/components/Settings.svelte` - Future signup integration
- `frontend/packages/ui/src/components/enter_message/MessageInput.svelte` - Signup button

### New Files to Create

#### Demo Chat System

- `frontend/packages/ui/src/demo_chats/types.ts`
- `frontend/packages/ui/src/demo_chats/index.ts`
- `frontend/packages/ui/src/demo_chats/store.ts`
- `frontend/packages/ui/src/demo_chats/data/welcome.ts`
- `frontend/packages/ui/src/demo_chats/data/what-makes-different.ts`
- `frontend/packages/ui/src/demo_chats/data/october-2025-updates.ts`
- `frontend/packages/ui/src/demo_chats/data/example-learn-something.ts`
- `frontend/packages/ui/src/demo_chats/data/example-power-of-apps.ts`
- `frontend/packages/ui/src/demo_chats/data/example-personalized-privacy.ts`
- `frontend/packages/ui/src/demo_chats/data/developers.ts`
- `frontend/packages/ui/src/demo_chats/data/stay-up-to-date.ts`

#### SEO Routes

- `frontend/apps/web_app/src/routes/chat/[slug]/+page.svelte`
- `frontend/apps/web_app/src/routes/chat/[slug]/+page.server.ts`
- `frontend/apps/web_app/src/routes/sitemap.xml/+server.ts`
- `frontend/apps/web_app/src/routes/robots.txt/+server.ts`

#### PWA Assets

- `frontend/apps/web_app/static/manifest.json` (auto-generated by plugin)
- `frontend/apps/web_app/static/icons/icon-72x72.png`
- `frontend/apps/web_app/static/icons/icon-96x96.png`
- `frontend/apps/web_app/static/icons/icon-128x128.png`
- `frontend/apps/web_app/static/icons/icon-144x144.png`
- `frontend/apps/web_app/static/icons/icon-152x152.png`
- `frontend/apps/web_app/static/icons/icon-192x192.png`
- `frontend/apps/web_app/static/icons/icon-384x384.png`
- `frontend/apps/web_app/static/icons/icon-512x512.png`
- `frontend/apps/web_app/static/og-image.png` (Open Graph image)

#### CI/CD

- `.github/workflows/deploy.yml`
- `.github/workflows/lighthouse.yml`
- `lighthouserc.json`

### Configuration Files

- `frontend/apps/web_app/svelte.config.js` - Static adapter + prerender config
- `frontend/apps/web_app/vite.config.ts` - PWA plugin + build optimization
- `frontend/apps/web_app/package.json` - New dependencies
- Domain DNS settings
- SSL certificates
- OAuth configuration
- CDN configuration (Cloudflare Pages / Netlify / Vercel)

---

## Notes & Considerations

### Technical Decisions

#### 1. Static vs Dynamic Rendering

**Decision:** Hybrid approach

- Static for: Demo chats, marketing pages, SEO content
- Dynamic for: User chats, authenticated routes, real-time features
- **Rationale:** Best of both worlds - SEO benefits + dynamic functionality

#### 2. Demo Chat Storage

**Decision:** Static TypeScript files

- Store demo chat content in version-controlled TS files
- Easy to update and review via Git
- Fast loading (bundled with app)
- Can migrate to CMS later if needed
- **Rationale:** Simplicity and performance for MVP

#### 3. PWA Caching Strategy

**Decision:** NetworkFirst for API, CacheFirst for assets

- Chat messages: NetworkFirst (always fresh when online)
- Static assets: CacheFirst (fast loading)
- Demo chats: CacheFirst (never change, fastest load)
- **Rationale:** Balance freshness and performance

#### 4. Progressive Enhancement Approach

**Decision:** Show demo chats immediately, swap to user chats on auth

- No loading spinners for unauthenticated users
- Instant first paint with demo content
- Seamless swap when authenticated
- **Rationale:** Best perceived performance

### Open Questions

1. **Should we version demo chats for cache busting?**
   - Option A: Add version hash to demo chat IDs
   - Option B: Use service worker versioning
   - **Recommendation:** Option B (simpler, automatic)

2. **How to handle demo chat updates after user signup?**
   - Option A: Never update demo chats for existing users
   - Option B: Show update notification
   - **Recommendation:** Option A (avoid confusion)

3. **Should demo chats support markdown/rich content?**
   - **Answer:** Yes, reuse existing message rendering

4. **How to prevent search engines from indexing duplicate content?**
   - **Answer:** Use canonical URLs, proper meta tags, structured data

5. **Should we A/B test demo chat content?**
   - **Answer:** Not in MVP, but plan for it (build flexible system)

6. **How to handle internationalization for demo chats?**
   - **Answer:** Future phase, start with English only

### Dependencies & Requirements

#### NPM Dependencies to Add

```json
{
  "@sveltejs/adapter-static": "^3.0.0",
  "@vite-pwa/sveltekit": "^0.4.0",
  "workbox-window": "^7.0.0",
  "web-vitals": "^3.5.0"
}
```

#### External Services Needed

- CDN: Cloudflare Pages (recommended) or Netlify or Vercel
- Analytics: Plausible or Fathom Analytics (privacy-friendly)
- Error Tracking: Sentry
- Uptime Monitoring: UptimeRobot or Pingdom
- SEO Tools: Google Search Console, Bing Webmaster Tools

#### Infrastructure Requirements

- Domain: `openmates.org` (already owned)
- SSL Certificate: Auto via CDN
- HTTP/3 Support: Via CDN
- Global CDN: Via CDN provider
- No dedicated server needed (fully static)

### Content Requirements

#### Demo Chat Content Needed

1. Welcome message (300-500 words)
2. What makes OpenMates different (1000-1500 words)
3. October 2025 updates (fetched from GitHub)
4. Example: Learn something new (sample conversation)
5. Example: Power of apps (sample conversation)
6. Example: Personalized privacy (sample conversation)
7. For developers (500-800 words + links)
8. Stay up to date (links to social media)

#### Media Assets Needed

- YouTube video embeds (3-5 videos)
- Open Graph images (1 per demo chat)
- PWA icons (8 sizes)
- Social media icons

#### SEO Content Needed

- Meta descriptions (each demo chat)
- Keywords lists (each demo chat)
- Alt text for images
- Structured data markup

### Risk Assessment

#### High Risk (Requires Mitigation)

- ❌ Static adapter may not support WebSockets for chat
  - **Mitigation:** Use client-side WebSocket connection (works fine)
- ❌ SEO might drop during domain transition
  - **Mitigation:** 301 redirects, maintain old domain, submit change in GSC

#### Medium Risk (Monitor Closely)

- ⚠️ Bundle size may increase with demo chats
  - **Mitigation:** Code splitting, lazy loading
- ⚠️ PWA cache may cause stale content issues
  - **Mitigation:** Proper cache versioning, skip waiting strategy

#### Low Risk (Acceptable)

- ✅ User confusion about demo chats
  - **Mitigation:** Clear labeling, good UX
- ✅ Demo chat content becomes outdated
  - **Mitigation:** Regular content reviews, changelog automation

---

## Success Criteria

### Must Have (MVP Requirements)

- ✅ Static build working with adapter-static
- ✅ All 8 demo chats created and prerendered
- ✅ Progressive enhancement working (demo → user chats)
- ✅ PWA installable on mobile and desktop
- ✅ Lighthouse score > 90 (all categories)
- ✅ Core Web Vitals in "Good" range (green)
- ✅ SEO meta tags and structured data on all pages
- ✅ Domain consolidated to openmates.org
- ✅ Offline support working for demo chats

### Should Have (Post-MVP)

- ✅ Lighthouse score > 95
- ✅ First page Google ranking for target keywords
- ✅ Push notifications working
- ✅ Background sync for pending messages
- ✅ Analytics tracking demo chat engagement
- ✅ A/B testing infrastructure

### Nice to Have (Future Enhancements)

- ✅ CMS for demo chat content
- ✅ Interactive demo features
- ✅ Personalized demo content
- ✅ Seasonal/event-based demos
- ✅ Video tutorials embedded in demos

---

## Team & Resources

### Required Roles

- **Full-Stack Developer:** Main implementation (1 person, full-time)
- **Content Writer:** Demo chat content (part-time, Phase 1)
- **Designer:** Icons, OG images, UI polish (part-time, Phases 1 & 5)
- **DevOps:** CDN setup, deployment pipeline (part-time, Phase 8)
- **QA Tester:** Cross-browser testing, PWA testing (part-time, Phase 7)

### Estimated Effort

- **Development:** 160-200 hours (4-5 weeks @ 40 hrs/week)
- **Content Creation:** 40-60 hours
- **Design:** 20-30 hours
- **Testing:** 40-50 hours
- **DevOps:** 10-15 hours
- **Total:** ~270-355 hours (~7-9 weeks of mixed team effort)

### Budget Estimate (if outsourcing)

- Development: $8,000 - $10,000 (at $50/hr)
- Content: $2,000 - $3,000
- Design: $1,000 - $1,500
- Testing: $2,000 - $2,500
- DevOps: $500 - $750
- **Total: $13,500 - $17,750**

### Tools & Services Costs (Annual)

- CDN: $0 (Cloudflare Pages free tier)
- Analytics: $0 - $90 (Plausible Starter)
- Error Tracking: $0 (Sentry free tier)
- Uptime Monitoring: $0 - $60 (UptimeRobot)
- Domain: $12 (already owned)
- **Total: $12 - $162/year**

---

## Next Steps

### Immediate Actions (This Week)

1. [ ] Review and approve this TODO document
2. [ ] Set up project board with all tasks
3. [ ] Install required dependencies (`adapter-static`, `@vite-pwa/sveltekit`)
4. [ ] Configure static adapter in `svelte.config.js`
5. [ ] Set up PWA plugin in `vite.config.ts`
6. [ ] Create demo chat directory structure
7. [ ] Start writing first demo chat content (Welcome)

### Next Sprint (Week 1)

1. [ ] Complete Phase 0 (SvelteKit Static & PWA Setup)
2. [ ] Complete Phase 1.1 & 1.2 (Demo Chat Infrastructure & Content)
3. [ ] Begin Phase 1.3 (Demo Chat Rendering)

### Following Sprint (Week 2)

1. [ ] Complete Phase 1.3 (Demo Chat Rendering)
2. [ ] Complete Phase 2 (Non-Auth User Experience)
3. [ ] Begin Phase 3 (SEO Optimization)

### Monthly Milestones

- **End of Month 1:** Phases 0-3 complete, demo chats working
- **End of Month 2:** Phases 4-7 complete, PWA working, tested
- **End of Month 3:** Deployed, monitoring, optimizing based on data

---

## Appendix

### Useful Resources

#### SvelteKit & Static Sites

- [SvelteKit Adapter Static Docs](https://kit.svelte.dev/docs/adapter-static)
- [SvelteKit Prerendering Guide](https://kit.svelte.dev/docs/page-options#prerender)
- [SvelteKit SEO Best Practices](https://joy-of-code.github.io/sveltekit-seo)

#### PWA Development

- [@vite-pwa/sveltekit Docs](https://vite-pwa-org.netlify.app/frameworks/sveltekit.html)
- [PWA Builder](https://www.pwabuilder.com/)
- [Workbox Docs](https://developer.chrome.com/docs/workbox/)
- [web-vitals Library](https://github.com/GoogleChrome/web-vitals)

#### Performance Optimization

- [Web.dev Core Web Vitals](https://web.dev/vitals/)
- [Lighthouse CI](https://github.com/GoogleChrome/lighthouse-ci)
- [Bundle Size Analyzer](https://github.com/webpack-contrib/webpack-bundle-analyzer)

#### SEO & Structured Data

- [Schema.org](https://schema.org/)
- [Google Search Console](https://search.google.com/search-console)
- [Open Graph Protocol](https://ogp.me/)
- [Twitter Card Validator](https://cards-dev.twitter.com/validator)

#### Deployment Platforms

- [Cloudflare Pages](https://pages.cloudflare.com/)
- [Netlify](https://www.netlify.com/)
- [Vercel](https://vercel.com/)

### Code Snippets

#### Progressive Enhancement Pattern

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { authStore } from '$lib/stores/authStore';

  export let data; // SSR data

  let displayChats = $state(data.demoChats);
  let isLoading = $state(false);

  onMount(async () => {
    // Only fetch if authenticated
    if ($authStore.isAuthenticated) {
      const userChats = await loadUserChats();
      // Instant swap, no loading state
      displayChats = userChats;
    }
  });
</script>

<!-- Always show chats immediately, no loading spinner -->
<ChatList chats={displayChats} />
```

#### Service Worker Registration

```typescript
// src/lib/register-sw.ts
import { registerSW } from "virtual:pwa-register";

const updateSW = registerSW({
  onNeedRefresh() {
    // Show update notification
    console.log("New version available");
  },
  onOfflineReady() {
    console.log("App ready to work offline");
  },
});

export { updateSW };
```

#### Web Vitals Tracking

```typescript
// src/lib/vitals.ts
import { getCLS, getFID, getFCP, getLCP, getTTFB } from "web-vitals";

function sendToAnalytics(metric) {
  // Send to your analytics service
  console.log(metric);
}

getCLS(sendToAnalytics);
getFID(sendToAnalytics);
getFCP(sendToAnalytics);
getLCP(sendToAnalytics);
getTTFB(sendToAnalytics);
```

---

**Document Version:** 1.0
**Last Updated:** 2025-10-29
**Owner:** Development Team
**Reviewers:** Product, Design, DevOps
**Status:** Ready for Implementation
