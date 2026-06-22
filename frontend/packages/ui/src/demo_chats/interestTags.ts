// frontend/packages/ui/src/demo_chats/interestTags.ts
// Canonical interest tag registry for guest smart selection and encrypted
// account topic preferences. Keep this module pure and browser-free so web,
// CLI, tests, and future native parity can consume the same stable IDs.
// Labels are loaded from chat.interests.* translations; fallbacks are only for
// missing-key resilience and must not be the normal UI path.

export type InterestTagType = "mate" | "skill" | "context";

export type InterestTagId =
  | "software_development"
  | "business_development"
  | "life_coach_psychology"
  | "medical_health"
  | "legal_law"
  | "finance"
  | "design"
  | "marketing_sales"
  | "science"
  | "history"
  | "cooking_food"
  | "electrical_engineering"
  | "maker_prototyping"
  | "movies_tv"
  | "activism"
  | "general_knowledge"
  | "find_events"
  | "find_restaurant"
  | "find_doctor_appointments"
  | "plot_charts"
  | "video_tutorials"
  | "find_apartments"
  | "build_electronics"
  | "diy_projects"
  | "create_videos"
  | "find_travel_connections"
  | "plan_trips"
  | "discuss_news"
  | "discuss_videos"
  | "run_code"
  | "privacy"
  | "learning"
  | "writing";

export interface InterestTag {
  id: InterestTagId;
  type: InterestTagType;
  labelKey: string;
  fallbackLabel: string;
  icon: string;
  appId: string;
  gradientCategory: string;
  defaultOrder: number;
  related: InterestTagId[];
  dailyInspirations: string[];
  introChats: string[];
  exampleChats: string[];
  suggestions: string[];
}

export const INTEREST_TAGS: InterestTag[] = [
  {
    id: "privacy",
    type: "context",
    labelKey: "chat.interests.privacy",
    fallbackLabel: "privacy",
    icon: "shield-check",
    appId: "ai",
    gradientCategory: "openmates_official",
    defaultOrder: 10,
    related: ["legal_law", "software_development", "writing"],
    dailyInspirations: ["pii-detection", "relevant-memories", "incognito-mode", "provider-independent"],
    introChats: ["demo-for-everyone", "demo-who-develops-openmates"],
    exampleChats: [
      "example-pdf-search-encryption",
      "example-privacy-website-hero-background",
      "example-private-workspace-demo-video",
    ],
    suggestions: [
      "chat.new_chat_suggestions.cybersecurity",
      "chat.new_chat_suggestions.professional_email",
    ],
  },
  {
    id: "learning",
    type: "context",
    labelKey: "chat.interests.learning",
    fallbackLabel: "learning",
    icon: "graduation-cap",
    appId: "web",
    gradientCategory: "general_knowledge",
    defaultOrder: 20,
    related: ["science", "history", "software_development", "video_tutorials", "writing"],
    dailyInspirations: ["openmates-intro", "learning-mode", "trusted-quotes", "offline-search"],
    introChats: ["demo-for-everyone"],
    exampleChats: [
      "example-rag-explained-videos",
      "example-ted-talk-transcript-summary",
      "example-memory-study-learning-goals",
    ],
    suggestions: [
      "chat.new_chat_suggestions.quantum_computing",
      "chat.new_chat_suggestions.learn_spanish",
      "chat.new_chat_suggestions.photosynthesis",
    ],
  },
  {
    id: "writing",
    type: "context",
    labelKey: "chat.interests.writing",
    fallbackLabel: "writing",
    icon: "pen-line",
    appId: "mail",
    gradientCategory: "creative_writing",
    defaultOrder: 30,
    related: ["marketing_sales", "business_development", "learning", "privacy"],
    dailyInspirations: ["audio-messages", "trusted-quotes", "document-upload", "relevant-memories"],
    introChats: ["demo-for-everyone"],
    exampleChats: [
      "example-ted-talk-transcript-summary",
      "example-building-maintenance-email",
      "example-memory-docs-writing-style",
    ],
    suggestions: [
      "chat.new_chat_suggestions.professional_email",
      "chat.new_chat_suggestions.writing_prompts",
      "chat.new_chat_suggestions.cover_letter",
    ],
  },
  {
    id: "software_development",
    type: "mate",
    labelKey: "chat.interests.software_development",
    fallbackLabel: "software development",
    icon: "code",
    appId: "code",
    gradientCategory: "software_development",
    defaultOrder: 40,
    related: ["run_code", "build_electronics", "diy_projects", "learning", "privacy"],
    dailyInspirations: ["sandbox-code-execution", "cli-parity", "rest-api", "webhooks", "learning-mode"],
    introChats: ["demo-for-developers", "demo-who-develops-openmates"],
    exampleChats: [
      "example-svelte-runes-docs",
      "example-python-squares-code-run",
      "example-openmates-app-skills-embeds-docs",
      "example-openmates-add-app-skill-doc",
      "example-frontend-developer-career-pivot",
    ],
    suggestions: [
      "chat.new_chat_suggestions.learn_coding",
      "chat.new_chat_suggestions.use_openmates_cli_api",
      "chat.new_chat_suggestions.cybersecurity",
      "chat.new_chat_suggestions.discover_math_calculate",
    ],
  },
  {
    id: "find_events",
    type: "skill",
    labelKey: "chat.interests.find_events",
    fallbackLabel: "find events",
    icon: "calendar-search",
    appId: "events",
    gradientCategory: "general_knowledge",
    defaultOrder: 50,
    related: ["plan_trips", "find_restaurant", "marketing_sales", "general_knowledge"],
    dailyInspirations: ["offline-search", "relevant-memories", "trusted-quotes"],
    introChats: ["demo-for-everyone"],
    exampleChats: [
      "example-ai-workshops-meetups-berlin",
      "example-creativity-drawing-meetups-berlin",
      "example-memory-events-saved-events",
    ],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "find_restaurant",
    type: "skill",
    labelKey: "chat.interests.find_restaurant",
    fallbackLabel: "find restaurant",
    icon: "utensils",
    appId: "maps",
    gradientCategory: "cooking_food",
    defaultOrder: 60,
    related: ["cooking_food", "find_events", "plan_trips", "find_apartments"],
    dailyInspirations: ["offline-search", "image-upload", "audio-messages"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-quiet-cafes-tempelhofer-feld", "example-organic-groceries-berlin"],
    suggestions: ["chat.new_chat_suggestions.meal_prep", "chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "find_doctor_appointments",
    type: "skill",
    labelKey: "chat.interests.find_doctor_appointments",
    fallbackLabel: "find doctor appointments",
    icon: "calendar-heart",
    appId: "health",
    gradientCategory: "medical_health",
    defaultOrder: 70,
    related: ["medical_health", "privacy", "learning"],
    dailyInspirations: ["relevant-memories", "audio-messages", "pii-detection"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-berlin-dermatology-appointments", "example-memory-health-appointments"],
    suggestions: ["chat.new_chat_suggestions.healthy_breakfast", "chat.new_chat_suggestions.workout_plan"],
  },
  {
    id: "plot_charts",
    type: "skill",
    labelKey: "chat.interests.plot_charts",
    fallbackLabel: "plot charts",
    icon: "chart-line",
    appId: "math",
    gradientCategory: "science",
    defaultOrder: 80,
    related: ["science", "finance", "business_development", "run_code"],
    dailyInspirations: ["sandbox-code-execution", "trusted-quotes", "document-upload"],
    introChats: ["demo-for-everyone", "demo-for-developers"],
    exampleChats: ["example-damped-sine-wave-plot", "example-mortgage-payment-calculation"],
    suggestions: ["chat.new_chat_suggestions.discover_math_calculate", "chat.new_chat_suggestions.stock_market"],
  },
  {
    id: "video_tutorials",
    type: "skill",
    labelKey: "chat.interests.video_tutorials",
    fallbackLabel: "video tutorials",
    icon: "circle-play",
    appId: "videos",
    gradientCategory: "movies_tv",
    defaultOrder: 90,
    related: ["learning", "discuss_videos", "movies_tv", "software_development"],
    dailyInspirations: ["learning-mode", "trusted-quotes", "offline-search"],
    introChats: ["demo-for-everyone", "demo-for-developers"],
    exampleChats: ["example-rag-explained-videos", "example-ted-talk-transcript-summary"],
    suggestions: ["chat.new_chat_suggestions.discover_video_search", "chat.new_chat_suggestions.learn_coding"],
  },
  {
    id: "find_apartments",
    type: "skill",
    labelKey: "chat.interests.find_apartments",
    fallbackLabel: "find apartments",
    icon: "home",
    appId: "home",
    gradientCategory: "business_development",
    defaultOrder: 100,
    related: ["find_restaurant", "plan_trips", "business_development"],
    dailyInspirations: ["document-upload", "image-upload", "offline-search"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-furnished-apartments-berlin", "example-memory-home-saved-listings"],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "business_development",
    type: "mate",
    labelKey: "chat.interests.business_development",
    fallbackLabel: "business development",
    icon: "briefcase-business",
    appId: "ai",
    gradientCategory: "business_development",
    defaultOrder: 110,
    related: ["marketing_sales", "finance", "writing", "plot_charts"],
    dailyInspirations: ["document-upload", "trusted-quotes", "relevant-memories"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-launch-readiness-checklist-doc", "example-privacy-first-product-launch-mind-map"],
    suggestions: ["chat.new_chat_suggestions.improve_productivity", "chat.new_chat_suggestions.professional_email"],
  },
  {
    id: "life_coach_psychology",
    type: "mate",
    labelKey: "chat.interests.life_coach_psychology",
    fallbackLabel: "life coach psychology",
    icon: "heart-handshake",
    appId: "ai",
    gradientCategory: "life_coach_psychology",
    defaultOrder: 120,
    related: ["learning", "writing", "medical_health"],
    dailyInspirations: ["learning-mode", "relevant-memories", "audio-messages"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-habit-tracker-onboarding-draft", "example-memory-ai-learning-preferences"],
    suggestions: ["chat.new_chat_suggestions.improve_productivity", "chat.new_chat_suggestions.workout_plan"],
  },
  {
    id: "medical_health",
    type: "mate",
    labelKey: "chat.interests.medical_health",
    fallbackLabel: "medical health",
    icon: "heart-pulse",
    appId: "health",
    gradientCategory: "medical_health",
    defaultOrder: 130,
    related: ["find_doctor_appointments", "privacy", "learning"],
    dailyInspirations: ["audio-messages", "relevant-memories", "pii-detection"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-berlin-dermatology-appointments", "example-memory-health-medical-history"],
    suggestions: ["chat.new_chat_suggestions.healthy_breakfast", "chat.new_chat_suggestions.workout_plan"],
  },
  {
    id: "legal_law",
    type: "mate",
    labelKey: "chat.interests.legal_law",
    fallbackLabel: "legal law",
    icon: "gavel",
    appId: "ai",
    gradientCategory: "legal_law",
    defaultOrder: 140,
    related: ["privacy", "writing", "activism"],
    dailyInspirations: ["pii-detection", "trusted-quotes", "document-upload"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-eu-chat-control-law-criticisms", "example-right-to-repair-laws-eu-us"],
    suggestions: ["chat.new_chat_suggestions.cybersecurity"],
  },
  {
    id: "finance",
    type: "mate",
    labelKey: "chat.interests.finance",
    fallbackLabel: "finance",
    icon: "dollar-sign",
    appId: "ai",
    gradientCategory: "finance",
    defaultOrder: 150,
    related: ["business_development", "plot_charts", "privacy"],
    dailyInspirations: ["trusted-quotes", "document-upload", "offline-search"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-mortgage-payment-calculation", "example-us-egg-prices-deep-research"],
    suggestions: ["chat.new_chat_suggestions.stock_market"],
  },
  {
    id: "design",
    type: "mate",
    labelKey: "chat.interests.design",
    fallbackLabel: "design",
    icon: "palette",
    appId: "images",
    gradientCategory: "design",
    defaultOrder: 160,
    related: ["create_videos", "writing", "marketing_sales"],
    dailyInspirations: ["image-upload", "document-upload", "relevant-memories"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-privacy-website-hero-background", "example-northstar-metrics-svg-logo"],
    suggestions: ["chat.new_chat_suggestions.discover_image_generate", "chat.new_chat_suggestions.writing_prompts"],
  },
  {
    id: "marketing_sales",
    type: "mate",
    labelKey: "chat.interests.marketing_sales",
    fallbackLabel: "marketing sales",
    icon: "megaphone",
    appId: "ai",
    gradientCategory: "marketing_sales",
    defaultOrder: 170,
    related: ["business_development", "writing", "create_videos", "find_events"],
    dailyInspirations: ["document-upload", "trusted-quotes", "relevant-memories"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-product-teaser-remotion-video", "example-nonprofit-event-planning-use-case"],
    suggestions: ["chat.new_chat_suggestions.professional_email", "chat.new_chat_suggestions.writing_prompts"],
  },
  {
    id: "science",
    type: "mate",
    labelKey: "chat.interests.science",
    fallbackLabel: "science",
    icon: "microscope",
    appId: "web",
    gradientCategory: "science",
    defaultOrder: 180,
    related: ["learning", "plot_charts", "general_knowledge"],
    dailyInspirations: ["learning-mode", "trusted-quotes", "offline-search"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-artemis-ii-mission", "example-sqlite-strict-tables-summary"],
    suggestions: ["chat.new_chat_suggestions.quantum_computing", "chat.new_chat_suggestions.photosynthesis"],
  },
  {
    id: "history",
    type: "mate",
    labelKey: "chat.interests.history",
    fallbackLabel: "history",
    icon: "landmark",
    appId: "web",
    gradientCategory: "history",
    defaultOrder: 190,
    related: ["learning", "discuss_news", "general_knowledge"],
    dailyInspirations: ["trusted-quotes", "offline-search", "document-upload"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-germany-historic-film-industry", "example-gigantic-airplanes"],
    suggestions: ["chat.new_chat_suggestions.internet_history", "chat.new_chat_suggestions.theory_relativity"],
  },
  {
    id: "cooking_food",
    type: "mate",
    labelKey: "chat.interests.cooking_food",
    fallbackLabel: "cooking food",
    icon: "utensils",
    appId: "maps",
    gradientCategory: "cooking_food",
    defaultOrder: 200,
    related: ["find_restaurant", "learning", "writing"],
    dailyInspirations: ["image-upload", "audio-messages", "relevant-memories"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-chickpea-spinach-protein-dinners", "example-organic-groceries-berlin"],
    suggestions: ["chat.new_chat_suggestions.healthy_breakfast", "chat.new_chat_suggestions.meal_prep"],
  },
  {
    id: "electrical_engineering",
    type: "mate",
    labelKey: "chat.interests.electrical_engineering",
    fallbackLabel: "electronics",
    icon: "zap",
    appId: "electronics",
    gradientCategory: "electrical_engineering",
    defaultOrder: 210,
    related: ["build_electronics", "software_development", "maker_prototyping"],
    dailyInspirations: ["sandbox-code-execution", "document-upload", "trusted-quotes"],
    introChats: ["demo-for-developers", "demo-for-everyone"],
    exampleChats: ["example-buck-converters-24v-5v", "example-usb-c-3v3-ldo-pcb-schematic"],
    suggestions: ["chat.new_chat_suggestions.learn_coding", "chat.new_chat_suggestions.discover_math_calculate"],
  },
  {
    id: "maker_prototyping",
    type: "mate",
    labelKey: "chat.interests.maker_prototyping",
    fallbackLabel: "maker prototyping",
    icon: "wrench",
    appId: "electronics",
    gradientCategory: "maker_prototyping",
    defaultOrder: 220,
    related: ["diy_projects", "build_electronics", "electrical_engineering"],
    dailyInspirations: ["image-upload", "sandbox-code-execution", "document-upload"],
    introChats: ["demo-for-everyone", "demo-for-developers"],
    exampleChats: ["example-usb-c-3v3-ldo-pcb-schematic", "example-right-to-repair-laws-eu-us"],
    suggestions: ["chat.new_chat_suggestions.learn_coding"],
  },
  {
    id: "movies_tv",
    type: "mate",
    labelKey: "chat.interests.movies_tv",
    fallbackLabel: "movies tv",
    icon: "tv",
    appId: "videos",
    gradientCategory: "movies_tv",
    defaultOrder: 230,
    related: ["discuss_videos", "video_tutorials", "create_videos"],
    dailyInspirations: ["trusted-quotes", "offline-search", "relevant-memories"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-rag-explained-videos", "example-memory-tv-to-watch-list"],
    suggestions: ["chat.new_chat_suggestions.discover_video_search"],
  },
  {
    id: "activism",
    type: "mate",
    labelKey: "chat.interests.activism",
    fallbackLabel: "activism",
    icon: "megaphone",
    appId: "news",
    gradientCategory: "activism",
    defaultOrder: 240,
    related: ["discuss_news", "legal_law", "privacy", "writing"],
    dailyInspirations: ["trusted-quotes", "offline-search", "document-upload"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-eu-chat-control-law-criticisms", "example-housing-policy-dinner-discussion"],
    suggestions: ["chat.new_chat_suggestions.carbon_footprint", "chat.new_chat_suggestions.cybersecurity"],
  },
  {
    id: "general_knowledge",
    type: "mate",
    labelKey: "chat.interests.general_knowledge",
    fallbackLabel: "general knowledge",
    icon: "help-circle",
    appId: "web",
    gradientCategory: "general_knowledge",
    defaultOrder: 250,
    related: ["learning", "science", "history", "discuss_news"],
    dailyInspirations: ["openmates-intro", "learning-mode", "trusted-quotes", "offline-search"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-gigantic-airplanes", "example-artemis-ii-mission"],
    suggestions: ["chat.new_chat_suggestions.quantum_computing", "chat.new_chat_suggestions.ml_vs_ai"],
  },
  {
    id: "build_electronics",
    type: "skill",
    labelKey: "chat.interests.build_electronics",
    fallbackLabel: "build electronics",
    icon: "cpu",
    appId: "electronics",
    gradientCategory: "electrical_engineering",
    defaultOrder: 260,
    related: ["electrical_engineering", "maker_prototyping", "software_development", "run_code"],
    dailyInspirations: ["document-upload", "sandbox-code-execution", "trusted-quotes"],
    introChats: ["demo-for-developers", "demo-for-everyone"],
    exampleChats: ["example-buck-converters-24v-5v", "example-usb-c-3v3-ldo-pcb-schematic"],
    suggestions: ["chat.new_chat_suggestions.discover_math_calculate", "chat.new_chat_suggestions.learn_coding"],
  },
  {
    id: "diy_projects",
    type: "skill",
    labelKey: "chat.interests.diy_projects",
    fallbackLabel: "DIY projects",
    icon: "hammer",
    appId: "electronics",
    gradientCategory: "maker_prototyping",
    defaultOrder: 270,
    related: ["maker_prototyping", "build_electronics", "learning"],
    dailyInspirations: ["image-upload", "document-upload", "learning-mode"],
    introChats: ["demo-for-everyone", "demo-for-developers"],
    exampleChats: ["example-right-to-repair-laws-eu-us", "example-usb-c-3v3-ldo-pcb-schematic"],
    suggestions: ["chat.new_chat_suggestions.learn_coding"],
  },
  {
    id: "create_videos",
    type: "skill",
    labelKey: "chat.interests.create_videos",
    fallbackLabel: "create videos",
    icon: "video",
    appId: "videos",
    gradientCategory: "movies_tv",
    defaultOrder: 280,
    related: ["design", "marketing_sales", "discuss_videos", "writing"],
    dailyInspirations: ["document-upload", "image-upload", "trusted-quotes"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-product-teaser-remotion-video", "example-private-workspace-demo-video"],
    suggestions: ["chat.new_chat_suggestions.discover_video_search", "chat.new_chat_suggestions.writing_prompts"],
  },
  {
    id: "find_travel_connections",
    type: "skill",
    labelKey: "chat.interests.find_travel_connections",
    fallbackLabel: "find travel connections",
    icon: "train-front",
    appId: "travel",
    gradientCategory: "general_knowledge",
    defaultOrder: 290,
    related: ["plan_trips", "find_apartments", "find_events"],
    dailyInspirations: ["offline-search", "relevant-memories", "image-upload"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-flights-berlin-to-bangkok", "example-memory-travel-saved-connections"],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "plan_trips",
    type: "skill",
    labelKey: "chat.interests.plan_trips",
    fallbackLabel: "plan trips",
    icon: "plane",
    appId: "travel",
    gradientCategory: "general_knowledge",
    defaultOrder: 300,
    related: ["find_travel_connections", "find_apartments", "find_events", "find_restaurant"],
    dailyInspirations: ["offline-search", "image-upload", "audio-messages"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-family-stays-kyoto", "example-furnished-apartments-berlin", "example-berlin-weather-bike-commute"],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "discuss_news",
    type: "skill",
    labelKey: "chat.interests.discuss_news",
    fallbackLabel: "discuss news",
    icon: "newspaper",
    appId: "news",
    gradientCategory: "general_knowledge",
    defaultOrder: 310,
    related: ["activism", "history", "general_knowledge", "privacy"],
    dailyInspirations: ["trusted-quotes", "offline-search", "provider-independent"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-eu-chat-control-law-criticisms", "example-fediverse-activitypub-social-search"],
    suggestions: ["chat.new_chat_suggestions.discover_news_search", "chat.new_chat_suggestions.ai_news"],
  },
  {
    id: "discuss_videos",
    type: "skill",
    labelKey: "chat.interests.discuss_videos",
    fallbackLabel: "discuss videos",
    icon: "message-square-play",
    appId: "videos",
    gradientCategory: "movies_tv",
    defaultOrder: 320,
    related: ["movies_tv", "video_tutorials", "create_videos", "learning"],
    dailyInspirations: ["trusted-quotes", "offline-search", "learning-mode"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-rag-explained-videos", "example-ted-talk-transcript-summary"],
    suggestions: ["chat.new_chat_suggestions.discover_video_search"],
  },
  {
    id: "run_code",
    type: "skill",
    labelKey: "chat.interests.run_code",
    fallbackLabel: "run code",
    icon: "play",
    appId: "code",
    gradientCategory: "software_development",
    defaultOrder: 330,
    related: ["software_development", "plot_charts", "build_electronics", "learning"],
    dailyInspirations: ["sandbox-code-execution", "cli-parity", "rest-api"],
    introChats: ["demo-for-developers"],
    exampleChats: ["example-python-squares-code-run", "example-damped-sine-wave-plot"],
    suggestions: [
      "chat.new_chat_suggestions.learn_coding",
      "chat.new_chat_suggestions.discover_math_calculate",
      "chat.new_chat_suggestions.use_openmates_cli_api",
    ],
  },
];

export const INTEREST_TAG_IDS = INTEREST_TAGS.map((tag) => tag.id);

export function isInterestTagId(value: string): value is InterestTagId {
  return INTEREST_TAG_IDS.includes(value as InterestTagId);
}

export function getInterestTagById(id: string): InterestTag | undefined {
  return INTEREST_TAGS.find((tag) => tag.id === id);
}

export function normalizeInterestTagIds(tagIds: readonly string[]): InterestTagId[] {
  const seen = new Set<InterestTagId>();
  const normalized: InterestTagId[] = [];

  for (const tagId of tagIds) {
    if (!isInterestTagId(tagId) || seen.has(tagId)) {
      continue;
    }
    seen.add(tagId);
    normalized.push(tagId);
  }

  return normalized;
}
