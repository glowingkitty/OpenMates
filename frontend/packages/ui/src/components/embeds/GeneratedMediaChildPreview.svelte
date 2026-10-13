<!-- Mount the registered generated-media leaf preview inside a parent grid. -->
<script lang="ts">
  import { mount, unmount } from 'svelte';
  import { embedPreviewRegistry } from '../../services/embedPreviewRegistry';

  interface Props {
    appId: string;
    result: Record<string, unknown> & { embed_id: string };
    onSelect: () => void;
  }

  let { appId, result, onSelect }: Props = $props();
  let host: HTMLDivElement;
  let renderError = $state(false);
  const childType = $derived({
    images: 'generated_image', audio: 'generated_audio', music: 'generated_music',
    videos: 'generated_video', models3d: 'generated_model',
  }[appId] || 'app_skill_use');

  $effect(() => {
    if (!host) return;
    let disposed = false;
    let instance: ReturnType<typeof mount> | undefined;
    renderError = false;
    void embedPreviewRegistry.resolve({
      embedId: result.embed_id,
      embedData: { type: childType, status: 'finished' },
      decodedContent: result,
      onFullscreen: onSelect,
    }).then((resolved) => {
      if (disposed) return;
      if (!resolved) { renderError = true; return; }
      instance = mount(resolved.component as Parameters<typeof mount>[0], {
        target: host, props: resolved.props,
      });
    }).catch(() => { if (!disposed) renderError = true; });
    return () => {
      disposed = true;
      if (instance) void unmount(instance);
      host.replaceChildren();
    };
  });
</script>

<div bind:this={host} data-testid="generated-media-child-card"></div>
{#if renderError}<button onclick={onSelect}>{String(result.prompt || result.embed_ref || result.embed_id)}</button>{/if}
