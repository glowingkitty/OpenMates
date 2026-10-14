import type { NewsroomView } from '@repo/public-site/components/newsroom/types';

const props = (view: NewsroomView, locale: 'en' | 'de' = 'en') => ({
  view,
  locale,
  appBaseUrl: 'https://app.dev.openmates.org',
  websiteBaseUrl: 'https://landing.dev.openmates.org',
});

export default props('news');
export const layout = 'fill';

export const variants = {
  'Social post': props('social-post'),
  Blog: props('blog'),
  Release: props('release'),
  'Blog post': props('blog-post'),
  'News German': props('news', 'de'),
  'Blog German': props('blog', 'de'),
  'Release German': props('release', 'de'),
};
