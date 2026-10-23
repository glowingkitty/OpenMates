<!-- Exercises the production group renderer and highlighted-embed carousel. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { encode } from '@toon-format/toon';
  import { GroupRenderer } from '../enter_message/extensions/embed_renderers/GroupRenderer';
  import { disposeEmbedTree } from '../enter_message/extensions/embed_renderers/mountedEmbedLifecycle';
  import { embedStore } from '../../services/embedStore';
  import EmbedPreviewLarge from './EmbedPreviewLarge.svelte';
  import EmbedReferencePreview from './EmbedReferencePreview.svelte';
  import type { EmbedNodeAttributes } from '../../message_parsing/types';

  let { app = 'home', skillCalls = false, skillStatus = 'processing' }: {
    app?: 'home' | 'events';
    skillCalls?: boolean;
    skillStatus?: 'processing' | 'finished';
  } = $props();
  let compact: HTMLDivElement;
  let ready = $state(false);
  const ids = [1, 2, 3].map(index => `e4336790-2200-4000-8000-00000000000${index}`);
  const titles = [
    'First apartment with a deliberately long title beside the canal and sunny balcony in Kreuzberg',
    'Second apartment with a deliberately long title near the park and excellent transit connections',
    'Third apartment with a deliberately long title and generous living room overlooking the courtyard',
  ];
  const rows = ids.map((embed_id, index) => ({ embed_id, title: titles[index],
    price_label: `${1250 + index * 100} EUR warm / month`, size_sqm: 65 + index,
    provider: 'WG-Gesucht', address: 'Kreuzberg, Berlin',
    image_url: `/store-examples/home-${index + 1}.webp`,
    url: `https://www.wg-gesucht.de/wohnungen-in-Berlin.${index + 1}.html`,
    date_start: '2026-12-15T18:00:00Z', event_type: 'PHYSICAL',
    ...(app === 'events' ? {
      provider: 'meetup', timezone: 'Europe/Berlin',
      organizer_name: `Berlin Event Community ${index + 1}`, organizer_id: `organizer-${index + 1}`,
      venue_name: 'Berlin community space', venue_city: 'Berlin', venue_address: 'Example Street 1',
      venue_lat: 52.52, venue_lon: 13.405, fee_amount: 0, fee_currency: 'EUR', is_paid: false, rsvp_count: 80 + index,
    } : { venue: { name: 'Berlin community space', city: 'Berlin' } }),
  }));

  onMount(() => {
    let disposed = false;
    const renderer = new GroupRenderer();
    const type = skillCalls ? 'app-skill-use' : app === 'home' ? 'home-listing' : 'events-event';
    const status = skillCalls ? skillStatus : 'finished';
    const queries = ['artificial intelligence latest developments', 'Anthropic news Claude', 'OpenAI latest news'];
    const records = skillCalls ? ids.map((embed_id, index) => ({
      embed_id, app_id: 'news', skill_id: 'search', query: queries[index],
      provider: 'Brave Search', status, embed_ids: [], result_count: 0,
    })) : rows;
    for (const row of records) {
      embedStore.setInMemoryOnly(`embed:${row.embed_id}`, {
        embed_id: row.embed_id, type, app_id: skillCalls ? 'news' : app,
        skill_id: skillCalls ? 'search' : app === 'home' ? 'listing' : 'event',
        status, content: encode(row),
      });
    }
    const groupedItems = [...records].reverse().map(row => ({
      id: row.embed_id, type, status,
      contentRef: `embed:${row.embed_id}`, ...row,
    } as EmbedNodeAttributes));
    void renderer.render({ attrs: { id: 'preview-real-result-group', type: `${type}-group`,
      status, groupedItems, groupCount: records.length } as EmbedNodeAttributes,
      content: compact, container: compact,
    }).then(() => { if (!disposed) ready = true; });
    return () => {
      disposed = true;
      disposeEmbedTree(compact);
      for (const id of ids) embedStore.removeFromMemoryCache(`embed:${id}`);
    };
  });
</script>

<div class="fixture read-only-message ProseMirror" data-testid="grouped-result-fixture" data-ready={ready} data-context="chat">
  <section data-testid="compact-group"><div bind:this={compact} class="embed-group-container"></div></section>
  {#if ready && !skillCalls}
    <section data-testid="large-group">
      {#each ids as id, index}<EmbedPreviewLarge embedRef={id} embedId={id} carouselIndex={index} carouselTotal={ids.length} runRef="grouped-result-fixture" />{/each}
    </section>
    <section data-testid="ungrouped-result"><EmbedReferencePreview embedRef={ids[0]} embedId={ids[0]} variant="small" /></section>
  {/if}
</div>

<style>
  @import '../enter_message/EmbeddPreview.styles.css';
  .fixture { width:100%; max-width:900px; min-width:0; box-sizing:border-box; padding:12px; display:grid; gap:40px; }
  section { min-width:0; }
</style>
