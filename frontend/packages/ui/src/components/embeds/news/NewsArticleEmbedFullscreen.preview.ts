/** The registry adapter uses raw embed data; reuse the news viewer's fixtures. */
import newsDefaults, { variants as newsVariants } from './NewsEmbedFullscreen.preview';

function articlePreview(props: Record<string, unknown>) {
  const {
    onClose, hasPreviousEmbed, hasNextEmbed, onNavigatePrevious, onNavigateNext,
    dataDate = '2026-10-21', ...content
  } = props;
  return {
    data: {
      decodedContent: { ...content, page_age: dataDate },
      embedData: { status: 'finished' },
      attrs: { app_id: 'news', skill_id: 'article' },
    },
    onClose, hasPreviousEmbed, hasNextEmbed, onNavigatePrevious, onNavigateNext,
  };
}

export default articlePreview(newsDefaults);
export const variants = Object.fromEntries(
  Object.entries(newsVariants).map(([name, props]) => [name, articlePreview(props)])
);
