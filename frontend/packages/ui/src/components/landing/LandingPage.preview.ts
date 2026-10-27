/** The page also renders its empty publication state when no feed is available. */
const defaultProps = {
  appBaseUrl: 'https://app.dev.openmates.org',
  websiteBaseUrl: 'https://app.dev.openmates.org',
  apiBaseUrl: 'https://api.dev.openmates.org',
  initialLanguage: 'en',
  initialLanguageMode: 'auto',
  events: [],
  news: [],
  posts: [],
};

export default defaultProps;

export const layout = 'fill';
