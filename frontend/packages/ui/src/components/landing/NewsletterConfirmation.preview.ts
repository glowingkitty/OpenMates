/** Local-only confirmation fixture; component proof intercepts relative /v1 requests. */
const defaultProps = {
  apiBaseUrl: '',
  signalUrl: 'https://signal.group/#preview',
  token: 'preview-token',
  language: 'en' as const,
};

export default defaultProps;

export const variants = {
  German: { ...defaultProps, language: 'de' as const },
};
