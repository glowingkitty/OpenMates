/**
 * Fictional run-start consent dialog fixtures (assertion code-run.e2b.upload-consent).
 * Choices dispatch `e2b-consent-preview-answer` on window so a spec can observe them.
 */
const onAnswer = (choice: string) => {
  window.dispatchEvent(new CustomEvent('e2b-consent-preview-answer', { detail: { choice } }));
};
const defaults = { open: true, onAnswer, onDismiss: () => onAnswer('dismissed') };
export default defaults;
export const variants = {};
