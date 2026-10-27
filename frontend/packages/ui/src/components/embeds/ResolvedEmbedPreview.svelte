<!-- Registry-level presentation context without changing individual preview contracts. -->
<script lang="ts">
  import { setContext, type Component } from 'svelte';
  import { EMBED_PREVIEW_PRESENTATION_CONTEXT, type EmbedPreviewPresentation } from '../../types/embedPreviewPresentation';

  // This internal adapter forwards each registered component's own prop contract.
  // svelte-ignore custom_element_props_identifier
  let { __previewComponent: Preview, __previewPresentation, ...previewProps }: {
    __previewComponent: Component<Record<string, unknown>>;
    __previewPresentation: EmbedPreviewPresentation;
    [key: string]: unknown;
  } = $props();

  // Registry consumers can replace content without remounting this provider.
  setContext(EMBED_PREVIEW_PRESENTATION_CONTEXT, {
    get presentation() { return __previewPresentation; },
  });
</script>

<Preview {...previewProps} />
