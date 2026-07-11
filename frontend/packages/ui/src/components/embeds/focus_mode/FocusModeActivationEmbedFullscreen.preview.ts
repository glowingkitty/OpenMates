/**
 * Deterministic preview fixture for focus-mode activation fullscreen history.
 * Uses the same decoded content contract emitted by the activation renderer.
 */

const defaultProps = {
  data: {
    decodedContent: {
      focus_id: "jobs-career_insights",
      app_id: "jobs",
      focus_mode_name: "Career Insights",
    },
    attrs: {},
  },
  embedId: "preview-focus-mode-activation",
  onClose: () => {},
};

export default defaultProps;
