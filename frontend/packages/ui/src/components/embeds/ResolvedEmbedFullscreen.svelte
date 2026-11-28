<!-- A registry adapter owns authored presentation; stored content stays unchanged. -->
<script lang="ts">
  import { setContext, type Component } from 'svelte';
  import { EMBED_PREVIEW_PRESENTATION_CONTEXT, getEmbedPreviewPresentation } from '../../types/embedPreviewPresentation';
  import { AUTHORED_RESULT_PRESENTATION_CONTEXT } from '../../types/authoredResult';
  import type { AuthoredResultMedia } from '../../types/authoredResult';
  import type { EmbedFullscreenRawData } from '../../types/embedFullscreen';
  import { createAuthoredResultMediaOwner } from '../../services/authoredResultMedia';
  import { authoredResultMetadata, authoredResultMediaPresentation } from '../../utils/authoredResultPresentation';

  // This adapter forwards each fullscreen's existing props, not a custom element.
  // svelte-ignore custom_element_props_identifier
  let { __fullscreenComponent: Fullscreen, __registryKey: registryKey, data, ...rest }: {
    __fullscreenComponent: Component<Record<string, unknown>>;
    __registryKey?: string;
    data?: EmbedFullscreenRawData;
    [key: string]: unknown;
  } = $props();
  setContext(EMBED_PREVIEW_PRESENTATION_CONTEXT, {
    get presentation() {
      const actual = data?.embedType ?? data?.embedData?.type ?? data?.attrs?.type;
      return getEmbedPreviewPresentation(typeof actual === 'string' ? actual : undefined, registryKey);
    }
  });
  const content = $derived(data?.decodedContent ?? {});
  const authoring = $derived(authoredResultMetadata(content));
  let mediaUrls = $state<string[]>([]);
  $effect(() => {
    const selected = authoring ? content.authored_media as AuthoredResultMedia[] | undefined : undefined;
    mediaUrls = [];
    if (!selected?.length) return;
    const owner = createAuthoredResultMediaOwner();
    let current = true;
    void owner.resolve(selected, 'fullscreen').then(media => { if (current) mediaUrls = media.map(item => item.url); });
    return () => { current = false; owner.dispose(); };
  });
  const presentationData = $derived(data && authoring
    ? { ...data, decodedContent: authoredResultMediaPresentation(content, mediaUrls) } : data);
  setContext(AUTHORED_RESULT_PRESENTATION_CONTEXT, {
    get authoring() { return authoring; },
    get content() { return content; },
    get presentationContent() { return presentationData?.decodedContent ?? content; },
  });
</script>

<Fullscreen {...rest} data={presentationData} />
