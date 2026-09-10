/**
 * Isolated fixture for the shared responsive fullscreen action toolbar.
 * Uses inert callbacks so every overflow action can be inspected safely.
 * Container sizing controls the Report issue label and Share placement.
 * No account, network requests, or persisted embed data are required.
 * See HeaderActionMenu.svelte for the shared chat/embed layout.
 */
const noop = () => {};

export default {
  onClose: noop,
  onReportIssue: noop,
  onShare: noop,
  showCopy: true,
  onCopy: noop,
  showDownload: true,
  onDownload: noop,
};
