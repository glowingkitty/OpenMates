/**
 * Fictional E2B upload-consent request fixtures (assertion code-run.e2b.upload-consent).
 * Default is unanswered; the answered variants show the read-only chosen answer.
 * Clicks dispatch `e2b-consent-preview-answer` on window so a spec can observe them.
 */
const onAnswer = (choice: string, requestId: string) => {
  window.dispatchEvent(new CustomEvent('e2b-consent-preview-answer', { detail: { choice, requestId } }));
};
const defaults = { requestId: 'preview-e2b-request', answeredChoice: null, onAnswer };
export default defaults;
export const variants = {
  'answered-allow': { ...defaults, answeredChoice: 'allow' },
  'answered-not-now': { ...defaults, answeredChoice: 'not_now' },
};
