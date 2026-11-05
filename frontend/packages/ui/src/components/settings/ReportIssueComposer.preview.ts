/**
 * Fixtures for the single-field Report Issue composer preview.
 * Handlers are inert; dictation only opens the overlay when clicked.
 */
const noop = () => undefined;

const defaultProps = {
  value: "",
  disabled: false,
  error: "",
  anonymous: false,
  canAttachImage: true,
  elementPickerActive: false,
  onAttachImage: noop,
  onPickElement: noop,
};

export default defaultProps;

export const variants = {
  filled: {
    ...defaultProps,
    value:
      "The chat list stayed empty after I logged in on my phone. Reloading did not help; the desktop app shows all chats.",
  },
  guest: { ...defaultProps, anonymous: true, canAttachImage: false },
  error: { ...defaultProps, error: "A short description is required" },
  picking: { ...defaultProps, elementPickerActive: true },
};
