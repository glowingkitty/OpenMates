/**
 * Fixtures for the Report Issue screenshot thumbnails: none, one and three
 * attached images (tiny inline SVG data URLs, no network).
 */
const swatch = (color: string) =>
  `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144"><rect width="144" height="144" fill="${color}"/></svg>`,
  )}`;

const defaultProps = {
  screenshots: [] as string[],
  error: "",
  disabled: false,
  maxCount: 5,
  onRemove: () => undefined,
};

export default defaultProps;

export const variants = {
  none: defaultProps,
  one: { ...defaultProps, screenshots: [swatch("#4c8bf5")] },
  three: {
    ...defaultProps,
    screenshots: [swatch("#4c8bf5"), swatch("#34a853"), swatch("#f5a623")],
  },
  limit: {
    ...defaultProps,
    screenshots: [
      swatch("#4c8bf5"),
      swatch("#34a853"),
      swatch("#f5a623"),
      swatch("#9c27b0"),
      swatch("#e53935"),
    ],
    error: "You can attach up to 5 screenshots.",
  },
};
