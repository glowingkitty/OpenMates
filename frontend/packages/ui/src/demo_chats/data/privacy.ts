// frontend/packages/ui/src/demo_chats/data/privacy.ts
//
// Static intro chat explaining OpenMates privacy protections in plain English.
// The detailed legal obligations remain in the Privacy Policy; this page focuses
// on product behavior users can understand before signing up. Content is resolved
// from i18n keys at runtime, matching the other intro chats.

import type { DemoChat } from "../types";

export const privacyChat: DemoChat = {
  chat_id: "demo-privacy",
  slug: "privacy",
  title: "demo_chats.privacy.title",
  description: "demo_chats.privacy.description",
  keywords: [
    "privacy",
    "client-side encryption",
    "PII replacement",
    "encrypted chats",
    "encrypted memories",
    "account deletion",
    "no tracking",
  ],
  messages: [
    {
      id: "privacy-1",
      role: "assistant",
      content: "demo_chats.privacy.message",
      timestamp: new Date().toISOString(),
    },
  ],
  follow_up_suggestions: [
    "demo_chats.privacy.follow_up_1",
    "demo_chats.privacy.follow_up_2",
    "demo_chats.privacy.follow_up_3",
  ],
  metadata: {
    category: "openmates_official",
    icon_names: ["lock", "shield-check", "user-check"],
    featured: true,
    order: 2,
    lastUpdated: new Date().toISOString(),
  },
};
