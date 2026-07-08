// frontend/packages/ui/src/demo_chats/guestProductInspirations.ts
// Logged-out product explainer inspirations for the new-chat welcome screen.
// These are public, non-personalized defaults and are ranked locally from
// guest-selected interest tags before signup.

import type { DailyInspiration } from "../stores/dailyInspirationStore";
import { OPENMATES_VIDEOS } from "./data/videos";
import { parse } from "yaml";

const INTRO_VIDEO = OPENMATES_VIDEOS["intro-en"];
const PRODUCT_VIDEO_BASE_URL = "https://openmates-product-media.nbg1.your-objectstorage.com/daily-inspiration/product-videos/v1";
const PRODUCT_VIDEO_TEASER_BASE_PATH = "/daily-inspiration-videos";
const PRODUCT_VIDEO_BY_FEATURE_ID: Record<string, string> = {
  "pii-detection": "custom-pii-detection",
  "events-search": "events-search",
  "trusted-quotes": "web-video-skills",
  "image-upload": "image-detection",
};
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

type ProductFeatureTextField = "title" | "headline" | "description";

type ProductFeatureTranslations = Record<
  string,
  Record<string, Partial<Record<ProductFeatureTextField, string>>>
>;

interface ProductFeaturesConfig {
  features?: ProductFeatureConfig[];
  translations?: ProductFeatureTranslations;
}

interface ProductFeatureData {
  features: ProductFeatureConfig[];
  translations: ProductFeatureTranslations;
}

interface ProductIntroText {
  phrase: string;
  title: string;
  assistantResponse: string;
  suggestions: [string, string, string];
  featureTitle: string;
  featureDescription: string;
}

const PRODUCT_INTRO_TEXT: Record<string, ProductIntroText> = {
  en: {
    phrase: "OpenMates gives you a team of specialized AI mates with apps, memories, and privacy-first controls.",
    title: "OpenMates for Everyone",
    assistantResponse:
      "OpenMates combines specialized AI mates, app skills, encrypted memories, and pay-per-use controls in one chat workspace. Pick an interest below and the welcome screen will locally reorder examples and suggestions without sending your choices to the server.",
    suggestions: [
      "Show me how OpenMates protects privacy",
      "What can app skills do?",
      "How is this different from one chatbot?",
    ],
    featureTitle: "Meet OpenMates",
    featureDescription: "AI mates, apps, memories, examples, and privacy controls in one workspace.",
  },
  de: {
    phrase: "OpenMates gibt dir ein Team spezialisierter KI-Mates mit Apps, Erinnerungen und Datenschutzkontrollen.",
    title: "OpenMates für alle",
    assistantResponse:
      "OpenMates kombiniert spezialisierte KI-Mates, App-Skills, verschlüsselte Erinnerungen und Pay-per-Use-Kontrollen in einem Chat-Arbeitsbereich. Wähle unten ein Interesse aus und der Willkommensbildschirm sortiert Beispiele und Vorschläge lokal neu, ohne deine Auswahl an den Server zu senden.",
    suggestions: [
      "Zeig mir, wie OpenMates Datenschutz schützt",
      "Was können App-Skills?",
      "Was ist anders als bei einem einzelnen Chatbot?",
    ],
    featureTitle: "Lerne OpenMates kennen",
    featureDescription: "KI-Mates, Apps, Erinnerungen, Beispiele und Datenschutzkontrollen in einem Arbeitsbereich.",
  },
};

function normalizeLocale(locale: string): string {
  return locale.split("-")[0]?.toLowerCase() || "en";
}

function getProductIntroText(locale: string): ProductIntroText {
  const lang = normalizeLocale(locale);
  return PRODUCT_INTRO_TEXT[lang] ?? PRODUCT_INTRO_TEXT.en;
}

function parseProductFeatureData(): ProductFeatureData {
  const parsed = parse(PRODUCT_FEATURES_YAML) as ProductFeaturesConfig | null;
  return {
    features: Array.isArray(parsed?.features) ? parsed.features : [],
    translations: parsed?.translations ?? {},
  };
}

function localizedFeatureField(
  feature: ProductFeatureConfig,
  translations: ProductFeatureTranslations,
  locale: string,
  field: ProductFeatureTextField,
): string {
  const lang = normalizeLocale(locale);
  return translations[lang]?.[feature.id]?.[field] ?? feature[field];
}

function buildProductFeatureVideo(featureId: string, title: string): DailyInspiration["direct_video"] {
  const videoSlug = PRODUCT_VIDEO_BY_FEATURE_ID[featureId];
  if (!videoSlug) return null;

  const teaserBase = `${PRODUCT_VIDEO_TEASER_BASE_PATH}/${videoSlug}-teaser`;
  return {
    title,
    mp4_url: `${PRODUCT_VIDEO_BASE_URL}/${videoSlug}.mp4`,
    thumbnail_url: `${teaserBase}.webp`,
    teaser_url: `${teaserBase}.webm`,
    teaser_mp4_url: `${teaserBase}.mp4`,
    teaser_webp_url: `${teaserBase}.webp`,
  };
}

function getProductExplainers(locale: string): Array<DailyInspiration & { tags: string[]; order: number }> {
  const intro = getProductIntroText(locale);
  const { features, translations } = parseProductFeatureData();
  return [
  {
    inspiration_id: "openmates-intro",
    phrase: intro.phrase,
    title: intro.title,
    category: "openmates_official",
    content_type: "feature",
    video: null,
    direct_video: {
      title: intro.title,
      mp4_url: INTRO_VIDEO.mp4_url,
      thumbnail_url: INTRO_VIDEO.thumbnail_url,
      teaser_url: INTRO_VIDEO.teaser_url ?? null,
      teaser_mp4_url: INTRO_VIDEO.teaser_mp4_url ?? null,
      teaser_webp_url: INTRO_VIDEO.teaser_webp_url ?? null,
    },
    generated_at: 0,
    assistant_response: intro.assistantResponse,
    follow_up_suggestions: intro.suggestions,
    feature: {
      feature_id: "openmates-intro",
      icon: "sparkles",
      title: intro.featureTitle,
      description: intro.featureDescription,
      settings_path: null,
    },
    tags: ["learning", "privacy", "software_development"],
    order: 10,
  },
  ...features.map((feature, index) => {
    const title = localizedFeatureField(feature, translations, locale, "title");
    const headline = localizedFeatureField(feature, translations, locale, "headline");
    const description = localizedFeatureField(feature, translations, locale, "description");
    return {
    inspiration_id: feature.id,
    phrase: headline,
    title,
    category: "openmates_official",
    content_type: "feature",
    video: null,
    direct_video: buildProductFeatureVideo(feature.id, title),
    generated_at: 0,
    assistant_response: description,
    follow_up_suggestions: [],
    feature: {
      feature_id: feature.id,
      icon: feature.icon,
      title,
      description,
      settings_path: feature.settings_path ?? null,
      requires_authentication: feature.requires_authentication ?? false,
    },
    tags: feature.tags,
    order: 20 + index * 10,
    };
  }),
];
}

export function getGuestProductInspirations(locale = "en"): DailyInspiration[] {
  const now = Math.floor(Date.now() / 1000);
  return getProductExplainers(locale)
    .slice()
    .sort((a, b) => a.order - b.order)
    .map(({ tags: _tags, order: _order, ...inspiration }) => ({
      ...inspiration,
      generated_at: now,
    }));
}
