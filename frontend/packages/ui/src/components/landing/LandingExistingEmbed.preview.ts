/** The real event embed used by the landing story (FOSDEM demonstration event). */
const defaultProps = { mode: 'preview', activate: false, language: 'en', onFullscreen: () => {} };
export default defaultProps;
export const variants = {
  fullscreen: { mode: 'fullscreen', language: 'en', showCalendar: false },
  calendar: { mode: 'fullscreen', language: 'en', showCalendar: true },
  german: { ...defaultProps, language: 'de' },
};
