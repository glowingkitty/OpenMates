// frontend/packages/ui/src/demo_chats/data/example_chats/building-maintenance-email.ts
//
// Example chat: Building maintenance email draft with private details protected
// Extracted from shared chat 6b930fc8-80f1-4135-bbd3-3cf903a418b8

import type { ExampleChat } from "../../types";

export const buildingMaintenanceEmailChat: ExampleChat = {
  chat_id: "example-building-maintenance-email",
  slug: "building-maintenance-email-private-details",
  title: "example_chats.building_maintenance_email.title",
  summary: "example_chats.building_maintenance_email.summary",
  icon: "mail",
  category: "general_knowledge",
  keywords: [
    "private details",
    "PII placeholders",
    "email draft",
    "building maintenance",
    "broken heater",
    "tenant communication",
    "privacy-first AI",
    "personal data protection",
    "OpenMates privacy",
  ],
  follow_up_suggestions: [
    "example_chats.building_maintenance_email.follow_up_1",
    "example_chats.building_maintenance_email.follow_up_2",
    "example_chats.building_maintenance_email.follow_up_3",
    "example_chats.building_maintenance_email.follow_up_4",
    "example_chats.building_maintenance_email.follow_up_5",
    "example_chats.building_maintenance_email.follow_up_6",
  ],
  messages: [
    {
      id: "f903a418b8-52660ff7-d648-46fc-ab62-f0f74681e5d6",
      role: "user",
      content: "example_chats.building_maintenance_email.user_message_1",
      created_at: 1779276855,
      category: "general_knowledge",
      pii_mappings: [
        {
          placeholder: "[EMAIL_1_.de]",
          original: "max.mustermann@posteo.de",
          type: "EMAIL",
        },
        {
          placeholder: "[EMAIL_2_com]",
          original: "sophia@proton.com",
          type: "EMAIL",
        },
        {
          placeholder: "[PHONE_1_171]",
          original: "+4917171717171",
          type: "PHONE",
        },
      ],
    },
    {
      id: "b927a479-8514-436a-96da-94843deb7e78",
      role: "assistant",
      content: "example_chats.building_maintenance_email.assistant_message_1",
      created_at: 1779276859,
      category: "general_knowledge",
      model_name: "Claude Haiku 4.5",
    },
  ],
  embeds: [
    {
      embed_id: "ec9c840d-75d8-4ab6-91ff-aa4a25ff4227",
      type: "mail",
      content: JSON.stringify({
        type: "mail",
        app_id: "mail",
        skill_id: "email",
        receiver: "[EMAIL_2_com]",
        subject: "Urgent: Broken Heater in Building - Repair Timeline Needed",
        content:
          "Dear [Recipient],\n\nI am writing to inform you about a serious issue in our building: the heater has been broken since May 15th and is no longer functioning.\n\nAs this is affecting the comfort and livability of the residents, I would appreciate your prompt attention to this matter. Could you please let me know:\n\n1. When can we expect the heater to be repaired?\n2. What is the estimated timeline for the repair work?\n\nI would prefer to discuss this matter further and would be grateful if you could call me back at [PHONE_1_171] at your earliest convenience.\n\nThank you for your immediate attention to this urgent issue.\n\nBest regards,\n[Your Name]",
        footer: "Sent from [EMAIL_1_.de]",
        embed_ref: "urgent-broken-heater-in-building-repair-timeline-ec9c84",
        status: "finished",
      }),
      parent_embed_id: null,
      embed_ids: null,
    },
  ],
  metadata: {
    featured: true,
    order: 8,
    app_skill_examples: ["mail.search"],
  },
};
