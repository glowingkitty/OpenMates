/**
 * PDF view preview with intentionally absent page media.
 * Mirrors public metadata-only examples without private storage credentials.
 * Uses a synthetic id so the isolated fixture performs no embed lookup.
 * The callback records a click for the focused component contract.
 * Architecture: docs/architecture/embeds.md.
 */
export default {
  id: "legacy-preview-pdf-view-metadata",
  filename: "sample.pdf",
  pageCount: 2,
  pages: [1],
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {
    window.dispatchEvent(new CustomEvent("pdf-preview-fixture-open"));
  },
};
