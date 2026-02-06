import type { DemoChat } from "../types";

/**
 * Who Develops OpenMates demo chat - Translation keys from i18n/locales/{locale}.json
 *
 * This demo chat introduces the creator and philosophy behind OpenMates:
 * - Marco (glowingkitty) as creator
 * - Frustrations with big tech that motivated the project
 * - Core values: user interests first, privacy, open source
 * - Invitation to join as user or contributor
 *
 * All content is translated at runtime using translateDemoChat()
 */
export const whoDevelopsOpenmatesChat: DemoChat = {
  chat_id: "demo-who-develops-openmates",
  slug: "who-develops-openmates",
  title: "demo_chats.who_develops_openmates.title.text",
  description: "demo_chats.who_develops_openmates.description.text",
  keywords: [
    "creator",
    "developer",
    "open source",
    "glowingkitty",
    "Marco",
    "philosophy",
    "user interests",
    "contributor",
  ],
  messages: [
    {
      id: "who-develops-openmates-1",
      role: "assistant",
      content: "demo_chats.who_develops_openmates.message.text",
      timestamp: new Date().toISOString(),
    },
  ],
  follow_up_suggestions: [
    "demo_chats.who_develops_openmates.follow_up_1.text",
    "demo_chats.who_develops_openmates.follow_up_2.text",
    "demo_chats.who_develops_openmates.follow_up_3.text",
  ],
  metadata: {
    category: "openmates_official", // Official OpenMates category - shows favicon, not mate profile
    icon_names: ["user", "heart", "coding"], // Icons for person/passion/development
    featured: true,
    order: 3,
    lastUpdated: new Date().toISOString(),
  },
};
