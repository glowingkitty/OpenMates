<!-- Registry-level presentation context without changing individual preview contracts. -->
<script lang="ts">
  import { setContext, type Component } from 'svelte';
  import { EMBED_PREVIEW_PRESENTATION_CONTEXT, type EmbedPreviewPresentation } from '../../types/embedPreviewPresentation';
  import { AUTHORED_RESULT_PRESENTATION_CONTEXT, type AuthoredResultMedia } from '../../types/authoredResult';
  import { createAuthoredResultMediaOwner } from '../../services/authoredResultMedia';
  import { authoredResultMetadata, authoredResultMediaPresentation } from '../../utils/authoredResultPresentation';

  // This internal adapter forwards each registered component's own prop contract.
  // svelte-ignore custom_element_props_identifier
  let { __previewComponent: Preview, __previewPresentation, __authoredContent = {}, __authoredProps, ...previewProps }: {
    __previewComponent: Component<Record<string, unknown>>;
    __previewPresentation: EmbedPreviewPresentation;
    __authoredContent?: Record<string, unknown>;
    __authoredProps?: (content: Record<string, unknown>) => Promise<Record<string, unknown>>;
    [key: string]: unknown;
  } = $props();
  const authoring = $derived(authoredResultMetadata(__authoredContent));
  let mediaProps = $state<Record<string, unknown>>();
  let mediaUrls = $state<string[]>([]);
  const presentationContent = $derived(authoredResultMediaPresentation(__authoredContent, mediaUrls));
  $effect(() => {
    const content = __authoredContent;
    const selected = authoring ? content.authored_media as AuthoredResultMedia[] | undefined : undefined;
    const resolveProps = __authoredProps;
    mediaProps = undefined;
    mediaUrls = [];
    if (!selected?.length || !resolveProps) return;
    const owner = createAuthoredResultMediaOwner();
    let current = true;
    void owner.resolve(selected).then(async media => {
      if (!current || !media.length) return;
      const urls = media.map(item => item.url);
      mediaUrls = urls;
      const props = await resolveProps(authoredResultMediaPresentation(content, urls));
      if (current) mediaProps = props;
    }).catch(() => { if (current) mediaProps = undefined; });
    return () => { current = false; owner.dispose(); };
  });
  setContext(AUTHORED_RESULT_PRESENTATION_CONTEXT, {
    get authoring() { return authoring; },
    get content() { return __authoredContent; },
    get presentationContent() { return presentationContent; },
  });

  // Registry consumers can replace content without remounting this provider.
  setContext(EMBED_PREVIEW_PRESENTATION_CONTEXT, {
    get presentation() { return __previewPresentation; },
  });
</script>

<Preview {...(mediaProps ?? previewProps)} />
