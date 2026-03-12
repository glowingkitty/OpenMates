/**
 * Preview mock data for MailEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/mail
 */

/** Default props — shows a fullscreen email draft view */
const defaultProps = {
  receiver: "anna@openmates.dev",
  subject: "Project Update — Sprint 12 Review",
  content:
    "Hi Anna,\n\nThe latest sprint review went well. All tickets were closed except the auth refactor, which is carried over to Sprint 13.\n\nKey highlights:\n- Login flow redesigned (done)\n- API rate limiting added (done)\n- Auth refactor (carried over)\n\nLet me know if you have any questions.\n\nBest,\nMax",
  footer: "",
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** With navigation arrows */
  withNavigation: {
    ...defaultProps,
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },

  /** Short email */
  short: {
    receiver: "team@openmates.dev",
    subject: "Quick update",
    content: "All systems nominal. Deploy scheduled for 18:00.",
    footer: "",
    onClose: () => {},
    hasPreviousEmbed: false,
    hasNextEmbed: false,
  },
};
