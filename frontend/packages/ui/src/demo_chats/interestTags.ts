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
    exampleChats: [],
    suggestions: ["chat.new_chat_suggestions.professional_email", "chat.new_chat_suggestions.writing_prompts"],
  },
  {
    id: "software_development", type: "mate", audience: "work", fallbackLabel: "software development", icon: "code", appId: "code", gradientCategory: "software_development",
    related: ["automation_workflows", "websites_online_shops", "data_spreadsheets", "ui_ux_design", "research_analysis", "privacy_personal_data"],
    dailyInspirations: ["sandbox-code-execution", "cli-parity", "rest-api", "webhooks", "learning-mode"],
    exampleChats: ["example-habit-garden-web-application", "example-screenshot-to-html-pricing", "example-svelte-runes-docs", "example-rust-vector-database-repos", "example-dashboard-sidebar-svg-icons", ],
    suggestions: ["chat.new_chat_suggestions.learn_coding", "chat.new_chat_suggestions.use_openmates_cli_api", "chat.new_chat_suggestions.cybersecurity"],
  },
  {
    id: "finance_bookkeeping", type: "mate", audience: "work", fallbackLabel: "finance & bookkeeping", icon: "calculator", appId: "ai", gradientCategory: "finance",
    related: ["data_spreadsheets", "admin_operations", "legal_compliance", "business_planning", "personal_finances"],
    exampleChats: ["example-finance-cash-flow-overview", "example-vital-farms-sec-financials", ],
    suggestions: ["chat.new_chat_suggestions.stock_market", "chat.new_chat_suggestions.improve_productivity"],
  },
  {
    id: "ui_ux_design", type: "mate", audience: "work", fallbackLabel: "UI/UX design", icon: "panels-top-left", appId: "images", gradientCategory: "design",
    related: ["branding_images", "websites_online_shops", "content_creation", "software_development"],
    exampleChats: ["example-screenshot-to-html-pricing", "example-habit-garden-web-application", "example-dashboard-sidebar-svg-icons", ],
    suggestions: ["chat.new_chat_suggestions.discover_image_generate", "chat.new_chat_suggestions.writing_prompts"],
  },
  {
    id: "business_planning", type: "mate", audience: "work", fallbackLabel: "business planning", icon: "briefcase-business", appId: "ai", gradientCategory: "business_development",
    related: ["marketing", "finance_bookkeeping", "project_management", "sales", "client_work_proposals"],
    exampleChats: ["example-finance-cash-flow-overview", ],
    suggestions: ["chat.new_chat_suggestions.improve_productivity", "chat.new_chat_suggestions.professional_email"],
  },
  {
    id: "content_creation", type: "skill", audience: "work", fallbackLabel: "content creation", icon: "sparkles", appId: "ai", gradientCategory: "creative_writing",
    related: ["marketing", "writing_editing", "branding_images", "video_social_media"],
    exampleChats: ["example-ted-talk-transcript-summary", "example-rag-explained-videos", ],
    suggestions: ["chat.new_chat_suggestions.writing_prompts", "chat.new_chat_suggestions.discover_image_generate", "chat.new_chat_suggestions.discover_video_search"],
  },
  {
    id: "project_management", type: "skill", audience: "work", fallbackLabel: "project management", icon: "list-checks", appId: "tasks", gradientCategory: "business_development",
    related: ["admin_operations", "automation_workflows", "productivity_organization", "business_planning", "client_work_proposals"],
    exampleChats: [],
    suggestions: ["chat.new_chat_suggestions.improve_productivity"],
  },
  {
    id: "admin_operations", type: "skill", audience: "work", fallbackLabel: "admin & operations", icon: "clipboard-list", appId: "tasks", gradientCategory: "business_development",
    related: ["project_management", "automation_workflows", "finance_bookkeeping", "customer_support", "productivity_organization"],
    exampleChats: ["example-building-maintenance-email", ],
    suggestions: ["chat.new_chat_suggestions.improve_productivity", "chat.new_chat_suggestions.professional_email"],
  },
  {
    id: "find_local_events", type: "skill", audience: "personal", fallbackLabel: "find local events", icon: "calendar-search", appId: "events", gradientCategory: "general_knowledge",
    related: ["events_networking", "find_restaurants_cafes", "plan_trips", "health_wellbeing"],
    exampleChats: ["example-ai-workshops-meetups-berlin", ],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "plan_trips", type: "skill", audience: "personal", fallbackLabel: "plan trips", icon: "plane", appId: "travel", gradientCategory: "general_knowledge",
    related: ["find_trains_flights", "find_apartments", "find_restaurants_cafes", "find_local_events"],
    exampleChats: ["example-furnished-apartments-berlin"],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "writing_editing", type: "mate", audience: "work", fallbackLabel: "writing & editing", icon: "pen-line", appId: "mail", gradientCategory: "creative_writing",
    related: ["content_creation", "marketing", "client_work_proposals", "customer_support"],
    exampleChats: ["example-building-maintenance-email", "example-ted-talk-transcript-summary", ],
    suggestions: ["chat.new_chat_suggestions.professional_email", "chat.new_chat_suggestions.writing_prompts", "chat.new_chat_suggestions.cover_letter"],
  },
  {
    id: "sales", type: "mate", audience: "work", fallbackLabel: "sales", icon: "badge-dollar-sign", appId: "ai", gradientCategory: "marketing_sales",
    related: ["marketing", "client_work_proposals", "customer_support", "business_planning"],
    exampleChats: ["example-screenshot-to-html-pricing", ],
    suggestions: ["chat.new_chat_suggestions.professional_email", "chat.new_chat_suggestions.improve_productivity"],
  },
  {
    id: "customer_support", type: "mate", audience: "work", fallbackLabel: "customer support", icon: "messages-square", appId: "mail", gradientCategory: "business_development",
    related: ["sales", "writing_editing", "admin_operations", "productivity_organization"],
    exampleChats: ["example-building-maintenance-email", ],
    suggestions: ["chat.new_chat_suggestions.professional_email", "chat.new_chat_suggestions.improve_productivity"],
  },
  {
    id: "research_analysis", type: "mate", audience: "work", fallbackLabel: "research & analysis", icon: "search-check", appId: "web", gradientCategory: "general_knowledge",
    related: ["data_spreadsheets", "legal_compliance", "learning_new_skills", "news_current_events"],
    exampleChats: ["example-vital-farms-sec-financials", "example-right-to-repair-laws", "example-housing-policy-dinner-discussion", "example-gigantic-airplanes", "example-rust-vector-database-repos", "example-buck-converters-24v-5v", ],
    suggestions: ["chat.new_chat_suggestions.quantum_computing", "chat.new_chat_suggestions.ml_vs_ai"],
  },
  {
    id: "data_spreadsheets", type: "skill", audience: "work", fallbackLabel: "data & spreadsheets", icon: "table-2", appId: "math", gradientCategory: "science",
    related: ["research_analysis", "finance_bookkeeping", "software_development", "business_planning"],
    exampleChats: ["example-finance-cash-flow-overview", "example-vital-farms-sec-financials", "example-buck-converters-24v-5v", "example-right-to-repair-laws", ],
    suggestions: ["chat.new_chat_suggestions.discover_math_calculate", "chat.new_chat_suggestions.stock_market"],
  },
  {
    id: "legal_compliance", type: "mate", audience: "work", fallbackLabel: "legal & compliance", icon: "gavel", appId: "ai", gradientCategory: "legal_law",
    related: ["privacy_personal_data", "business_planning", "finance_bookkeeping", "research_analysis"],
    exampleChats: ["example-right-to-repair-laws", "example-vital-farms-sec-financials", ],
    suggestions: ["chat.new_chat_suggestions.cybersecurity"],
  },
  {
    id: "events_networking", type: "skill", audience: "work", fallbackLabel: "events & networking", icon: "users-round", appId: "events", gradientCategory: "marketing_sales",
    related: ["marketing", "sales", "find_local_events", "business_planning"],
    exampleChats: ["example-ai-workshops-meetups-berlin", ],
    suggestions: ["chat.new_chat_suggestions.improve_productivity"],
  },
  {
    id: "websites_online_shops", type: "skill", audience: "work", fallbackLabel: "websites & online shops", icon: "shopping-bag", appId: "code", gradientCategory: "software_development",
    related: ["software_development", "ui_ux_design", "marketing", "sales", "branding_images"],
    exampleChats: ["example-habit-garden-web-application", "example-screenshot-to-html-pricing", ],
    suggestions: ["chat.new_chat_suggestions.learn_coding", "chat.new_chat_suggestions.discover_image_generate"],
  },
  {
    id: "automation_workflows", type: "skill", audience: "work", fallbackLabel: "automation & workflows", icon: "workflow", appId: "tasks", gradientCategory: "software_development",
    related: ["project_management", "admin_operations", "software_development", "productivity_organization"],
    exampleChats: [],
    suggestions: ["chat.new_chat_suggestions.improve_productivity", "chat.new_chat_suggestions.use_openmates_cli_api"],
  },
  {
    id: "client_work_proposals", type: "mate", audience: "work", fallbackLabel: "client work & proposals", icon: "handshake", appId: "ai", gradientCategory: "business_development",
    related: ["sales", "business_planning", "writing_editing", "project_management"],
    exampleChats: [],
    suggestions: ["chat.new_chat_suggestions.professional_email", "chat.new_chat_suggestions.cover_letter"],
  },
  {
    id: "branding_images", type: "skill", audience: "work", fallbackLabel: "branding & images", icon: "image", appId: "images", gradientCategory: "design",
    related: ["ui_ux_design", "marketing", "content_creation", "video_social_media"],
    exampleChats: ["example-dashboard-sidebar-svg-icons", ],
    suggestions: ["chat.new_chat_suggestions.discover_image_generate", "chat.new_chat_suggestions.writing_prompts"],
  },
  {
    id: "video_social_media", type: "skill", audience: "work", fallbackLabel: "video & social media", icon: "video", appId: "videos", gradientCategory: "movies_tv",
    related: ["content_creation", "marketing", "branding_images", "writing_editing"],
    exampleChats: ["example-rag-explained-videos", "example-ted-talk-transcript-summary", ],
    suggestions: ["chat.new_chat_suggestions.discover_video_search", "chat.new_chat_suggestions.writing_prompts"],
  },
  {
    id: "productivity_organization", type: "context", audience: "work", fallbackLabel: "productivity & organization", icon: "check-check", appId: "tasks", gradientCategory: "life_coach_psychology",
    related: ["project_management", "admin_operations", "automation_workflows", "learning_new_skills"],
    exampleChats: ["example-balcony-plant-reminder", "example-berlin-weather-bike-commute"],
    suggestions: ["chat.new_chat_suggestions.improve_productivity"],
  },
  {
    id: "learning_new_skills", type: "context", audience: "personal", fallbackLabel: "learning new skills", icon: "graduation-cap", appId: "web", gradientCategory: "general_knowledge",
    related: ["research_analysis", "software_development", "productivity_organization", "diy_electronics"],
    exampleChats: ["example-svelte-runes-docs", "example-rag-explained-videos", "example-ai-workshops-meetups-berlin", "example-ted-talk-transcript-summary", "example-rust-vector-database-repos", "example-gigantic-airplanes", ],
    suggestions: ["chat.new_chat_suggestions.learn_coding", "chat.new_chat_suggestions.learn_spanish", "chat.new_chat_suggestions.quantum_computing"],
  },
  {
    id: "health_wellbeing", type: "mate", audience: "personal", fallbackLabel: "health & wellbeing", icon: "heart-pulse", appId: "health", gradientCategory: "medical_health",
    related: ["find_doctor_appointments", "cooking_meal_planning", "productivity_organization", "privacy_personal_data"],
    exampleChats: ["example-vegetarian-recipes-from-fridge", "example-air-fryers-retail-germany", "example-berlin-weather-bike-commute", "example-habit-garden-web-application", ],
    suggestions: ["chat.new_chat_suggestions.healthy_breakfast", "chat.new_chat_suggestions.workout_plan"],
  },
  {
    id: "find_doctor_appointments", type: "skill", audience: "personal", fallbackLabel: "find doctor appointments", icon: "calendar-heart", appId: "health", gradientCategory: "medical_health",
    related: ["health_wellbeing", "privacy_personal_data", "productivity_organization"],
    exampleChats: ["example-berlin-english-speaking-gp"],
    suggestions: ["chat.new_chat_suggestions.healthy_breakfast", "chat.new_chat_suggestions.workout_plan"],
  },
  {
    id: "find_apartments", type: "skill", audience: "personal", fallbackLabel: "find apartments", icon: "home", appId: "home", gradientCategory: "business_development",
    related: ["personal_finances", "plan_trips", "find_restaurants_cafes", "find_local_events"],
    exampleChats: ["example-furnished-apartments-berlin", ],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "find_trains_flights", type: "skill", audience: "personal", fallbackLabel: "find trains & flights", icon: "train-front", appId: "travel", gradientCategory: "general_knowledge",
    related: ["plan_trips", "find_apartments", "find_local_events"],
    exampleChats: ["example-deutschlandticket-train-fare-breakdown", ],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "find_restaurants_cafes", type: "skill", audience: "personal", fallbackLabel: "find restaurants & cafes", icon: "utensils", appId: "maps", gradientCategory: "cooking_food",
    related: ["find_local_events", "cooking_meal_planning", "plan_trips", "find_apartments"],
    exampleChats: ["example-berlin-mitte-work-friendly", "example-air-fryers-retail-germany"],
    suggestions: ["chat.new_chat_suggestions.meal_prep", "chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "personal_finances", type: "mate", audience: "personal", fallbackLabel: "personal finances", icon: "wallet-cards", appId: "ai", gradientCategory: "finance",
    related: ["finance_bookkeeping", "find_apartments", "data_spreadsheets", "privacy_personal_data"],
    exampleChats: ["example-deutschlandticket-train-fare-breakdown", ],
    suggestions: ["chat.new_chat_suggestions.stock_market"],
  },
  {
    id: "cooking_meal_planning", type: "mate", audience: "personal", fallbackLabel: "cooking & meal planning", icon: "cooking-pot", appId: "maps", gradientCategory: "cooking_food",
    related: ["health_wellbeing", "find_restaurants_cafes", "productivity_organization"],
    exampleChats: ["example-vegetarian-recipes-from-fridge", "example-air-fryers-retail-germany"],
    suggestions: ["chat.new_chat_suggestions.healthy_breakfast", "chat.new_chat_suggestions.meal_prep"],
  },
  {
    id: "news_current_events", type: "mate", audience: "personal", fallbackLabel: "news & current events", icon: "newspaper", appId: "news", gradientCategory: "general_knowledge",
    related: ["research_analysis", "legal_compliance", "find_local_events", "privacy_personal_data"],
    exampleChats: ["example-right-to-repair-laws", "example-housing-policy-dinner-discussion", "example-berlin-weather-bike-commute", ],
    suggestions: ["chat.new_chat_suggestions.discover_news_search", "chat.new_chat_suggestions.ai_news"],
  },
  {
    id: "diy_electronics", type: "mate", audience: "personal", fallbackLabel: "DIY & electronics", icon: "wrench", appId: "electronics", gradientCategory: "maker_prototyping",
    related: ["software_development", "learning_new_skills", "research_analysis"],
    exampleChats: ["example-buck-converters-24v-5v", "example-printable-benchy-phone-stand", "example-right-to-repair-laws", ],
    suggestions: ["chat.new_chat_suggestions.learn_coding", "chat.new_chat_suggestions.discover_math_calculate"],
  },
  {
    id: "privacy_personal_data", type: "context", audience: "personal", fallbackLabel: "privacy & personal data", icon: "shield-check", appId: "ai", gradientCategory: "openmates_official",
    related: ["legal_compliance", "health_wellbeing", "finance_bookkeeping", "software_development"],
    dailyInspirations: ["pii-detection", "relevant-memories", "incognito-mode", "provider-independent"],
    exampleChats: ["example-private-plumber-email", "example-building-maintenance-email", ],
    suggestions: ["chat.new_chat_suggestions.cybersecurity", "chat.new_chat_suggestions.professional_email"],
  },
];

export const INTEREST_TAGS: InterestTag[] = DEFINITIONS.map((definition, index) => {
  const { dailyInspirations = [], ...tag } = definition;
  return {
    ...tag,
    labelKey: `chat.interests.${tag.id}`,
    defaultOrder: (index + 1) * 10,
    dailyInspirations: [...dailyInspirations, ...GUEST_PRODUCT_INSPIRATIONS],
    introChats: [],
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
