/**
 * Preview mock data for WebsiteEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/web/WebsiteEmbedPreview
 */

/** Default props — shows a finished website embed card with metadata */
const defaultProps = {
  id: "preview-website-1",
  url: "https://svelte.dev",
  title: "Svelte — Cybernetically enhanced web apps",
  description:
    "Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.",
  favicon: "https://svelte.dev/favicon.png",
  image: "/store-examples/events-1.webp",
  status: "finished" as const,
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
  /** Processing state — shows loading while fetching metadata */
  processing: {
    id: "preview-website-processing",
    url: "https://svelte.dev/loading-page",
    status: "processing" as const,
    isMobile: false,
  },

  /** Error state */
  error: {
    id: "preview-website-error",
    url: "https://svelte.dev/broken-link",
    status: "error" as const,
    isMobile: false,
  },

  /** With all metadata filled */
  richMetadata: {
    id: "preview-website-rich",
    url: "https://github.com/sveltejs/svelte",
    title: "sveltejs/svelte: Cybernetically enhanced web apps",
    description:
      "The official Svelte repository on GitHub. Contribute to the future of frontend development.",
    favicon: "https://github.githubassets.com/favicons/favicon.svg",
    image: "/store-examples/events-1.webp",
    status: "finished" as const,
    isMobile: false,
  },

  /** Mobile view */
  mobile: {
    ...defaultProps,
    id: "preview-website-mobile",
    isMobile: true,
  },
};
