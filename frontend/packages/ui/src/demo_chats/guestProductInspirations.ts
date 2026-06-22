// frontend/packages/ui/src/demo_chats/guestProductInspirations.ts
// Logged-out product explainer inspirations for the new-chat welcome screen.
// These are public, non-personalized defaults and are ranked locally from
// guest-selected interest tags before signup.

import type { DailyInspiration } from "../stores/dailyInspirationStore";
import { OPENMATES_VIDEOS } from "./data/videos";
import { parse } from "yaml";

const INTRO_VIDEO = OPENMATES_VIDEOS["intro-en"];
const PRODUCT_FEATURE_MODULES = import.meta.glob("../data/product_features.yml", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;
const PRODUCT_FEATURES_YAML = Object.values(PRODUCT_FEATURE_MODULES)[0] ?? "features: []";

interface ProductFeatureConfig {
  id: string;
  title: string;
  headline: string;
  description: string;
  icon: string;
  tags: string[];
  settings_path?: string | null;
  requires_authentication?: boolean;
}

function parseProductFeatureConfigs(): ProductFeatureConfig[] {
  const parsed = parse(PRODUCT_FEATURES_YAML) as { features?: ProductFeatureConfig[] } | null;
  return Array.isArray(parsed?.features) ? parsed.features : [];
}

const PRODUCT_EXPLAINERS: Array<DailyInspiration & { tags: string[]; order: number }> = [
  {
    inspiration_id: "openmates-intro",
    phrase: "OpenMates gives you a team of specialized AI mates with apps, memories, and privacy-first controls.",
    title: "OpenMates for Everyone",
    category: "openmates_official",
    content_type: "feature",
    video: null,
    direct_video: {
      title: "OpenMates for Everyone",
      mp4_url: INTRO_VIDEO.mp4_url,
      thumbnail_url: INTRO_VIDEO.thumbnail_url,
      teaser_url: INTRO_VIDEO.teaser_url ?? null,
      teaser_mp4_url: INTRO_VIDEO.teaser_mp4_url ?? null,
      teaser_webp_url: INTRO_VIDEO.teaser_webp_url ?? null,
    },
    generated_at: 0,
    assistant_response:
      "OpenMates combines specialized AI mates, app skills, encrypted memories, and pay-per-use controls in one chat workspace. Pick an interest below and the welcome screen will locally reorder examples and suggestions without sending your choices to the server.",
    follow_up_suggestions: [
      "Show me how OpenMates protects privacy",
      "What can app skills do?",
      "How is this different from one chatbot?",
    ],
    feature: {
      feature_id: "openmates-intro",
      icon: "sparkles",
      title: "Meet OpenMates",
      description: "AI mates, apps, memories, examples, and privacy controls in one workspace.",
      settings_path: null,
    },
    tags: ["learning", "privacy", "software_development"],
    order: 10,
  },
  ...parseProductFeatureConfigs().map((feature, index) => ({
    inspiration_id: feature.id,
    phrase: feature.headline,
    title: feature.title,
    category: "openmates_official",
    content_type: "feature",
    video: null,
    generated_at: 0,
    assistant_response: feature.description,
    follow_up_suggestions: [],
    feature: {
      feature_id: feature.id,
      icon: feature.icon,
      title: feature.title,
      description: feature.description,
      settings_path: feature.settings_path ?? null,
      requires_authentication: feature.requires_authentication ?? false,
    },
    tags: feature.tags,
    order: 20 + index * 10,
  })),
];

export function getGuestProductInspirations(): DailyInspiration[] {
  const now = Math.floor(Date.now() / 1000);
  return PRODUCT_EXPLAINERS
    .slice()
    .sort((a, b) => a.order - b.order)
    .map(({ tags: _tags, order: _order, ...inspiration }) => ({
      ...inspiration,
      generated_at: now,
    }));
}
