<script lang="ts">
  import type { Component } from 'svelte';
  import type { EmbedPreviewPresentation } from '../../../types/embedPreviewPresentation';
  import ResolvedEmbedPreview from '../ResolvedEmbedPreview.svelte';
  import Probe from './ResolvedEmbedPreviewProbe.svelte';
  let { onSelect, onPreviewMount, initialPayload }: {
    onSelect: (payload: { id: string }) => void; onPreviewMount: () => void;
    initialPayload: { id: string };
  } = $props();
  function initialRoute(): { presentation: EmbedPreviewPresentation; title: string; payload: { id: string } } {
    return { presentation: 'execution', title: 'Execution result', payload: initialPayload };
  }
  let route = $state.raw(initialRoute());
  export function navigate(next: typeof route) { route = next; }
  const component = Probe as unknown as Component<Record<string, unknown>>;
</script>

<ResolvedEmbedPreview __previewComponent={component} __previewPresentation={route.presentation}
  title={route.title} payload={route.payload} {onSelect} {onPreviewMount} marker="forwarded-flat-prop" />
