/** Local-only newsletter form fixture; component proof intercepts relative /v1 requests. */
const defaultProps = {
  apiBaseUrl: '',
  websiteBaseUrl: 'http://localhost:5173',
  language: 'en' as const,
};

export default defaultProps;

export const variants = {
  German: { ...defaultProps, language: 'de' as const },
};
