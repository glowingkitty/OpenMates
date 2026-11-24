import type { ComponentProps } from 'svelte';
import type MailSearchEmbedFullscreen from './MailSearchEmbedFullscreen.svelte';
import { embedStore } from '../../../services/embedStore';

const results = [
  { subject: 'Garden volunteers', from: 'garden@example.org', body_text: 'Meet by the south gate at ten.' },
  {
    subject: 'Seed swap',
    from: 'seeds@example.org',
    body_html: '<p>Bring <strong>labelled seeds</strong>.</p><form><input name="email"></form>',
  },
];
const embedIds = results.map((content, index) => {
  const embedId = `preview-mail-search-result-${index}`;
  embedStore.registerStaticEmbed({
    embedId, type: 'email', appId: 'mail', skillId: 'email', content: JSON.stringify(content),
  });
  return embedId;
});
const search = { query: 'Community garden', result_count: results.length };
const props = {
  embedId: 'preview-mail-search',
  data: { decodedContent: { ...search, embed_ids: embedIds } },
  onClose: () => {},
} satisfies ComponentProps<typeof MailSearchEmbedFullscreen>;

export default props;
export const variants = {
  focusedChild: { ...props, data: { ...props.data, focusChildEmbedId: embedIds[1] } },
  inlineResults: { ...props, data: { decodedContent: { ...search, results } } },
} satisfies Record<string, ComponentProps<typeof MailSearchEmbedFullscreen>>;
