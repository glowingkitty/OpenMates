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
  projectConsent: {
    ...defaultProps,
    id: "preview-project-consent",
    focusId: "project-11111111-1111-4111-8111-111111111111",
    appId: "projects",
    focusModeName: "Work on Garden notes",
    alreadyActive: false,
    pendingUntil: Date.now() + 4000,
    onAcceptProject: async () => {},
  },
  projectApproval: {
    ...defaultProps,
    id: "preview-project-approval",
    focusId: "project-11111111-1111-4111-8111-111111111111",
    appId: "projects",
    focusModeName: "Work on Garden notes",
    alreadyActive: false,
    pendingUntil: Date.now() + 20 * 60_000,
    previewActivationPolicy: "approval",
    onAcceptProject: async () => {},
  },
  countdown: {
    ...defaultProps,
    id: "preview-focus-mode-countdown",
    alreadyActive: false,
    pendingUntil: Date.now() + 4000,
  },
};
