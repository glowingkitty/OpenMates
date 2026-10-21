<script lang="ts">
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { searchResultImageUrl } from '../../../utils/searchPreviewImages';
  import NewsEmbedFullscreen from './NewsEmbedFullscreen.svelte';

  // The shared registry passes raw embed data; the article viewer is also used
  // directly by News search and keeps its existing metadata prop contract.
  let { data, embedId, onClose, showChatButton = false }: {
    data: EmbedFullscreenRawData; embedId?: string; onClose: () => void; showChatButton?: boolean;
  } = $props();
  const content = $derived(data.decodedContent);
  const text = (value: unknown): string | undefined => typeof value === 'string' ? value : undefined;
  const metaUrl = $derived(content.meta_url && typeof content.meta_url === 'object' ? content.meta_url as Record<string, unknown> : {});
</script>

<NewsEmbedFullscreen {embedId} {onClose} {showChatButton}
  url={text(content.url) ?? ''} title={text(content.title)}
  description={text(content.description) ?? text(content.snippet)}
  favicon={text(content.favicon) ?? text(content.favicon_url) ?? text(content.meta_url_favicon) ?? text(content['meta_url.favicon']) ?? text(metaUrl.favicon)}
  image={searchResultImageUrl(content)} extra_snippets={content.extra_snippets as string | string[] | undefined}
  dataDate={text(content.page_age) ?? text(content.age)} />
