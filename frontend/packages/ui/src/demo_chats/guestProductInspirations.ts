// frontend/packages/ui/src/demo_chats/guestProductInspirations.ts
// Logged-out product explainer inspirations for the new-chat welcome screen.
// These are public, non-personalized defaults and are ranked locally from
// guest-selected interest tags before signup.

import type { DailyInspiration } from "../stores/dailyInspirationStore";
import { OPENMATES_VIDEOS } from "./data/videos";

const INTRO_VIDEO = OPENMATES_VIDEOS["intro-en"];

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
    tags: ["learn_anything", "protect_my_privacy", "software_development"],
    order: 10,
  },
  {
    inspiration_id: "privacy-pii-replacement",
    phrase: "Hide personal data before an AI provider sees it, then reveal it locally when you need context.",
    title: "Private by Design",
    category: "openmates_official",
    content_type: "feature",
    video: null,
    generated_at: 0,
    assistant_response:
      "OpenMates can replace names, emails, addresses, and other sensitive details before a model call. The cleartext stays on your device while the AI works with placeholders.",
    follow_up_suggestions: [
      "Explain personal data replacement",
      "Show privacy examples",
      "How does encryption work?",
    ],
    feature: {
      feature_id: "privacy-pii-replacement",
      icon: "shield-check",
      title: "Personal Data Replacement",
      description: "Keep sensitive details local while AI still understands the task.",
      settings_path: null,
    },
    tags: ["protect_my_privacy", "open_source", "summarize_documents"],
    order: 20,
  },
  {
    inspiration_id: "apps-skills-tools",
    phrase: "Use apps for search, PDFs, images, code, reminders, maps, and more directly from chat.",
    title: "Apps and Skills",
    category: "openmates_official",
    content_type: "feature",
    video: null,
    generated_at: 0,
    assistant_response:
      "OpenMates apps turn chat into tools: search the web, read PDFs, generate images, run code, manage reminders, and render rich embeds without switching products.",
    follow_up_suggestions: [
      "Show app skill examples",
      "Find developer tool examples",
      "What apps are available?",
    ],
    feature: {
      feature_id: "apps-skills-tools",
      icon: "blocks",
      title: "App Skills",
      description: "Use real tools from the same chat interface.",
      settings_path: null,
    },
    tags: ["software_development", "run_code", "summarize_documents"],
    order: 30,
  },
  {
    inspiration_id: "memory-personalization",
    phrase: "Encrypted memories and settings let you choose what OpenMates may remember for each app.",
    title: "Memories You Control",
    category: "openmates_official",
    content_type: "feature",
    video: null,
    generated_at: 0,
    assistant_response:
      "OpenMates separates app memories and settings so you can decide what is saved, where it applies, and what stays off. After signup, preferences are encrypted before sync.",
    follow_up_suggestions: [
      "Explain app memories",
      "Show settings examples",
      "What is encrypted?",
    ],
    feature: {
      feature_id: "memory-personalization",
      icon: "heart",
      title: "Encrypted Memories",
      description: "Control what each app can remember.",
      settings_path: null,
    },
    tags: ["protect_my_privacy", "learn_anything"],
    order: 40,
  },
  {
    inspiration_id: "example-chats",
    phrase: "Explore public example chats to see real workflows before creating an account.",
    title: "Learn from Examples",
    category: "general_knowledge",
    content_type: "feature",
    video: null,
    generated_at: 0,
    assistant_response:
      "Example chats show complete workflows: research, coding, PDFs, private workspace demos, travel, maps, reminders, and more. Interest tags reorder them locally so the most relevant examples appear first.",
    follow_up_suggestions: [
      "Show coding examples",
      "Show privacy examples",
      "Show local life examples",
    ],
    feature: {
      feature_id: "example-chats",
      icon: "messages-square",
      title: "Example Chats",
      description: "Browse real public workflows and reuse the pattern.",
      settings_path: null,
    },
    tags: ["learn_anything", "local_life", "find_apartments"],
    order: 50,
  },
  {
    inspiration_id: "cli-programmatic-use",
    phrase: "Use OpenMates from the CLI or scripts when you want reproducible AI workflows.",
    title: "CLI and Programmatic Use",
    category: "software_development",
    content_type: "feature",
    video: null,
    generated_at: 0,
    assistant_response:
      "Developers can use OpenMates beyond the browser. The same account settings and encrypted preferences are designed to work across web, CLI, and native clients.",
    follow_up_suggestions: [
      "Use OpenMates from CLI/API",
      "Show developer examples",
      "How do encrypted settings sync?",
    ],
    feature: {
      feature_id: "cli-programmatic-use",
      icon: "terminal",
      title: "CLI Workflows",
      description: "Make AI workflows reproducible from developer tools.",
      settings_path: null,
    },
    tags: ["software_development", "use_the_cli", "open_source"],
    order: 60,
  },
  {
    inspiration_id: "developer-docs-code",
    phrase: "Ask OpenMates to read docs, compare APIs, run snippets, and explain code changes.",
    title: "Developer Docs and Code",
    category: "software_development",
    content_type: "feature",
    video: null,
    generated_at: 0,
    assistant_response:
      "For software work, OpenMates can combine web/docs search, code interpretation, PDFs, diagrams, and memory-backed preferences so the answer fits your stack.",
    follow_up_suggestions: [
      "Read developer docs",
      "Run a code example",
      "Explain a framework choice",
    ],
    feature: {
      feature_id: "developer-docs-code",
      icon: "file-code",
      title: "Docs and Code",
      description: "Research APIs and reason through code from chat.",
      settings_path: null,
    },
    tags: ["software_development", "read_developer_docs", "run_code"],
    order: 70,
  },
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
