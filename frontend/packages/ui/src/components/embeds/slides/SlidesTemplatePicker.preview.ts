/**
 * Preview mock data for SlidesTemplatePicker.
 * Access at: /dev/preview/embeds/slides/SlidesTemplatePicker
 * The preview has no account library, so it lists the built-in designs only.
 */
const defaultProps = {
  deckTemplate: 'builtin:plain',
  deckTheme: undefined,
  teamId: null,
  disabled: false,
  onApply: async () => {},
  onClose: () => {}
};

export default defaultProps;

export const variants = {
  /** The deck streams or is being edited: Apply stays disabled. */
  disabled: { ...defaultProps, disabled: true }
};
