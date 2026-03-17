/**
 * Preview mock data for MailSearchEmbedPreview.
 *
 * Provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/mail/search
 */

const sampleResults = [
  {
    uid: "1",
    subject: "Invoice #1042 - OpenMates B.V.",
    from: "billing@acme.com",
    to: "admin@openmates.org",
    snippet:
      "Please find attached invoice #1042 for services rendered in February 2026.",
    date: "Thu, 28 Feb 2026 10:00:00 +0100",
    timestamp: 1740733200,
    is_unread: true,
  },
  {
    uid: "2",
    subject: "Server maintenance scheduled",
    from: "ops@provider.com",
    to: "admin@openmates.org",
    snippet: "Scheduled maintenance window: Saturday 22:00-02:00 UTC.",
    date: "Wed, 27 Feb 2026 14:30:00 +0100",
    timestamp: 1740659400,
    is_unread: false,
  },
  {
    uid: "3",
    subject: "New contributor joined",
    from: "github-noreply@github.com",
    to: "admin@openmates.org",
    snippet:
      "A new contributor has opened a pull request in OpenMates/OpenMates.",
    date: "Mon, 25 Feb 2026 08:00:00 +0100",
    timestamp: 1740470400,
    is_unread: false,
  },
];

/** Default props — finished search with results */
const defaultProps = {
  id: "preview-mail-search-1",
  query: "invoice",
  provider: "Proton Mail Bridge",
  status: "finished" as const,
  results: sampleResults,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  processing: {
    id: "preview-mail-search-processing",
    query: "invoice",
    provider: "Proton Mail Bridge",
    status: "processing" as const,
    results: [],
    isMobile: false,
    onFullscreen: () => {},
  },

  recent: {
    id: "preview-mail-search-recent",
    query: "Recent emails",
    provider: "Proton Mail Bridge",
    status: "finished" as const,
    results: sampleResults,
    isMobile: false,
    onFullscreen: () => {},
  },

  empty: {
    id: "preview-mail-search-empty",
    query: "proton bridge xyz",
    provider: "Proton Mail Bridge",
    status: "finished" as const,
    results: [],
    isMobile: false,
    onFullscreen: () => {},
  },

  mobile: {
    ...defaultProps,
    id: "preview-mail-search-mobile",
    isMobile: true,
  },
};
