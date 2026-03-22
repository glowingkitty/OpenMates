/**
 * Preview mock data for MathCalculateEmbedPreview.
 * Access at: /dev/preview/embeds/math/MathCalculateEmbedPreview
 */

const defaultProps = {
  id: "preview-math-calculate-1",
  query: "sin(pi/4) + cos(pi/3)",
  status: "finished" as const,
  results: [
    {
      expression: "sin(pi/4) + cos(pi/3)",
      result: "1.20710678118655",
      result_type: "float",
      mode: "numeric",
    },
  ],
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants — ALL FOUR are required */
export const variants = {
  /** Loading animation */
  processing: {
    id: "preview-math-calculate-processing",
    query: "integrate(x^2, x, 0, 1)",
    status: "processing" as const,
    results: [],
    isMobile: false,
  },
  /** Error indicator */
  error: {
    id: "preview-math-calculate-error",
    query: "1/0",
    status: "error" as const,
    results: [],
    isMobile: false,
  },
  /** Cancelled state */
  cancelled: {
    id: "preview-math-calculate-cancelled",
    query: "cancelled",
    status: "cancelled" as const,
    results: [],
    isMobile: false,
  },
  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-math-calculate-mobile",
    isMobile: true,
  },
};
