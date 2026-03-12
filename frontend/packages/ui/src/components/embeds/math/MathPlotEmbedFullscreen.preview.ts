/**
 * Preview mock data for MathPlotEmbedFullscreen.
 * Access at: /dev/preview/embeds/math/MathPlotEmbedFullscreen
 */

const defaultProps = {
  plotSpec: "f(x) = sin(x)\nf(x) = cos(x)\nf(x) = tan(x)",
  title: "Trigonometric Functions",
  embedId: "preview-math-plot-fullscreen-1",
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

export const variants = {
  single_function: {
    ...defaultProps,
    plotSpec: "f(x) = x^2 - 2*x + 1",
    title: "Quadratic: x² - 2x + 1",
  },
  polynomial: {
    ...defaultProps,
    plotSpec: "f(x) = x^3 - 3*x\nf(x) = 3*x^2 - 3",
    title: "Cubic and Its Derivative",
  },
};
