<!--
  Isolated result-preview layout fixture: renders two copies of a production
  result card (home, health, events or code) in chat or grid context.
  No account, memory data, save operation, reminder or backend is involved.
-->
<script lang="ts">
  import type { Component } from 'svelte';
  import HomePreview from './home/HomeListingEmbedPreview.svelte';
  import HealthPreview from './health/HealthAppointmentEmbedPreview.svelte';
  import EventPreview from './events/EventEmbedPreview.svelte';
  import CodePreview from './code/CodeEmbedPreview.svelte';

  let { family = 'home', mode = 'chat' }: {
    family?: 'home' | 'health' | 'events' | 'code'; mode?: 'chat' | 'grid';
  } = $props();
  const embedId = 'saved-preview-fixture-result';
  const title = 'Saved preview result';
  let expanded = $state(0);
  const onFullscreen = () => { expanded += 1; };
  const preview = $derived.by(() => {
    if (family === 'health') return { component: HealthPreview, props: { id: embedId, name: title, speciality: 'General medicine', onFullscreen } };
    if (family === 'events') return { component: EventPreview, props: { id: embedId, event: { embed_id: embedId, title, date_start: '2026-10-30T11:00:00Z' }, onFullscreen } };
    if (family === 'code') return { component: CodePreview, props: { id: embedId, filename: 'Saved preview result with a deliberately long filename to verify marker clearance.py', language: 'python', codeContent: 'print("preview")', status: 'finished', onFullscreen } };
    return { component: HomePreview, props: { embed_id: embedId, title, price_label: '850 EUR/month', onSelect: onFullscreen } };
  });
  const renderable = (component: unknown): Component<Record<string, unknown>> => component as Component<Record<string, unknown>>;
</script>

<div data-testid="saved-result-fixture" data-ready="true" data-expanded={expanded}>
  <div class:read-only-message={mode === 'chat'} class="cards" data-embed-result-context={mode === 'grid' ? 'results' : undefined}>
    {#each [0, 1] as index}
      {@const Preview = renderable(preview.component)}
      <div class="preview-host" data-testid={`saved-result-copy-${index}`}>
        <Preview {...preview.props} />
      </div>
    {/each}
  </div>
</div>

<style>
  .cards { display: flex; flex-wrap: wrap; gap: 20px; }
  .preview-host { width: 300px; container: embed-preview / inline-size; }
</style>
