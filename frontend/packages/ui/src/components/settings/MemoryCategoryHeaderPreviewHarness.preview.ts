/** Public metadata only; production category owns previous/next registration. */
const defaults = { appId: 'books', categoryId: 'favorite_books', scrollTop: 0 };
export default defaults;
export const variants = {
  middle: { ...defaults, categoryId: 'currently_reading' },
  collapsed: { ...defaults, categoryId: 'currently_reading', scrollTop: 120 },
};
