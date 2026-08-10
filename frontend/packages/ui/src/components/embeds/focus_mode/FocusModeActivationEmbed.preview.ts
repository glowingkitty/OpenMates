/**
 * Deterministic preview fixtures for the focus-mode activation history embed.
 * Covers the stable activated state without starting the production countdown.
 */

const defaultProps = {
  id: "preview-focus-mode-activation",
  focusId: "jobs-career_insights",
  appId: "jobs",
  focusModeName: "Career Insights",
  alreadyActive: true,
  onReject: () => {},
  onActivate: () => {},
  onDeactivate: () => {},
  onDetails: () => {},
  onContextMenu: () => {},
};

export default defaultProps;

export const variants = {
  countdown: {
    ...defaultProps,
    id: "preview-focus-mode-countdown",
    alreadyActive: false,
  },
};
