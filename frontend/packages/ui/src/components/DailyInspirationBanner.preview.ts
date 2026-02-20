/**
 * Preview mock data for DailyInspirationBanner.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/DailyInspirationBanner
 *
 * Architecture note — store seeding:
 * DailyInspirationBanner reads data from `dailyInspirationStore` internally (not
 * from props), and the store starts empty. Without seeding it, the component
 * renders nothing (guarded by `{#if inspirations.length > 0}`).
 *
 * Each variant object uses a JS getter on `onStartChat` so that when the preview
 * system calls `Object.assign(base, variants[activeVariant])` — which invokes
 * getters — the store is seeded with the right inspirations for that variant.
 * This is the only hook we have into variant-switch lifecycle without modifying
 * the preview page itself.
 *
 * The only required prop is `onStartChat` — a callback invoked when the user
 * clicks a banner to start a chat from that inspiration.
 */

import {
  dailyInspirationStore,
  type DailyInspiration,
} from "../stores/dailyInspirationStore";

// ─── Mock inspiration data ────────────────────────────────────────────────────

const inspirationSoftware: DailyInspiration = {
  inspiration_id: "preview-software-1",
  phrase:
    "What if you could redesign the entire onboarding experience of your product in one afternoon?",
  category: "software_development",
  content_type: "video",
  video: {
    youtube_id: "dQw4w9WgXcQ",
    title: "How to Build a Great Developer Experience",
    thumbnail_url: "https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
    channel_name: "TechTalks",
    view_count: 1_240_000,
    duration_seconds: 847,
    published_at: "2024-01-15T10:00:00Z",
  },
  generated_at: Date.now(),
};

const inspirationFinance: DailyInspiration = {
  inspiration_id: "preview-finance-1",
  phrase:
    "Could understanding compound interest for just 15 minutes today change your financial future?",
  category: "finance",
  content_type: "video",
  video: {
    youtube_id: "abc123finance",
    title: "The Power of Compound Interest Explained",
    thumbnail_url: "https://img.youtube.com/vi/abc123finance/mqdefault.jpg",
    channel_name: "Finance Simplified",
    view_count: 345_000,
    duration_seconds: 612,
    published_at: "2024-03-01T12:00:00Z",
  },
  generated_at: Date.now(),
};

const inspirationNoVideo: DailyInspiration = {
  inspiration_id: "preview-general-1",
  phrase:
    "What would happen if you spent one hour today learning something completely outside your field?",
  category: "general_knowledge",
  content_type: "video",
  video: null,
  generated_at: Date.now(),
};

const inspirationDesign: DailyInspiration = {
  inspiration_id: "preview-design-1",
  phrase:
    "Design is not just what it looks like and feels like — design is how it works.",
  category: "design",
  content_type: "video",
  video: {
    youtube_id: "xyz789design",
    title: "Steve Jobs on Design Thinking",
    thumbnail_url: "https://img.youtube.com/vi/xyz789design/mqdefault.jpg",
    channel_name: "Design Matters",
    view_count: 2_800_000,
    duration_seconds: 423,
    published_at: "2023-11-20T08:30:00Z",
  },
  generated_at: Date.now(),
};

// ─── Store seeding ────────────────────────────────────────────────────────────
// Seed with the 3-card carousel on module load so the banner renders immediately.
// Each variant re-seeds via a getter (see variants export below).
dailyInspirationStore.setInspirations([
  inspirationSoftware,
  inspirationFinance,
  inspirationNoVideo,
]);

// ─── Default props ────────────────────────────────────────────────────────────

const defaultProps = {
  onStartChat: (inspiration: DailyInspiration) => {
    console.log(
      "[Preview] onStartChat →",
      inspiration.inspiration_id,
      ":",
      inspiration.phrase,
    );
  },
};

export default defaultProps;

// ─── Variant helper ───────────────────────────────────────────────────────────

/**
 * Build a variant descriptor whose `onStartChat` getter re-seeds the store.
 *
 * The preview system reads variant props via `Object.assign(base, variant)`.
 * `Object.assign` invokes getters on the source object, so the getter fires
 * exactly when the variant is applied — which is the right moment to seed the
 * store with that variant's inspirations.
 */
function makeVariant(
  inspirations: DailyInspiration[],
  label: string,
): Record<string, unknown> {
  return Object.defineProperty({}, "onStartChat", {
    enumerable: true,
    configurable: true,
    get() {
      // Re-seed the store when this variant is activated
      dailyInspirationStore.setInspirations(inspirations);
      return (inspiration: DailyInspiration) => {
        console.log(
          `[Preview:${label}] onStartChat →`,
          inspiration.inspiration_id,
          ":",
          inspiration.phrase,
        );
      };
    },
  });
}

// ─── Named variants ───────────────────────────────────────────────────────────

export const variants = {
  /**
   * Three-card carousel — shows left/right arrows and dot indicators.
   * Use the arrow buttons inside the banner to switch cards.
   */
  carousel: makeVariant(
    [inspirationSoftware, inspirationFinance, inspirationNoVideo],
    "carousel",
  ),

  /**
   * Single card — no carousel arrows or dot indicators.
   */
  singleCard: makeVariant([inspirationSoftware], "singleCard"),

  /**
   * Banner without a video panel — only phrase text and CTA on the left.
   */
  noVideo: makeVariant([inspirationNoVideo], "noVideo"),

  /**
   * Design category — dark near-black gradient.
   */
  design: makeVariant([inspirationDesign], "design"),

  /**
   * Finance category — green gradient with video thumbnail.
   */
  finance: makeVariant([inspirationFinance], "finance"),
};
