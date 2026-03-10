/**
 * Preview mock data for MailEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/mail
 */

/** Default props — shows a finished email draft embed */
const defaultProps = {
  id: "preview-mail-1",
  receiver: "anna@openmates.dev",
  subject: "Project Update — Sprint 12 Review",
  content:
    "Hi Anna,\n\nThe latest sprint review went well. All tickets were closed except the auth refactor, which is carried over to Sprint 13.\n\nKey highlights:\n- Login flow redesigned (done)\n- API rate limiting added (done)\n- Auth refactor (carried over)\n\nLet me know if you have any questions.\n\nBest,\nMax",
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Processing state — email being composed */
  processing: {
    id: "preview-mail-processing",
    status: "processing" as const,
    isMobile: false,
  },

  /** Error state */
  error: {
    id: "preview-mail-error",
    status: "error" as const,
    isMobile: false,
  },

  /** Short email */
  short: {
    id: "preview-mail-short",
    receiver: "team@openmates.dev",
    subject: "Quick update",
    content: "All systems nominal. Deploy scheduled for 18:00.",
    status: "finished" as const,
    isMobile: false,
  },

  /** Mobile view */
  mobile: {
    ...defaultProps,
    id: "preview-mail-mobile",
    isMobile: true,
  },
};
