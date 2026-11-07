/**
 * Pure URL classification for pasted links (YouTube video, GitHub repository,
 * YouTube video id). Import-free so the Rust twin (web_composer/url_kinds.rs) can
 * be checked against it with generated vectors.
 */

/**
 * YouTube URL patterns for detection
 * Matches:
 * - https://www.youtube.com/watch?v=VIDEO_ID
 * - https://m.youtube.com/watch?v=VIDEO_ID (mobile)
 * - https://youtu.be/VIDEO_ID
 * - https://www.youtube.com/embed/VIDEO_ID
 * - https://www.youtube.com/shorts/VIDEO_ID
 * - https://www.youtube.com/v/VIDEO_ID (legacy)
 */
const YOUTUBE_URL_PATTERN =
  /^https?:\/\/(www\.|m\.)?(youtube\.com\/(watch\?v=|embed\/|shorts\/|v\/)|youtu\.be\/)/i;
const GITHUB_REPO_URL_PATTERN = /^https?:\/\/(www\.)?github\.com\/[^/\s]+\/[^/\s?#]+\/?(?:[?#].*)?$/i;

/**
 * Check if a URL is a YouTube video URL
 * @param url The URL to check
 * @returns true if it's a YouTube URL
 */
export function isYouTubeUrl(url: string): boolean {
  return YOUTUBE_URL_PATTERN.test(url);
}

export function isGitHubRepoUrl(url: string): boolean {
  if (!GITHUB_REPO_URL_PATTERN.test(url)) return false;
  try {
    const parsed = new URL(url);
    const parts = parsed.pathname.replace(/\/$/, "").split("/").filter(Boolean);
    if (parts.length !== 2) return false;
    const [owner, repo] = parts;
    return Boolean(owner && repo && !["features", "topics", "collections", "marketplace", "explore", "login"].includes(owner));
  } catch {
    return false;
  }
}

/**
 * Extracts the 11-character YouTube video ID from a URL without any API call.
 * Supports all common YouTube URL formats.
 *
 * @param url Any YouTube URL
 * @returns The 11-character video ID, or null if not found
 */
export function extractYouTubeVideoId(url: string): string | null {
  // Ordered patterns matching all known YouTube URL formats
  const patterns = [
    /[?&]v=([a-zA-Z0-9_-]{11})/, // ?v= or &v=
    /youtu\.be\/([a-zA-Z0-9_-]{11})/, // youtu.be/
    /youtube\.com\/embed\/([a-zA-Z0-9_-]{11})/, // /embed/
    /youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})/, // /shorts/
    /youtube\.com\/v\/([a-zA-Z0-9_-]{11})/, // /v/
  ];
  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match) return match[1];
  }
  return null;
}
