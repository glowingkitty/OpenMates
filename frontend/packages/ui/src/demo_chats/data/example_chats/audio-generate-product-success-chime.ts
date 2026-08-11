// frontend/packages/ui/src/demo_chats/data/example_chats/audio-generate-product-success-chime.ts
//
// Example chat: Audio Generate Product Success Chime
// Static public fixture with a deterministic local MP3 asset.

import type { ExampleChat } from "../../types";

export const audioGenerateProductSuccessChimeChat: ExampleChat = {
  chat_id: "example-audio-generate-product-success-chime",
  slug: "audio-generate-product-success-chime",
  title: "example_chats.audio_generate_product_success_chime.title",
  summary: "example_chats.audio_generate_product_success_chime.summary",
  icon: "volume2",
  category: "design",
  keywords: ["audio generation", "sound effects", "ElevenLabs", "product sound", "OpenMates apps"],
  follow_up_suggestions: [],
  messages: [
    {
      id: "0fe80324-42f5-4b87-9e11-0b0d8f36c9d5",
      role: "user",
      content: "example_chats.audio_generate_product_success_chime.message_1",
      created_at: 1786382134
    },
    {
      id: "87bb2a45-d06b-4afa-8a4d-d2f4173647b8",
      role: "assistant",
      content: "example_chats.audio_generate_product_success_chime.message_2",
      created_at: 1786382154,
      user_message_id: "0fe80324-42f5-4b87-9e11-0b0d8f36c9d5",
      response_credits: 17,
      category: "general_knowledge",
      model_name: "Gemini 3.5 Flash-Lite"
    }
  ],
  embeds: [
    {
      embed_id: "8d96310e-a05a-41e8-a687-08ce2ce1ce9a",
      type: "app_skill_use",
      content: "app_id: audio\nskill_id: generate\ntype: audio\nstatus: finished\nprompt: \"Create a short, friendly success chime for an OpenMates workflow finishing\"\ngeneration_type: sound_effect\nprovider: ElevenLabs\nmodel: eleven_text_to_sound_v2\nmime_type: audio/mpeg\nduration_seconds: 0.679\nbyte_length: 3531\npreviewAudioUrl: /store-examples/audio-generate-product-success-chime.mp3\nfiles:\n  original:\n    size_bytes: 3531\n    format: mp3\n    mime_type: audio/mpeg\n    duration_seconds: 0.679\ngenerated_at: \"2026-08-11T02:30:00.000000+00:00\"\nwatermarking: Static public fixture",
      parent_embed_id: null,
      embed_ids: null
    }
  ],
  usage_entries: [
    {
      id: "example-audio-generate-product-success-chime-usage-1",
      type: "skill_execution",
      source: "chat",
      app_id: "ai",
      skill_id: "ask",
      model_used: "google/gemini-3.5-flash-lite",
      credits: 17,
      input_tokens: 18477,
      output_tokens: 107,
      user_input_tokens: 185,
      system_prompt_tokens: 8516,
      server_provider: "Google AI Studio",
      server_region: "US",
      chat_id: "example-audio-generate-product-success-chime",
      message_id: "0fe80324-42f5-4b87-9e11-0b0d8f36c9d5",
      created_at: 1786382147,
      updated_at: 1786382147,
      tool_inference_iterations: 1
    }
  ],
  metadata: {
    featured: true,
    order: 123,
    app_skill_examples: ["audio.generate"],
  },
};
