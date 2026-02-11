import type { DemoChat } from "../types";

/**
 * For Developers demo chat - Translation keys from i18n/locales/{locale}.json
 *
 * This demo chat introduces OpenMates to software developers, highlighting:
 * - No complicated MCP server setups needed
 * - REST API access to all App skills
 * - CLI, pip & npm packages (planned)
 * - Privacy & encryption for code and project details
 * - Open source as protection against enshittification
 *
 * All content is translated at runtime using translateDemoChat()
 */
export const forDevelopersChat: DemoChat = {
  chat_id: "demo-for-developers",
  slug: "for-developers",
  title: "demo_chats.for_developers.title.text",
  description: "demo_chats.for_developers.description.text",
  keywords: [
    "developers",
    "REST API",
    "CLI",
    "npm",
    "pip",
    "MCP",
    "code",
    "open source",
    "self-host",
    "privacy",
  ],
  messages: [
    {
      id: "for-developers-1",
      role: "assistant",
      content: "demo_chats.for_developers.message.text",
      timestamp: new Date().toISOString(),
    },
  ],
  follow_up_suggestions: [
    "demo_chats.for_developers.follow_up_1.text",
    "demo_chats.for_developers.follow_up_2.text",
    "demo_chats.for_developers.follow_up_3.text",
  ],
  metadata: {
    category: "openmates_official", // Official OpenMates category - shows favicon, not mate profile
    icon_names: ["code", "terminal", "shield-check"], // Lucide icons for code/terminal/security
    featured: true,
    order: 2,
    lastUpdated: new Date().toISOString(),
  },
};
