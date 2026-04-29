/**
 * Central video registry for OpenMates intro chats, announcements, and tips.
 * All video URLs are defined here once — demo chat data files and backend
 * scripts reference entries by key instead of duplicating URLs.
 */

export interface OpenMatesVideo {
  id: string;
  hls_url: string;
  mp4_url: string;
  thumbnail_url: string;
  teaser_url?: string;
  teaser_webp_url?: string;
  start_time?: number;
  background_frames?: string[];
}

const INTRO_BACKGROUND_FRAMES = Array.from(
  { length: 12 },
  (_, i) => `/intro-frames/frame-${String(i + 1).padStart(2, "0")}.webp`,
);

export const OPENMATES_VIDEOS: Record<string, OpenMatesVideo> = {
  "intro-en": {
    id: "vi43o2FOchAMACeh5blHumCa",
    hls_url:
      "https://vod.api.video/vod/vi43o2FOchAMACeh5blHumCa/hls/manifest.m3u8",
    mp4_url:
      "https://vod.api.video/vod/vi43o2FOchAMACeh5blHumCa/mp4/source.mp4",
    thumbnail_url:
      "https://vod.api.video/vod/vi43o2FOchAMACeh5blHumCa/thumbnail.jpg",
    teaser_url: "/intro-teasers/openmates-intro-teaser.webm",
    teaser_webp_url: "/intro-teasers/openmates-intro-teaser.webp",
    start_time: 17,
    background_frames: INTRO_BACKGROUND_FRAMES,
  },
  "intro-de": {
    id: "vi1LdNC1NrHlKyANrOUDsfX6",
    hls_url:
      "https://vod.api.video/vod/vi1LdNC1NrHlKyANrOUDsfX6/hls/manifest.m3u8",
    mp4_url:
      "https://vod.api.video/vod/vi1LdNC1NrHlKyANrOUDsfX6/mp4/source.mp4",
    thumbnail_url:
      "https://vod.api.video/vod/vi1LdNC1NrHlKyANrOUDsfX6/thumbnail.jpg",
    teaser_url: "/intro-teasers/openmates-intro-teaser.webm",
    teaser_webp_url: "/intro-teasers/openmates-intro-teaser.webp",
    start_time: 17,
    background_frames: INTRO_BACKGROUND_FRAMES,
  },
} as const;

export function getVideoForLocale(
  videoKey: string,
  locale: string,
): OpenMatesVideo | null {
  const langPrefix = locale?.slice(0, 2) ?? "en";
  return (
    OPENMATES_VIDEOS[`${videoKey}-${langPrefix}`] ??
    OPENMATES_VIDEOS[videoKey] ??
    OPENMATES_VIDEOS[`${videoKey}-en`] ??
    null
  );
}
