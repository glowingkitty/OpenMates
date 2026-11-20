/** Recorded landing interaction: the real event embed (app) or the public package's own (standalone website). */
export default { section: 'actionable', active: true, language: 'en' };
export const variants = {
  german: { section: 'actionable', active: true, language: 'de' },
  standalone: { section: 'actionable', active: true, language: 'en', standalone: true },
  standaloneGerman: { section: 'actionable', active: true, language: 'de', standalone: true },
  paused: { section: 'actionable', active: false, language: 'en' },
  privacy: { section: 'privacy', active: true, language: 'en' },
};
