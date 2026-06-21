// frontend/packages/ui/src/demo_chats/interestTags.ts
// Canonical interest tag registry for guest smart selection and encrypted
// account topic preferences. Keep this module pure and browser-free so web,
// CLI, tests, and future native parity can consume the same stable IDs.
// Labels are translation keys with English fallbacks until UI wiring adds the
// localized tag rail.

export type InterestTagId =
  | "software_development"
  | "use_the_cli"
  | "open_source"
  | "read_developer_docs"
  | "run_code"
  | "protect_my_privacy"
  | "summarize_documents"
  | "find_apartments"
  | "local_life"
  | "learn_anything";

export interface InterestTag {
  id: InterestTagId;
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
    id: "software_development",
    labelKey: "chat.interests.software_development",
    fallbackLabel: "software development",
    icon: "code",
    appId: "code",
    gradientCategory: "software_development",
    defaultOrder: 60,
    related: [
      "use_the_cli",
      "open_source",
      "read_developer_docs",
      "run_code",
      "protect_my_privacy",
      "summarize_documents",
    ],
    dailyInspirations: ["developer-docs-code", "cli-programmatic-use"],
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
    id: "use_the_cli",
    labelKey: "chat.interests.use_the_cli",
    fallbackLabel: "use the CLI",
    icon: "terminal",
    appId: "code",
    gradientCategory: "software_development",
    defaultOrder: 80,
    related: ["software_development", "run_code", "read_developer_docs"],
    dailyInspirations: ["cli-programmatic-use", "developer-docs-code"],
    introChats: ["demo-for-developers"],
    exampleChats: [
      "example-openmates-app-skills-embeds-docs",
      "example-python-squares-code-run",
    ],
    suggestions: [
      "chat.new_chat_suggestions.use_openmates_cli_api",
      "chat.new_chat_suggestions.learn_coding",
    ],
  },
  {
    id: "open_source",
    labelKey: "chat.interests.open_source",
    fallbackLabel: "open source",
    icon: "git-branch",
    appId: "code",
    gradientCategory: "software_development",
    defaultOrder: 70,
    related: ["software_development", "read_developer_docs", "protect_my_privacy"],
    dailyInspirations: ["developer-docs-code"],
    introChats: ["demo-who-develops-openmates", "demo-for-developers"],
    exampleChats: ["example-rust-vector-database-repos"],
    suggestions: ["chat.new_chat_suggestions.cybersecurity"],
  },
  {
    id: "read_developer_docs",
    labelKey: "chat.interests.read_developer_docs",
    fallbackLabel: "read developer docs",
    icon: "file-code",
    appId: "code",
    gradientCategory: "software_development",
    defaultOrder: 90,
    related: ["software_development", "use_the_cli", "run_code", "open_source"],
    dailyInspirations: ["developer-docs-code", "apps-skills-tools"],
    introChats: ["demo-for-developers"],
    exampleChats: [
      "example-svelte-runes-docs",
      "example-openmates-add-app-skill-doc",
    ],
    suggestions: ["chat.new_chat_suggestions.learn_coding"],
  },
  {
    id: "run_code",
    labelKey: "chat.interests.run_code",
    fallbackLabel: "run code",
    icon: "play",
    appId: "code",
    gradientCategory: "software_development",
    defaultOrder: 100,
    related: ["software_development", "use_the_cli", "read_developer_docs"],
    dailyInspirations: ["developer-docs-code", "apps-skills-tools"],
    introChats: ["demo-for-developers"],
    exampleChats: ["example-python-squares-code-run", "example-habit-garden-vite-app"],
    suggestions: [
      "chat.new_chat_suggestions.learn_coding",
      "chat.new_chat_suggestions.discover_math_calculate",
    ],
  },
  {
    id: "protect_my_privacy",
    labelKey: "chat.interests.protect_my_privacy",
    fallbackLabel: "protect my privacy",
    icon: "shield-check",
    appId: "ai",
    gradientCategory: "openmates_official",
    defaultOrder: 10,
    related: ["open_source", "software_development", "summarize_documents"],
    dailyInspirations: ["privacy-pii-replacement", "apps-skills-tools"],
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
    id: "summarize_documents",
    labelKey: "chat.interests.summarize_documents",
    fallbackLabel: "summarize documents",
    icon: "file-text",
    appId: "pdf",
    gradientCategory: "business_development",
    defaultOrder: 30,
    related: ["protect_my_privacy", "read_developer_docs", "learn_anything"],
    dailyInspirations: ["apps-skills-tools", "memory-personalization"],
    introChats: ["demo-for-everyone"],
    exampleChats: [
      "example-pdf-read-secret-word",
      "example-pdf-view-page-layout",
      "example-sqlite-strict-tables-summary",
    ],
    suggestions: ["chat.new_chat_suggestions.professional_email"],
  },
  {
    id: "find_apartments",
    labelKey: "chat.interests.find_apartments",
    fallbackLabel: "find apartments",
    icon: "home",
    appId: "home",
    gradientCategory: "business_development",
    defaultOrder: 50,
    related: ["local_life"],
    dailyInspirations: ["apps-skills-tools"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-furnished-apartments-berlin"],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "local_life",
    labelKey: "chat.interests.local_life",
    fallbackLabel: "local life",
    icon: "map-pin",
    appId: "maps",
    gradientCategory: "general_knowledge",
    defaultOrder: 40,
    related: ["find_apartments", "learn_anything"],
    dailyInspirations: ["example-chats"],
    introChats: ["demo-for-everyone"],
    exampleChats: [
      "example-quiet-cafes-tempelhofer-feld",
      "example-berlin-weather-bike-commute",
      "example-berlin-central-station-map-location",
    ],
    suggestions: ["chat.new_chat_suggestions.plan_trip_japan"],
  },
  {
    id: "learn_anything",
    labelKey: "chat.interests.learn_anything",
    fallbackLabel: "learn anything",
    icon: "sparkles",
    appId: "web",
    gradientCategory: "general_knowledge",
    defaultOrder: 20,
    related: ["summarize_documents", "local_life"],
    dailyInspirations: ["openmates-intro", "example-chats"],
    introChats: ["demo-for-everyone"],
    exampleChats: ["example-rag-explained-videos", "example-ted-talk-transcript-summary"],
    suggestions: [
      "chat.new_chat_suggestions.quantum_computing",
      "chat.new_chat_suggestions.learn_spanish",
      "chat.new_chat_suggestions.photosynthesis",
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
