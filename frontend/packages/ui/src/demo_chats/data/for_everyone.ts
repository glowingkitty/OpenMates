import type { DemoChat } from "../types";
import { OPENMATES_VIDEOS } from "./videos";

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

const introVideo = OPENMATES_VIDEOS["intro-en"];

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
    category: "openmates_official",
    icon_names: ["hand", "rocket", "sparkles"],
    featured: true,
    order: 1,
    lastUpdated: new Date().toISOString(),
    video_key: "intro",
    video_hls_url: introVideo.hls_url,
    video_mp4_url: introVideo.mp4_url,
    video_thumbnail_url: introVideo.thumbnail_url,
    video_teaser_url: introVideo.teaser_url,
    video_teaser_webp_url: introVideo.teaser_webp_url,
    video_start_time: introVideo.start_time,
    background_frames: introVideo.background_frames,
  },
};
