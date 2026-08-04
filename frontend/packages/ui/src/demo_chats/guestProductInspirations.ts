// frontend/packages/ui/src/demo_chats/guestProductInspirations.ts
// Logged-out product explainer inspirations for the new-chat welcome screen.
// These are public, non-personalized defaults and are ranked locally from
// guest-selected interest tags before signup.

import type { DailyInspiration } from "../stores/dailyInspirationStore";
import { OPENMATES_VIDEOS } from "./data/videos";

const INTRO_VIDEO = OPENMATES_VIDEOS["intro-en"];
const ACTIONABLE_EVENTS_INSPIRATION_ID = "openmates-actionable-events";
const SIGNUP_CTA_INSPIRATION_ID = "openmates-signup-cta";

interface ProductIntroText {
  phrase: string;
  title: string;
  assistantResponse: string;
  suggestions: string[];
  featureTitle: string;
  featureDescription: string;
}

interface LandingProductSlide {
  inspiration_id: string;
  phrase: string;
  title: string;
  assistantResponse: string;
  suggestions: string[];
  featureId: string;
  icon: string;
  featureTitle: string;
  featureDescription: string;
  tags: string[];
  order: number;
}

const PRODUCT_INTRO_TEXT: Record<string, ProductIntroText> = {
  en: {
    phrase: "Simply ask your AI team mates.",
    title: "OpenMates for Everyone",
    assistantResponse:
      "Ask naturally and OpenMates routes the work to specialized mates and apps inside one chat workspace.",
    suggestions: [
      "Show me how OpenMates protects privacy",
      "What can app skills do?",
      "How is this different from one chatbot?",
    ],
    featureTitle: "Meet OpenMates",
    featureDescription: "Ask naturally and let specialized mates and apps help from one workspace.",
  },
  de: {
    phrase: "Frag einfach deine KI Team-Mates.",
    title: "OpenMates fuer alle",
    assistantResponse:
      "Frag natuerlich und OpenMates leitet die Arbeit an spezialisierte Mates und Apps in einem Chat-Arbeitsbereich weiter.",
    suggestions: [
      "Zeig mir, wie OpenMates Datenschutz schuetzt",
      "Was koennen App-Skills?",
      "Was ist anders als bei einem einzelnen Chatbot?",
    ],
    featureTitle: "Lerne OpenMates kennen",
    featureDescription: "Frag natuerlich und lass spezialisierte Mates und Apps in einem Arbeitsbereich helfen.",
  },
};

const LANDING_PRODUCT_SLIDES: Record<string, LandingProductSlide[]> = {
  en: [
    {
      inspiration_id: "openmates-privacy-safety",
      phrase: "Privacy & safety by design.",
      title: "Stay in control of personal data",
      assistantResponse:
        "OpenMates is built around encrypted chats, local-first controls, and explicit choices before sensitive context is shared.",
      suggestions: [
        "How does OpenMates protect private chats?",
        "Show privacy controls",
        "Explain local memories",
      ],
      featureId: "openmates-privacy-safety",
      icon: "shield-check",
      featureTitle: "Privacy & safety",
      featureDescription: "Encrypted chats and clear controls help you decide what is shared, when, and why.",
      tags: ["privacy"],
      order: 20,
    },
    {
      inspiration_id: "openmates-mates-focus",
      phrase: "Get the most out of AI. Without needing deep technical know-how.",
      title: "Work with the right mate",
      assistantResponse:
        "OpenMates can keep a chat focused on learning, planning, building, researching, or another job instead of treating every request the same way.",
      suggestions: [
        "Show focus modes",
        "Which mate should help me?",
        "Plan a project step by step",
      ],
      featureId: "openmates-mates-focus",
      icon: "users",
      featureTitle: "Mates & focus modes",
      featureDescription: "Use specialized guidance for different jobs without leaving the chat workspace.",
      tags: ["learning", "software_development"],
      order: 30,
    },
    {
      inspiration_id: "openmates-provider-cross-platform",
      phrase: "Built for people & the best possible experience.",
      title: "Bring OpenMates across your tools",
      assistantResponse:
        "OpenMates is designed around portable chats, multiple AI providers, and clients beyond one browser tab.",
      suggestions: [
        "Compare AI providers",
        "Show the CLI",
        "How portable are my chats?",
      ],
      featureId: "openmates-provider-cross-platform",
      icon: "network",
      featureTitle: "Independent workspace",
      featureDescription: "Avoid locking your work into one model provider or one app surface.",
      tags: ["privacy", "software_development"],
      order: 40,
    },
    {
      inspiration_id: SIGNUP_CTA_INSPIRATION_ID,
      phrase: "Start using OpenMates",
      title: "Signup",
      assistantResponse: "Create your OpenMates account to start using a private, pay-per-use AI workspace.",
      suggestions: ["No ads", "No subscription", "Privacy focus", "Pay per use"],
      featureId: SIGNUP_CTA_INSPIRATION_ID,
      icon: "check",
      featureTitle: "Signup",
      featureDescription: "No ads, no subscription, privacy focus, and pay per use.",
      tags: ["privacy"],
      order: 50,
    },
  ],
  de: [
    {
      inspiration_id: "openmates-privacy-safety",
      phrase: "Datenschutz & Sicherheit von Anfang an.",
      title: "Behalte Kontrolle ueber persoenliche Daten",
      assistantResponse:
        "OpenMates setzt auf verschluesselte Chats, lokale Kontrollen und bewusste Entscheidungen, bevor sensible Inhalte geteilt werden.",
      suggestions: [
        "Wie schuetzt OpenMates private Chats?",
        "Zeig Datenschutz-Kontrollen",
        "Erklaer lokale Erinnerungen",
      ],
      featureId: "openmates-privacy-safety",
      icon: "shield-check",
      featureTitle: "Datenschutz & Sicherheit",
      featureDescription: "Verschluesselte Chats und klare Kontrollen helfen dir zu entscheiden, was geteilt wird.",
      tags: ["privacy"],
      order: 20,
    },
    {
      inspiration_id: "openmates-mates-focus",
      phrase: "Hol das Beste aus KI heraus. Ohne tiefes technisches Vorwissen.",
      title: "Arbeite mit dem passenden Mate",
      assistantResponse:
        "OpenMates kann einen Chat auf Lernen, Planen, Bauen, Recherche oder andere Aufgaben fokussieren.",
      suggestions: [
        "Zeig Fokusmodi",
        "Welcher Mate passt?",
        "Plane ein Projekt Schritt fuer Schritt",
      ],
      featureId: "openmates-mates-focus",
      icon: "users",
      featureTitle: "Mates & Fokusmodi",
      featureDescription: "Nutze spezialisierte Hilfe fuer verschiedene Aufgaben im selben Chat-Arbeitsbereich.",
      tags: ["learning", "software_development"],
      order: 30,
    },
    {
      inspiration_id: "openmates-provider-cross-platform",
      phrase: "Für Menschen und die bestmögliche Erfahrung entwickelt.",
      title: "Nutze OpenMates in deinen Tools",
      assistantResponse:
        "OpenMates ist fuer portable Chats, mehrere KI-Provider und verschiedene Clients gebaut.",
      suggestions: [
        "Vergleiche KI-Provider",
        "Zeig die CLI",
        "Wie portabel sind meine Chats?",
      ],
      featureId: "openmates-provider-cross-platform",
      icon: "network",
      featureTitle: "Unabhaengiger Arbeitsbereich",
      featureDescription: "Vermeide, deine Arbeit an einen Modellanbieter oder eine App-Oberflaeche zu binden.",
      tags: ["privacy", "software_development"],
      order: 40,
    },
    {
      inspiration_id: SIGNUP_CTA_INSPIRATION_ID,
      phrase: "OpenMates starten:",
      title: "Registrieren",
      assistantResponse: "Erstelle dein OpenMates-Konto und nutze einen privaten KI-Arbeitsbereich mit Pay-per-Use.",
      suggestions: ["Keine Werbung", "Kein Abo", "Datenschutz im Fokus", "Pay-per-Use"],
      featureId: SIGNUP_CTA_INSPIRATION_ID,
      icon: "check",
      featureTitle: "Registrieren",
      featureDescription: "Keine Werbung, kein Abo, Datenschutz im Fokus und Pay-per-Use.",
      tags: ["privacy"],
      order: 50,
    },
  ],
};

function normalizeLocale(locale: string): string {
  return locale.split("-")[0]?.toLowerCase() || "en";
}

function getProductIntroText(locale: string): ProductIntroText {
  const lang = normalizeLocale(locale);
  return PRODUCT_INTRO_TEXT[lang] ?? PRODUCT_INTRO_TEXT.en;
}

function createLandingSlide(slide: LandingProductSlide): DailyInspiration & { tags: string[]; order: number } {
  return {
    inspiration_id: slide.inspiration_id,
    phrase: slide.phrase,
    title: slide.title,
    category: "openmates_official",
    content_type: "feature",
    video: null,
    direct_video: null,
    generated_at: 0,
    assistant_response: slide.assistantResponse,
    follow_up_suggestions: slide.suggestions,
    feature: {
      feature_id: slide.featureId,
      icon: slide.icon,
      title: slide.featureTitle,
      description: slide.featureDescription,
      settings_path: null,
    },
    tags: slide.tags,
    order: slide.order,
  };
}

function getProductExplainers(locale: string): Array<DailyInspiration & { tags: string[]; order: number }> {
  const intro = getProductIntroText(locale);
  const lang = normalizeLocale(locale);
  const landingSlides = LANDING_PRODUCT_SLIDES[lang] ?? LANDING_PRODUCT_SLIDES.en;

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
    {
      inspiration_id: ACTIONABLE_EVENTS_INSPIRATION_ID,
      phrase: "Actionable. Not just a wall of text.",
      title: "Find language-learning events",
      category: "openmates_official",
      content_type: "feature",
      video: null,
      direct_video: null,
      generated_at: 0,
      assistant_response:
        "OpenMates can turn a simple request into useful results, previews, and details instead of only writing a long answer.",
      follow_up_suggestions: [
        "Find language-learning events in Berlin",
        "Show beginner-friendly events this week",
        "Compare event options near me",
      ],
      feature: {
        feature_id: ACTIONABLE_EVENTS_INSPIRATION_ID,
        icon: "calendar-search",
        title: "Actionable results",
        description: "Search for real-world options and inspect useful details from one chat.",
        settings_path: null,
      },
      tags: ["find_events", "learning"],
      order: 15,
    },
    ...landingSlides.map(createLandingSlide),
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
