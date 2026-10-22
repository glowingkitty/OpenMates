/**
 * Preview mock data for NewsEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/news/NewsEmbedPreview
 */

/** Default props — shows a finished news article embed card */
const defaultProps = {
  id: "preview-news-1",
  url: "https://techcrunch.com/2025/svelte-5-released",
  title: "Svelte 5 Officially Released with Revolutionary Runes System",
  description:
    "The Svelte team has announced the stable release of Svelte 5, featuring the new runes reactivity system that promises better performance and developer experience.",
  favicon: "/favicon.png",
  image: "/store-examples/events-1.webp",
  status: "finished" as const,
  publicationDate: "2026-10-21",
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  chat: { ...defaultProps, resultContext: 'chat', onFullscreen: () => console.info('[Preview] result expanded') },
  results: { ...defaultProps, resultContext: 'results', onFullscreen: () => console.info('[Preview] result expanded') },
  noImage: { ...defaultProps, image: '', description: 'A concise source description without an image. Read useful context about this source, including the central topic, the information available and why the result may help answer your question. The card keeps this description readable while remaining within its compact bounds.' },
  brokenImage: { ...defaultProps, image: '/missing-result-preview-image.webp' },
  longTitle: { ...defaultProps, title: 'A deliberately long result title that remains readable in narrow cards without overflowing the page or hiding the source identity' },
  /** Processing state — shows loading while fetching article */
  processing: {
    id: "preview-news-processing",
    url: "https://techcrunch.com/news/loading",
    favicon: "/favicon.png",
    image: "/store-examples/events-1.webp",
    status: "processing" as const,
    isMobile: false,
  },

  /** Error state */
  error: {
    id: "preview-news-error",
    url: "https://techcrunch.com/news/not-found",
    favicon: "/favicon.png",
    image: "/store-examples/events-1.webp",
    status: "error" as const,
    isMobile: false,
  },

  /** With all metadata */
  richMetadata: {
    id: "preview-news-rich",
    url: "https://techcrunch.com/2025/svelte-5-launch",
    title: "Svelte 5 Launches to Wide Acclaim",
    description:
      "The latest version of the popular frontend framework brings fundamental changes to reactivity with the introduction of runes.",
    favicon: "/favicon.png",
    image: "/store-examples/events-1.webp",
    status: "finished" as const,
    isMobile: false,
  },

  /** Mobile view */
  mobile: {
    ...defaultProps,
    id: "preview-news-mobile",
    isMobile: true,
  },
};
