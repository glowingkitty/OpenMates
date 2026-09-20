import { newsroomFixtures } from './fixtures';
import type { NewsroomAction, NewsroomView } from './types';

const logAction = (action: NewsroomAction) => console.info('[newsroom preview]', action);

function props(view: NewsroomView, locale: 'en' | 'de' = 'en') {
  return {
    view,
    locale,
    data: newsroomFixtures[locale],
    onAction: logAction,
  };
}

export default props('news');

export const variants = {
  Blog: props('blog'),
  Release: props('release'),
  'Blog post': props('blog-post'),
  'Social post': props('social-post'),
  'News German': props('news', 'de'),
  'Blog German': props('blog', 'de'),
};
