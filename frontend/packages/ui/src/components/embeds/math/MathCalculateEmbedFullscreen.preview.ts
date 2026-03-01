/**
 * Preview mock data for MathCalculateEmbedFullscreen.
 * Access at: /dev/preview/embeds/math/MathCalculateEmbedFullscreen
 */

const defaultProps = {
  query: "sin(pi/4) + cos(pi/3)",
  subtitle: "Numeric mode",
  status: "finished" as const,
  results: [
    {
      expression: "sin(pi/4) + cos(pi/3)",
      result: "1.20710678118655",
      result_type: "float",
      mode: "numeric",
    },
    {
      expression: "diff(x^3, x)",
      result: "3*x**2",
      result_type: "symbolic",
      mode: "diff",
    },
  ],
  embedId: "preview-math-calculate-fullscreen-1",
  onClose: () => console.log("[Preview] Close clicked"),
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

export const variants = {
  processing: {
    ...defaultProps,
    query: "integrate(x^2, x, 0, 1)",
    status: "processing" as const,
    results: [],
  },
  error: {
    ...defaultProps,
    query: "1/0",
    status: "error" as const,
    results: [],
  },
  with_steps: {
    ...defaultProps,
    query: "solve(x^2 - 4, x)",
    results: [
      {
        expression: "solve(x^2 - 4, x)",
        result: "[-2, 2]",
        result_type: "list",
        mode: "solve",
        steps: ["x^2 - 4 = 0", "(x-2)(x+2) = 0", "x = 2 or x = -2"],
      },
    ],
  },
};
