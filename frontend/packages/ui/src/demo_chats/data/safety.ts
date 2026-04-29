// frontend/packages/ui/src/demo_chats/data/safety.ts
//
// Static intro chat explaining how OpenMates reduces safety risks around AI use.
// The page is intentionally plain-English and avoids claiming perfect safety:
// the product adds checks around model use, tool use, external content, and
// sensitive topics, but users still need to verify important answers.

import type { DemoChat } from "../types";

export const safetyChat: DemoChat = {
  chat_id: "demo-safety",
  slug: "safety",
  title: "demo_chats.safety.title",
  description: "demo_chats.safety.description",
  keywords: [
    "AI safety",
    "harmful instructions",
    "prompt injection",
    "hallucinations",
    "mental health",
    "image safety",
    "tool safety",
  ],
  messages: [
    {
      id: "safety-1",
      role: "assistant",
      content: "demo_chats.safety.message",
      timestamp: new Date().toISOString(),
    },
  ],
  follow_up_suggestions: [
    "demo_chats.safety.follow_up_1",
    "demo_chats.safety.follow_up_2",
    "demo_chats.safety.follow_up_3",
  ],
  metadata: {
    category: "openmates_official",
    icon_names: ["shield-alert", "brain", "file-warning"],
    featured: true,
    order: 3,
    lastUpdated: new Date().toISOString(),
  },
};
