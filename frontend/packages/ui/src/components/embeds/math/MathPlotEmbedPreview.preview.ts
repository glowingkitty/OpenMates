/**
 * Preview mock data for MathPlotEmbedPreview.
 * Access at: /dev/preview/embeds/math/MathPlotEmbedPreview
 */

const defaultProps = {
  id: "preview-math-plot-1",
  plotSpec: "f(x) = sin(x)\nf(x) = cos(x)",
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants — ALL FOUR are required */
export const variants = {
  processing: {
    id: "preview-math-plot-processing",
    plotSpec: "",
    status: "processing" as const,
    isMobile: false,
  },
  error: {
    id: "preview-math-plot-error",
    plotSpec: "invalid_func(",
    status: "error" as const,
    isMobile: false,
  },
  cancelled: {
    id: "preview-math-plot-cancelled",
    plotSpec: "",
    status: "cancelled" as const,
    isMobile: false,
  },
  mobile: {
    ...defaultProps,
    id: "preview-math-plot-mobile",
    isMobile: true,
  },
};
