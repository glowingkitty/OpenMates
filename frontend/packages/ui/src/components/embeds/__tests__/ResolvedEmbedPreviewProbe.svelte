<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import { EMBED_PREVIEW_PRESENTATION_CONTEXT, type EmbedPreviewPresentationContext } from '../../../types/embedPreviewPresentation';
  let { title, payload, onSelect, onPreviewMount, marker, __previewComponent, __previewPresentation }: {
    title: string; payload: { id: string }; onSelect: (payload: { id: string }) => void;
    onPreviewMount: () => void; [key: string]: unknown;
  } = $props();
  const context = getContext<EmbedPreviewPresentationContext>(EMBED_PREVIEW_PRESENTATION_CONTEXT);
  const presentation = $derived(typeof context === 'string' ? context : context.presentation);
  onMount(() => onPreviewMount());
</script>

<button type="button" data-testid="resolved-preview-probe" data-presentation={presentation}
  data-payload-id={payload.id} data-marker={marker}
  data-control-props={[__previewComponent !== undefined ? '__previewComponent' : '', __previewPresentation !== undefined ? '__previewPresentation' : ''].filter(Boolean).join(',')}
  onclick={() => onSelect(payload)}>{title}</button>
