// frontend/packages/ui/src/demo_chats/interestTags.ts
// Canonical interest registry for local guest ranking and encrypted account
// preferences. Tag IDs are stable persisted data; legacy IDs are migrated by
// normalizeInterestTagIds without sending cleartext preferences to the server.
// Example mappings reference the public registry in exampleChatData.ts.

export type InterestTagType = "mate" | "skill" | "context";
export type InterestTagAudience = "work" | "personal";

export type InterestTagId =
  | "marketing"
  | "software_development"
  | "finance_bookkeeping"
  | "ui_ux_design"
  | "business_planning"
  | "content_creation"
  | "project_management"
  | "admin_operations"
  | "find_local_events"
  | "plan_trips"
  | "writing_editing"
  | "sales"
  | "customer_support"
  | "research_analysis"
  | "data_spreadsheets"
  | "legal_compliance"
  | "events_networking"
  | "websites_online_shops"
  | "automation_workflows"
  | "client_work_proposals"
  | "branding_images"
  | "video_social_media"
  | "productivity_organization"
  | "learning_new_skills"
  | "health_wellbeing"
  | "find_doctor_appointments"
  | "find_apartments"
  | "find_trains_flights"
  | "find_restaurants_cafes"
  | "personal_finances"
  | "cooking_meal_planning"
  | "news_current_events"
  | "diy_electronics"
  | "privacy_personal_data";

export interface InterestTag {
  id: InterestTagId;
  type: InterestTagType;
  audience: InterestTagAudience;
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

type InterestTagDefinition = Omit<
  InterestTag,
  "labelKey" | "defaultOrder" | "dailyInspirations" | "introChats"
> & {
  developerIntro?: boolean;
  dailyInspirations?: string[];
};

const GUEST_PRODUCT_INSPIRATIONS = [
  "openmates-actionable-events",
  "openmates-privacy-safety",
  "openmates-mates-focus",
  "openmates-provider-cross-platform",
  "openmates-signup-cta",
];

const DEFINITIONS: InterestTagDefinition[] = [
  {
    id: "marketing", type: "mate", audience: "work", fallbackLabel: "marketing", icon: "megaphone", appId: "ai", gradientCategory: "marketing_sales",
    related: ["content_creation", "branding_images", "video_social_media", "sales", "events_networking"],
    exampleChats: ["example-product-teaser-remotion-video", "example-private-workspace-demo-video", "example-product-launch-synth-loop", "example-privacy-website-hero-background", "example-privacy-first-product-launch", "example-nonprofit-event-planning-use", "example-launch-readiness-checklist-doc"],
    suggestions: ["chat.new_chat_suggestions.professional_email", "chat.new_chat_suggestions.writing_prompts"],
  },
  {
    id: "software_development", type: "mate", audience: "work", fallbackLabel: "software development", icon: "code", appId: "code", gradientCategory: "software_development", developerIntro: true,
    related: ["automation_workflows", "websites_online_shops", "data_spreadsheets", "ui_ux_design", "research_analysis", "privacy_personal_data"],
    dailyInspirations: ["sandbox-code-execution", "cli-parity", "rest-api", "webhooks", "learning-mode"],
    exampleChats: ["example-habit-garden-web-application", "example-screenshot-to-html-pricing", "example-beautiful-single-page-html", "example-svelte-runes-docs", "example-openmates-add-app-skill", "example-rust-vector-database-repos", "example-sqlite-strict-tables-summary", "example-python-squares-code-run", "example-usb-c-3v3-ldo", "example-dashboard-sidebar-svg-icons", "example-open-meteo-weather-notebook", "example-privacy-first-local-ai", "example-memory-code-projects", "example-memory-code-preferred-tech", "example-memory-code-coding-setup", "example-memory-code-want-to"],
    suggestions: ["chat.new_chat_suggestions.learn_coding", "chat.new_chat_suggestions.use_openmates_cli_api", "chat.new_chat_suggestions.cybersecurity"],
  },
  {
    id: "finance_bookkeeping", type: "mate", audience: "work", fallbackLabel: "finance & bookkeeping", icon: "calculator", appId: "ai", gradientCategory: "finance",
    related: ["data_spreadsheets", "admin_operations", "legal_compliance", "business_planning", "personal_finances"],
    exampleChats: ["example-finance-cash-flow-overview", "example-vital-farms-sec-financials", "example-us-egg-prices-deep", "example-mortgage-payment-calculation"],
    suggestions: ["chat.new_chat_suggestions.stock_market", "chat.new_chat_suggestions.improve_productivity"],
  },
  {
    id: "ui_ux_design", type: "mate", audience: "work", fallbackLabel: "UI/UX design", icon: "panels-top-left", appId: "images", gradientCategory: "design",
    related: ["branding_images", "websites_online_shops", "content_creation", "software_development"],
    exampleChats: ["example-screenshot-to-html-pricing", "example-habit-tracker-onboarding-draft", "example-habit-garden-web-application", "example-dashboard-sidebar-svg-icons", "example-beautiful-single-page-html", "example-privacy-website-hero-background", "example-image-vectorize-openmates-header"],
    suggestions: ["chat.new_chat_suggestions.discover_image_generate", "chat.new_chat_suggestions.writing_prompts"],
  },
  {
    id: "business_planning", type: "mate", audience: "work", fallbackLabel: "business planning", icon: "briefcase-business", appId: "ai", gradientCategory: "business_development",
    related: ["marketing", "finance_bookkeeping", "project_management", "sales", "client_work_proposals"],
    exampleChats: ["example-privacy-first-local-ai", "example-privacy-first-product-launch", "example-launch-readiness-checklist-doc", "example-nonprofit-event-planning-use", "example-frontend-developer-career-pivot", "example-finance-cash-flow-overview", "example-berlin-ai-founder-meetups"],
    suggestions: ["chat.new_chat_suggestions.improve_productivity", "chat.new_chat_suggestions.professional_email"],
  },
  {
    id: "content_creation", type: "skill", audience: "work", fallbackLabel: "content creation", icon: "sparkles", appId: "ai", gradientCategory: "creative_writing",
    related: ["marketing", "writing_editing", "branding_images", "video_social_media"],
    exampleChats: ["example-product-teaser-remotion-video", "example-private-workspace-demo-video", "example-product-launch-synth-loop", "example-audio-transcribe-voice-note", "example-ted-talk-transcript-summary", "example-rag-explained-videos", "example-reference-image-3d-model", "example-image-vectorize-openmates-header", "example-privacy-website-hero-background", "example-memory-videos-to-watch"],
    suggestions: ["chat.new_chat_suggestions.writing_prompts", "chat.new_chat_suggestions.discover_image_generate", "chat.new_chat_suggestions.discover_video_search"],
  },
  {
    id: "project_management", type: "skill", audience: "work", fallbackLabel: "project management", icon: "list-checks", appId: "tasks", gradientCategory: "business_development",
    related: ["admin_operations", "automation_workflows", "productivity_organization", "business_planning", "client_work_proposals"],
    exampleChats: ["example-example-chat-task-planning", "example-launch-readiness-checklist-doc", "example-privacy-first-product-launch", "example-privacy-first-local-ai", "example-nonprofit-event-planning-use", "example-library-book-return-workflow", "example-memory-code-projects"],
    suggestions: ["chat.new_chat_suggestions.improve_productivity"],
  },
  {
    id: "admin_operations", type: "skill", audience: "work", fallbackLabel: "admin & operations", icon: "clipboard-list", appId: "tasks", gradientCategory: "business_development",
    related: ["project_management", "automation_workflows", "finance_bookkeeping", "customer_support", "productivity_organization"],
    exampleChats: ["example-upcoming-reminders-list", "example-cancel-test-reminder", "example-library-book-return-workflow", "example-building-maintenance-email", "example-launch-readiness-checklist-doc", "example-example-chat-task-planning", "example-memory-reminder-defaults"],
    suggestions: ["chat.new_chat_suggestions.improve_productivity", "chat.new_chat_suggestions.professional_email"],
  },
  {
    id: "find_local_events", type: "skill", audience: "personal", fallbackLabel: "find local events", icon: "calendar-search", appId: "events", gradientCategory: "general_knowledge",
    related: ["events_networking", "find_restaurants_cafes", "plan_trips", "health_wellbeing"],
    exampleChats: ["example-ai-workshops-meetups-berlin", "example-creativity-drawing-meetups-berlin", "example-berlin-ai-founder-meetups", "example-memory-events-saved-events", "example-urban-sports-fitness-studios", "example-urban-sports-yoga-classes"],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "plan_trips", type: "skill", audience: "personal", fallbackLabel: "plan trips", icon: "plane", appId: "travel", gradientCategory: "general_knowledge",
    related: ["find_trains_flights", "find_apartments", "find_restaurants_cafes", "find_local_events"],
    exampleChats: ["example-family-stays-kyoto", "example-memory-travel-trips", "example-memory-travel-saved-stays", "example-memory-travel-preferred-activities", "example-memory-travel-saved-connections", "example-memory-travel-preferred-airlines", "example-memory-travel-preferred-transport", "example-flights-berlin-bangkok", "example-berlin-central-station-map-location", "example-furnished-apartments-berlin"],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "writing_editing", type: "mate", audience: "work", fallbackLabel: "writing & editing", icon: "pen-line", appId: "mail", gradientCategory: "creative_writing",
    related: ["content_creation", "marketing", "client_work_proposals", "customer_support"],
    exampleChats: ["example-building-maintenance-email", "example-audio-transcribe-voice-note", "example-ted-talk-transcript-summary", "example-memory-docs-writing-style", "example-memory-mail-writing-styles", "example-openmates-add-app-skill", "example-sqlite-strict-tables-summary", "example-launch-readiness-checklist-doc"],
    suggestions: ["chat.new_chat_suggestions.professional_email", "chat.new_chat_suggestions.writing_prompts", "chat.new_chat_suggestions.cover_letter"],
  },
  {
    id: "sales", type: "mate", audience: "work", fallbackLabel: "sales", icon: "badge-dollar-sign", appId: "ai", gradientCategory: "marketing_sales",
    related: ["marketing", "client_work_proposals", "customer_support", "business_planning"],
    exampleChats: ["example-screenshot-to-html-pricing", "example-privacy-first-local-ai", "example-berlin-ai-founder-meetups", "example-nonprofit-event-planning-use"],
    suggestions: ["chat.new_chat_suggestions.professional_email", "chat.new_chat_suggestions.improve_productivity"],
  },
  {
    id: "customer_support", type: "mate", audience: "work", fallbackLabel: "customer support", icon: "messages-square", appId: "mail", gradientCategory: "business_development",
    related: ["sales", "writing_editing", "admin_operations", "productivity_organization"],
    exampleChats: ["example-building-maintenance-email", "example-launch-readiness-checklist-doc", "example-habit-tracker-onboarding-draft"],
    suggestions: ["chat.new_chat_suggestions.professional_email", "chat.new_chat_suggestions.improve_productivity"],
  },
  {
    id: "research_analysis", type: "mate", audience: "work", fallbackLabel: "research & analysis", icon: "search-check", appId: "web", gradientCategory: "general_knowledge",
    related: ["data_spreadsheets", "legal_compliance", "learning_new_skills", "news_current_events"],
    exampleChats: ["example-us-egg-prices-deep", "example-vital-farms-sec-financials", "example-right-to-repair-laws", "example-eu-chat-control-law", "example-housing-policy-dinner-discussion", "example-artemis-ii-mission", "example-germany-historic-film-industry", "example-gigantic-airplanes", "example-framework-store-reputation-check", "example-rust-vector-database-repos", "example-classic-car-reverse-image", "example-pdf-search-encryption", "example-pdf-read-secret-word", "example-pdf-view-page-layout", "example-sqlite-strict-tables-summary", "example-fediverse-activitypub-social-search", "example-open-meteo-weather-notebook", "example-buck-converters-24v-5v"],
    suggestions: ["chat.new_chat_suggestions.quantum_computing", "chat.new_chat_suggestions.ml_vs_ai"],
  },
  {
    id: "data_spreadsheets", type: "skill", audience: "work", fallbackLabel: "data & spreadsheets", icon: "table-2", appId: "math", gradientCategory: "science",
    related: ["research_analysis", "finance_bookkeeping", "software_development", "business_planning"],
    exampleChats: ["example-finance-cash-flow-overview", "example-vital-farms-sec-financials", "example-mortgage-payment-calculation", "example-damped-sine-wave-plot", "example-open-meteo-weather-notebook", "example-buck-converters-24v-5v", "example-berlin-dermatology-appointments", "example-right-to-repair-laws", "example-python-squares-code-run"],
    suggestions: ["chat.new_chat_suggestions.discover_math_calculate", "chat.new_chat_suggestions.stock_market"],
  },
  {
    id: "legal_compliance", type: "mate", audience: "work", fallbackLabel: "legal & compliance", icon: "gavel", appId: "ai", gradientCategory: "legal_law",
    related: ["privacy_personal_data", "business_planning", "finance_bookkeeping", "research_analysis"],
    exampleChats: ["example-eu-chat-control-law", "example-right-to-repair-laws", "example-vital-farms-sec-financials", "example-pdf-search-encryption", "example-privacy-first-local-ai"],
    suggestions: ["chat.new_chat_suggestions.cybersecurity"],
  },
  {
    id: "events_networking", type: "skill", audience: "work", fallbackLabel: "events & networking", icon: "users-round", appId: "events", gradientCategory: "marketing_sales",
    related: ["marketing", "sales", "find_local_events", "business_planning"],
    exampleChats: ["example-nonprofit-event-planning-use", "example-berlin-ai-founder-meetups", "example-ai-workshops-meetups-berlin", "example-creativity-drawing-meetups-berlin", "example-memory-events-saved-events"],
    suggestions: ["chat.new_chat_suggestions.improve_productivity"],
  },
  {
    id: "websites_online_shops", type: "skill", audience: "work", fallbackLabel: "websites & online shops", icon: "shopping-bag", appId: "code", gradientCategory: "software_development", developerIntro: true,
    related: ["software_development", "ui_ux_design", "marketing", "sales", "branding_images"],
    exampleChats: ["example-habit-garden-web-application", "example-beautiful-single-page-html", "example-screenshot-to-html-pricing", "example-privacy-website-hero-background", "example-fediverse-activitypub-social-search"],
    suggestions: ["chat.new_chat_suggestions.learn_coding", "chat.new_chat_suggestions.discover_image_generate"],
  },
  {
    id: "automation_workflows", type: "skill", audience: "work", fallbackLabel: "automation & workflows", icon: "workflow", appId: "tasks", gradientCategory: "software_development", developerIntro: true,
    related: ["project_management", "admin_operations", "software_development", "productivity_organization"],
    exampleChats: ["example-library-book-return-workflow", "example-cancel-test-reminder", "example-upcoming-reminders-list", "example-memory-reminder-defaults", "example-nonprofit-event-planning-use"],
    suggestions: ["chat.new_chat_suggestions.improve_productivity", "chat.new_chat_suggestions.use_openmates_cli_api"],
  },
  {
    id: "client_work_proposals", type: "mate", audience: "work", fallbackLabel: "client work & proposals", icon: "handshake", appId: "ai", gradientCategory: "business_development",
    related: ["sales", "business_planning", "writing_editing", "project_management"],
    exampleChats: ["example-privacy-first-local-ai", "example-nonprofit-event-planning-use", "example-privacy-first-product-launch"],
    suggestions: ["chat.new_chat_suggestions.professional_email", "chat.new_chat_suggestions.cover_letter"],
  },
  {
    id: "branding_images", type: "skill", audience: "work", fallbackLabel: "branding & images", icon: "image", appId: "images", gradientCategory: "design",
    related: ["ui_ux_design", "marketing", "content_creation", "video_social_media"],
    exampleChats: ["example-northstar-metrics-svg-logo", "example-image-vectorize-openmates-header", "example-privacy-website-hero-background", "example-habit-tracker-onboarding-draft", "example-dashboard-sidebar-svg-icons", "example-product-teaser-remotion-video", "example-private-workspace-demo-video", "example-reference-image-3d-model", "example-memory-images-preferred-styles", "example-product-launch-synth-loop"],
    suggestions: ["chat.new_chat_suggestions.discover_image_generate", "chat.new_chat_suggestions.writing_prompts"],
  },
  {
    id: "video_social_media", type: "skill", audience: "work", fallbackLabel: "video & social media", icon: "video", appId: "videos", gradientCategory: "movies_tv",
    related: ["content_creation", "marketing", "branding_images", "writing_editing"],
    exampleChats: ["example-product-teaser-remotion-video", "example-private-workspace-demo-video", "example-fediverse-activitypub-social-search", "example-mastodon-account-recent-posts", "example-rag-explained-videos", "example-ted-talk-transcript-summary", "example-memory-videos-to-watch", "example-memory-tv-to-watch", "example-memory-tv-watched-movies", "example-memory-tv-watched-shows", "example-product-launch-synth-loop"],
    suggestions: ["chat.new_chat_suggestions.discover_video_search", "chat.new_chat_suggestions.writing_prompts"],
  },
  {
    id: "productivity_organization", type: "context", audience: "work", fallbackLabel: "productivity & organization", icon: "check-check", appId: "tasks", gradientCategory: "life_coach_psychology",
    related: ["project_management", "admin_operations", "automation_workflows", "learning_new_skills"],
    exampleChats: ["example-upcoming-reminders-list", "example-cancel-test-reminder", "example-example-chat-task-planning", "example-library-book-return-workflow", "example-launch-readiness-checklist-doc", "example-balcony-plant-reminder", "example-memory-reminder-defaults", "example-memory-web-bookmarks", "example-memory-web-read-later", "example-memory-books-to-read", "example-memory-tv-to-watch", "example-memory-videos-to-watch", "example-memory-study-learning-goals", "example-memory-travel-trips", "example-memory-code-projects", "example-berlin-weather-bike-commute"],
    suggestions: ["chat.new_chat_suggestions.improve_productivity"],
  },
  {
    id: "learning_new_skills", type: "context", audience: "personal", fallbackLabel: "learning new skills", icon: "graduation-cap", appId: "web", gradientCategory: "general_knowledge", developerIntro: true,
    related: ["research_analysis", "software_development", "productivity_organization", "diy_electronics"],
    exampleChats: ["example-memory-study-learning-goals", "example-memory-code-want-to", "example-svelte-runes-docs", "example-rag-explained-videos", "example-ai-workshops-meetups-berlin", "example-frontend-developer-career-pivot", "example-memory-books-to-read", "example-memory-books-currently-reading", "example-memory-books-favorite-books", "example-ted-talk-transcript-summary", "example-sqlite-strict-tables-summary", "example-rust-vector-database-repos", "example-open-meteo-weather-notebook", "example-damped-sine-wave-plot", "example-artemis-ii-mission", "example-gigantic-airplanes", "example-germany-historic-film-industry"],
    suggestions: ["chat.new_chat_suggestions.learn_coding", "chat.new_chat_suggestions.learn_spanish", "chat.new_chat_suggestions.quantum_computing"],
  },
  {
    id: "health_wellbeing", type: "mate", audience: "personal", fallbackLabel: "health & wellbeing", icon: "heart-pulse", appId: "health", gradientCategory: "medical_health",
    related: ["find_doctor_appointments", "cooking_meal_planning", "productivity_organization", "privacy_personal_data"],
    exampleChats: ["example-urban-sports-fitness-studios", "example-urban-sports-yoga-classes", "example-chickpea-spinach-protein-dinners", "example-organic-groceries-berlin", "example-berlin-morning-bike-forecast", "example-berlin-weather-bike-commute", "example-habit-tracker-onboarding-draft", "example-habit-garden-web-application", "example-memory-health-medical-history"],
    suggestions: ["chat.new_chat_suggestions.healthy_breakfast", "chat.new_chat_suggestions.workout_plan"],
  },
  {
    id: "find_doctor_appointments", type: "skill", audience: "personal", fallbackLabel: "find doctor appointments", icon: "calendar-heart", appId: "health", gradientCategory: "medical_health",
    related: ["health_wellbeing", "privacy_personal_data", "productivity_organization"],
    exampleChats: ["example-berlin-dermatology-appointments", "example-memory-health-appointments", "example-memory-health-medical-history"],
    suggestions: ["chat.new_chat_suggestions.healthy_breakfast", "chat.new_chat_suggestions.workout_plan"],
  },
  {
    id: "find_apartments", type: "skill", audience: "personal", fallbackLabel: "find apartments", icon: "home", appId: "home", gradientCategory: "business_development",
    related: ["personal_finances", "plan_trips", "find_restaurants_cafes", "find_local_events"],
    exampleChats: ["example-furnished-apartments-berlin", "example-memory-home-saved-listings", "example-memory-travel-saved-stays"],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "find_trains_flights", type: "skill", audience: "personal", fallbackLabel: "find trains & flights", icon: "train-front", appId: "travel", gradientCategory: "general_knowledge",
    related: ["plan_trips", "find_apartments", "find_local_events"],
    exampleChats: ["example-flights-berlin-bangkok", "example-lh400-flight-status-check", "example-deutschlandticket-train-fare-breakdown", "example-memory-travel-saved-connections", "example-memory-travel-preferred-airlines", "example-memory-travel-preferred-transport", "example-berlin-central-station-map-location"],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "find_restaurants_cafes", type: "skill", audience: "personal", fallbackLabel: "find restaurants & cafes", icon: "utensils", appId: "maps", gradientCategory: "cooking_food",
    related: ["find_local_events", "cooking_meal_planning", "plan_trips", "find_apartments"],
    exampleChats: ["example-berlin-mitte-work-friendly", "example-quiet-cafes-tempelhofer-feld", "example-organic-groceries-berlin"],
    suggestions: ["chat.new_chat_suggestions.meal_prep", "chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "personal_finances", type: "mate", audience: "personal", fallbackLabel: "personal finances", icon: "wallet-cards", appId: "ai", gradientCategory: "finance",
    related: ["finance_bookkeeping", "find_apartments", "data_spreadsheets", "privacy_personal_data"],
    exampleChats: ["example-mortgage-payment-calculation", "example-deutschlandticket-train-fare-breakdown", "example-us-egg-prices-deep"],
    suggestions: ["chat.new_chat_suggestions.stock_market"],
  },
  {
    id: "cooking_meal_planning", type: "mate", audience: "personal", fallbackLabel: "cooking & meal planning", icon: "cooking-pot", appId: "maps", gradientCategory: "cooking_food",
    related: ["health_wellbeing", "find_restaurants_cafes", "productivity_organization"],
    exampleChats: ["example-chickpea-spinach-protein-dinners", "example-organic-groceries-berlin"],
    suggestions: ["chat.new_chat_suggestions.healthy_breakfast", "chat.new_chat_suggestions.meal_prep"],
  },
  {
    id: "news_current_events", type: "mate", audience: "personal", fallbackLabel: "news & current events", icon: "newspaper", appId: "news", gradientCategory: "general_knowledge",
    related: ["research_analysis", "legal_compliance", "find_local_events", "privacy_personal_data"],
    exampleChats: ["example-artemis-ii-mission", "example-eu-chat-control-law", "example-right-to-repair-laws", "example-housing-policy-dinner-discussion", "example-us-egg-prices-deep", "example-fediverse-activitypub-social-search", "example-mastodon-account-recent-posts", "example-rostock-heavy-rain-radar", "example-berlin-morning-bike-forecast", "example-berlin-weather-bike-commute", "example-lh400-flight-status-check"],
    suggestions: ["chat.new_chat_suggestions.discover_news_search", "chat.new_chat_suggestions.ai_news"],
  },
  {
    id: "diy_electronics", type: "mate", audience: "personal", fallbackLabel: "DIY & electronics", icon: "wrench", appId: "electronics", gradientCategory: "maker_prototyping", developerIntro: true,
    related: ["software_development", "learning_new_skills", "research_analysis"],
    exampleChats: ["example-usb-c-3v3-ldo", "example-buck-converters-24v-5v", "example-printable-benchy-phone-stand", "example-reference-image-3d-model", "example-right-to-repair-laws", "example-classic-car-reverse-image"],
    suggestions: ["chat.new_chat_suggestions.learn_coding", "chat.new_chat_suggestions.discover_math_calculate"],
  },
  {
    id: "privacy_personal_data", type: "context", audience: "personal", fallbackLabel: "privacy & personal data", icon: "shield-check", appId: "ai", gradientCategory: "openmates_official",
    related: ["legal_compliance", "health_wellbeing", "finance_bookkeeping", "software_development"],
    dailyInspirations: ["pii-detection", "relevant-memories", "incognito-mode", "provider-independent"],
    exampleChats: ["example-pdf-search-encryption", "example-eu-chat-control-law", "example-privacy-first-local-ai", "example-private-workspace-demo-video", "example-privacy-first-product-launch", "example-privacy-website-hero-background", "example-building-maintenance-email", "example-memory-health-medical-history", "example-memory-health-appointments", "example-framework-store-reputation-check"],
    suggestions: ["chat.new_chat_suggestions.cybersecurity", "chat.new_chat_suggestions.professional_email"],
  },
];

export const INTEREST_TAGS: InterestTag[] = DEFINITIONS.map((definition, index) => {
  const { developerIntro, dailyInspirations = [], ...tag } = definition;
  return {
    ...tag,
    labelKey: `chat.interests.${tag.id}`,
    defaultOrder: (index + 1) * 10,
    dailyInspirations: [...dailyInspirations, ...GUEST_PRODUCT_INSPIRATIONS],
    introChats: developerIntro ? ["demo-who-develops-openmates"] : [],
  };
});

export const INTEREST_TAG_IDS = INTEREST_TAGS.map((tag) => tag.id);

export const LEGACY_INTEREST_TAG_ALIASES: Record<string, InterestTagId[]> = {
  business_development: ["business_planning"],
  life_coach_psychology: ["health_wellbeing", "productivity_organization"],
  medical_health: ["health_wellbeing"],
  legal_law: ["legal_compliance"],
  finance: ["finance_bookkeeping", "personal_finances"],
  design: ["ui_ux_design", "branding_images"],
  marketing_sales: ["marketing", "sales"],
  science: ["research_analysis", "learning_new_skills"],
  history: ["research_analysis", "learning_new_skills"],
  cooking_food: ["cooking_meal_planning"],
  electrical_engineering: ["diy_electronics"],
  maker_prototyping: ["diy_electronics"],
  movies_tv: ["video_social_media"],
  activism: ["news_current_events", "legal_compliance"],
  general_knowledge: ["research_analysis", "learning_new_skills"],
  find_events: ["find_local_events", "events_networking"],
  find_restaurant: ["find_restaurants_cafes"],
  plot_charts: ["data_spreadsheets"],
  video_tutorials: ["learning_new_skills", "video_social_media"],
  build_electronics: ["diy_electronics"],
  diy_projects: ["diy_electronics"],
  create_videos: ["video_social_media", "content_creation"],
  find_travel_connections: ["find_trains_flights"],
  discuss_news: ["news_current_events"],
  discuss_videos: ["video_social_media"],
  run_code: ["software_development"],
  privacy: ["privacy_personal_data"],
  learning: ["learning_new_skills"],
  writing: ["writing_editing"],
  use_the_cli: ["software_development"],
  open_source: ["software_development"],
  read_developer_docs: ["software_development"],
  protect_my_privacy: ["privacy_personal_data"],
  summarize_documents: ["writing_editing"],
  local_life: ["find_local_events"],
  learn_anything: ["learning_new_skills"],
};

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
    const canonicalIds = isInterestTagId(tagId)
      ? [tagId]
      : (LEGACY_INTEREST_TAG_ALIASES[tagId] ?? []);
    for (const canonicalId of canonicalIds) {
      if (seen.has(canonicalId)) continue;
      seen.add(canonicalId);
      normalized.push(canonicalId);
    }
  }

  return normalized;
}
