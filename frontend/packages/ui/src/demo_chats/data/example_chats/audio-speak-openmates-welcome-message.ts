// frontend/packages/ui/src/demo_chats/data/example_chats/audio-speak-openmates-welcome-message.ts
//
// Example chat: Audio Speak OpenMates Welcome Message
// Static public fixture derived from a real generated-audio dev API result.

import type { ExampleChat } from "../../types";

export const audioSpeakOpenmatesWelcomeMessageChat: ExampleChat = {
  chat_id: "example-audio-speak-openmates-welcome-message",
  slug: "audio-speak-openmates-welcome-message",
  title: "example_chats.audio_speak_friendly_welcome_message.title",
  summary: "example_chats.audio_speak_friendly_welcome_message.summary",
  icon: "volume2",
  category: "design",
  keywords: ["text to speech", "ElevenLabs", "speech generation", "voice narration", "OpenMates apps"],
  follow_up_suggestions: [],
  messages: [
    {
      id: "b39cb42f-ec3e-45ec-9339-801b54c7cb03",
      role: "user",
      content: "example_chats.audio_speak_friendly_welcome_message.message_1",
      created_at: 1786382241
    },
    {
      id: "892c94f0-2c44-4d72-9c92-f27db186a103",
      role: "assistant",
      content: "example_chats.audio_speak_friendly_welcome_message.message_2",
      created_at: 1786382255,
      user_message_id: "b39cb42f-ec3e-45ec-9339-801b54c7cb03",
      response_credits: 37,
      category: "onboarding_support",
      model_name: "Gemini 3.5 Flash-Lite"
    }
  ],
  embeds: [
    {
      embed_id: "463ace0f-02f9-43c2-94ee-cf385162bb75",
      type: "app_skill_use",
      content: "app_id: audio\nskill_id: speak\ntype: audio\nstatus: finished\nprompt: \"Say this as a warm, natural welcome message: Welcome back to OpenMates. Your workspace is ready whenever you are.\"\ntext_preview: \"Welcome back to OpenMates. Your workspace is ready whenever you are.\"\ntext: \"Welcome back to OpenMates. Your workspace is ready whenever you are.\"\ngeneration_type: speech\nvoice: warm_neutral\nprovider: ElevenLabs\nmodel: eleven_multilingual_v2\nmime_type: audio/mpeg\nduration_seconds: 4.624\nbyte_length: 74440\npreviewAudioUrl: /store-examples/audio-speak-openmates-welcome-message.mp3\nfiles:\n  original:\n    size_bytes: 74440\n    format: mp3\n    mime_type: audio/mpeg\n    duration_seconds: 4.624\ngenerated_at: \"2026-08-09T23:36:02.000000+00:00\"\nwatermarking: Static public fixture derived from real generated output",
      parent_embed_id: null,
      embed_ids: null
    }
  ],
  usage_entries: [
    {
      id: "example-audio-speak-openmates-welcome-message-usage-1",
      type: "skill_execution",
      source: "chat",
      app_id: "ai",
      skill_id: "ask",
      model_used: "google/gemini-3.5-flash-lite",
      credits: 18,
      input_tokens: 19599,
      output_tokens: 69,
      user_input_tokens: 181,
      system_prompt_tokens: 9066,
      server_provider: "Google AI Studio",
      server_region: "US",
      chat_id: "example-audio-speak-openmates-welcome-message",
      message_id: "b39cb42f-ec3e-45ec-9339-801b54c7cb03",
      created_at: 1786382249,
      updated_at: 1786382249,
      tool_inference_iterations: 1
    },
    {
      id: "example-audio-speak-openmates-welcome-message-usage-2",
      type: "skill_execution",
      source: "chat",
      app_id: "audio",
      skill_id: "speak",
      model_used: "elevenlabs/eleven_multilingual_v2",
      credits: 19,
      server_provider: "ElevenLabs",
      server_region: "US",
      chat_id: "example-audio-speak-openmates-welcome-message",
      message_id: "b39cb42f-ec3e-45ec-9339-801b54c7cb03",
      created_at: 1786382246,
      updated_at: 1786382246,
      tool_inference_iterations: 0,
      code_run_duration_seconds: 4.624
    }
  ],
  metadata: {
    featured: true,
    order: 124,
    app_skill_examples: ["audio.speak"],
  },
};
