// frontend/packages/openmates-cli/src/urlEmbed.ts
/**
 * CLI URL embed preprocessing.
 *
 * Purpose: mirror browser message sending for plain URLs typed in user messages.
 * Architecture: converts standalone URLs into prepared website/video embeds and
 * markdown embed references before the message is sent over WebSocket.
 * Privacy: metadata is not fetched from third-party URLs in the CLI path; the
 * original URL is stored as encrypted embed content and reference fallback only.
 */

import {
  createEmbedRef,
  createEmbedReferenceBlock,
  generateEmbedId,
  toonEncodeContent,
  type PreparedEmbed,
} from "./embedCreator.js";

const URL_PATTERN = /\bhttps?:\/\/[^\s<>()`"']+/gi;
const FENCED_BLOCK_PATTERN = /(```[\s\S]*?```)/g;
const TRAILING_URL_PUNCTUATION = /[.,!?;:]+$/;

export interface PreparedUrlEmbeds {
  message: string;
  embeds: PreparedEmbed[];
}

function trimTrailingUrlPunctuation(rawUrl: string): { url: string; suffix: string } {
  let url = rawUrl;
  let suffix = "";

  const punctuation = url.match(TRAILING_URL_PUNCTUATION)?.[0] ?? "";
  if (punctuation) {
    url = url.slice(0, -punctuation.length);
    suffix = punctuation + suffix;
  }

  while (url.endsWith(")")) {
    const openCount = (url.match(/\(/g) ?? []).length;
    const closeCount = (url.match(/\)/g) ?? []).length;
    if (closeCount <= openCount) break;
    url = url.slice(0, -1);
    suffix = `)${suffix}`;
  }

  return { url, suffix };
}

function createWebsiteEmbed(url: string): PreparedEmbed {
  const embedId = generateEmbedId();
  const embedRef = createEmbedRef("website", `${url}:${embedId}`);
  const content = toonEncodeContent({
    url,
    embed_ref: embedRef,
    title: null,
    description: null,
    favicon: null,
    image: null,
    site_name: null,
    fetched_at: new Date().toISOString(),
  });

  return {
    embedId,
    embedRef,
    type: "web-website",
    content,
    textPreview: url,
    status: "finished",
  };
}

function youtubeVideoId(url: string): string | null {
  const parsed = new URL(url);
  const host = parsed.hostname.toLowerCase();
  let videoId: string | null = null;
  if (host === 'youtu.be') videoId = parsed.pathname.split('/')[1] ?? null;
  if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'www.youtube-nocookie.com', 'youtube-nocookie.com'].includes(host)) {
    videoId = parsed.pathname === '/watch'
      ? parsed.searchParams.get('v')
      : /^\/(?:embed|shorts|v)\/([^/]+)/.exec(parsed.pathname)?.[1] ?? null;
  }
  return videoId && /^[A-Za-z0-9_-]{11}$/.test(videoId) ? videoId : null;
}

function createVideoEmbed(url: string, videoId: string): PreparedEmbed {
  const embedId = generateEmbedId();
  const embedRef = createEmbedRef('video', `${url}:${embedId}`);
  return {
    embedId,
    embedRef,
    type: 'videos-video',
    content: toonEncodeContent({
      url, video_id: videoId, embed_ref: embedRef,
      title: null, description: null, thumbnail: null,
      channel_name: null, duration_seconds: null,
    }),
    textPreview: url,
    status: 'finished',
  };
}

function replaceUrlsInText(text: string, embeds: PreparedEmbed[]): string {
  return text.replace(URL_PATTERN, (rawUrl) => {
    const { url, suffix } = trimTrailingUrlPunctuation(rawUrl);
    if (!url) return rawUrl;

    try {
      // Validate rather than guessing whether a matched token is actually a URL.
      new URL(url);
    } catch {
      return rawUrl;
    }

    const videoId = youtubeVideoId(url);
    const embed = videoId ? createVideoEmbed(url, videoId) : createWebsiteEmbed(url);
    embeds.push(embed);
    return `${createEmbedReferenceBlock(embed.embedRef ?? embed.embedId)}${suffix}`;
  });
}

export function prepareUrlEmbeds(message: string): PreparedUrlEmbeds {
  const embeds: PreparedEmbed[] = [];
  const parts = message.split(FENCED_BLOCK_PATTERN);
  const processed = parts
    .map((part, index) => {
      const isFence = index % 2 === 1 && part.startsWith("```");
      return isFence ? part : replaceUrlsInText(part, embeds);
    })
    .join("");

  return { message: processed, embeds };
}
