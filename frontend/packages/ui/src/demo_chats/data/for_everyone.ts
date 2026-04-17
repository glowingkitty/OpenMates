import type { DemoChat } from "../types";

/**
 * For Everyone demo chat - Translation keys from i18n/locales/{locale}.json
 *
 * This is the main introductory demo chat that explains OpenMates' core value proposition:
 * - Team of specialized AI chatbots
 * - Apps with skills, focus modes, and memories
 * - Privacy & encryption features
 * - Pay-per-use pricing model
 *
 * All content is translated at runtime using translateDemoChat()
 */
export const forEveryoneChat: DemoChat = {
  chat_id: "demo-for-everyone",
  slug: "for-everyone",
  title: "demo_chats.for_everyone.title",
  description: "demo_chats.for_everyone.description",
  keywords: [
    "AI assistant",
    "getting started",
    "introduction",
    "OpenMates features",
    "apps",
    "privacy",
    "encryption",
    "pricing",
  ],
  messages: [
    {
      id: "for-everyone-1",
      role: "assistant",
      content: "demo_chats.for_everyone.message",
      timestamp: new Date().toISOString(),
    },
  ],
  follow_up_suggestions: [
    "demo_chats.for_everyone.follow_up_1",
    "demo_chats.for_everyone.follow_up_2",
    "demo_chats.for_everyone.follow_up_3",
  ],
  metadata: {
    category: "openmates_official", // Official OpenMates category - shows favicon, not mate profile
    icon_names: ["hand", "rocket", "sparkles"], // Lucide icons for welcome/introduction
    featured: true,
    order: 1,
    lastUpdated: new Date().toISOString(),
    video_hls_url: "https://vod.api.video/vod/vi43o2FOchAMACeh5blHumCa/hls/manifest.m3u8",
    video_mp4_url: "https://vod.api.video/vod/vi43o2FOchAMACeh5blHumCa/mp4/source.mp4",
    video_thumbnail_url: "https://vod.api.video/vod/vi43o2FOchAMACeh5blHumCa/thumbnail.jpg",
    video_start_time: 17,
    // Crossfading Ken-Burns slideshow for the chat header background.
    // Replaces autoplay video to avoid per-visitor video delivery cost.
    // Real video remains available via the header play button (fullscreen).
    background_frames: [
      "/intro-frames/frame-01.webp",
      "/intro-frames/frame-02.webp",
      "/intro-frames/frame-03.webp",
      "/intro-frames/frame-04.webp",
      "/intro-frames/frame-05.webp",
      "/intro-frames/frame-06.webp",
      "/intro-frames/frame-07.webp",
      "/intro-frames/frame-08.webp",
      "/intro-frames/frame-09.webp",
      "/intro-frames/frame-10.webp",
      "/intro-frames/frame-11.webp",
      "/intro-frames/frame-12.webp",
    ],
  },
};
