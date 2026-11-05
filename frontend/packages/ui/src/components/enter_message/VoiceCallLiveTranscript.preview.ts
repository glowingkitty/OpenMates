const defaults = { text: 'What is the weather in Berlin', submitted: false, overlay: true };
export default defaults;
export const variants = {
  submitted: { ...defaults, text: 'What is the weather in Berlin tomorrow?', submitted: true },
  belowDraft: { ...defaults, overlay: false },
};
