<!-- Account-free stored-content fixture. Real carrier, registry, store resolution,
     fullscreen controller and leaf components run unchanged; no backend proof. -->
<script lang="ts">
  import { onMount, type Component } from 'svelte';
  import AuthoredResultsEmbedPreview from './AuthoredResultsEmbedPreview.svelte';
  import { embedStore } from '../../services/embedStore';
  import { chatSyncService } from '../../services/chatSyncService';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import { dispatchEmbedFullscreen, resolveEmbedFullscreenTarget,
    type EmbedFullscreenDispatchDetail } from '../../services/embedFullscreenController';
  import { loadFullscreenComponent, resolveRegistryKey } from '../../services/embedFullscreenResolver';
  import type { AuthoredResultsContent } from '../../types/authoredResult';
  import type { EmbedFullscreenRawData } from '../../types/embedFullscreen';

  interface Child { embed_id: string; content: Record<string, unknown>; }
  let { id, content, children, isMobile = false, initialFullscreen = false,
    navigation = false, hydrateContent, renderViaGroup = false, sourceChatId }: {
    id: string; content: AuthoredResultsContent; children: Child[]; isMobile?: boolean;
    initialFullscreen?: boolean; navigation?: boolean; hydrateContent?: AuthoredResultsContent;
    renderViaGroup?: boolean; sourceChatId?: string;
  } = $props();
  let ready = $state(false);
  let groupHost = $state<HTMLDivElement>();
  let fullscreen = $state<{ id: string; component: Component<Record<string, unknown>>;
    data: EmbedFullscreenRawData; sourceChatId?: string | null }>();
  const fullscreenIndex = $derived(children.findIndex(child => child.embed_id === fullscreen?.id));
  let failure = $state('');
  let storedImageEvidence = $state('');
  async function closeFullscreen() {
    fullscreen = undefined;
    // Observe the actual store after the mounted view has projected its media.
    // Only public input URLs are reported; this fixture has no encrypted media.
    const observed = await Promise.all(children.map(async child => {
      const stored = await resolveEmbed(child.embed_id);
      const decoded = stored && await decodeToonContent(stored.content);
      return { embed_id: child.embed_id, image_url: decoded?.image_url ?? null,
        poster_url: decoded?.poster_url ?? null, image_urls: decoded?.image_urls ?? null };
    }));
    storedImageEvidence = JSON.stringify(observed);
  }
  const open = (embedId: string) => dispatchEmbedFullscreen({ embedId, sourceChatId });
  onMount(() => {
    let active = true;
    let disposeGroup: (() => void) | undefined;
    for (const child of children) {
      embedStore.registerStaticEmbed({ embedId: child.embed_id, type: String(child.content.type),
        appId: String(child.content.app_id), skillId: String(child.content.skill_id),
        parentEmbedId: id, content: JSON.stringify(child.content) });
      embedStore.registerEmbedRef(String(child.content.embed_ref), child.embed_id, String(child.content.app_id));
    }
    const seedCarrier = (next: AuthoredResultsContent) => embedStore.setInMemoryOnly(`embed:${id}`, {
      embed_id: id, type: 'authored_results', status: next.status, app_id: 'ai', skill_id: 'authored_results',
      embed_ids: next.embed_ids, content: JSON.stringify(next),
    });
    seedCarrier(content);
    const expanded = async (event: Event) => {
      const detail = (event as CustomEvent<EmbedFullscreenDispatchDetail>).detail;
      if (!detail.embedId) return;
      try {
        const original = await resolveEmbed(detail.embedId);
        if (!original) throw new Error('Fixture stored target is missing');
        const decoded = await decodeToonContent(original.content);
        if (!decoded) throw new Error('Fixture stored target cannot be decoded');
        const target = await resolveEmbedFullscreenTarget(original.embed_id, {
          embedType: original.type, decodedContent: decoded,
        });
        const stored = target.targetEmbedId === original.embed_id ? original : await resolveEmbed(target.targetEmbedId);
        if (!stored) throw new Error('Fixture resolved target is missing');
        const resolved = await decodeToonContent(stored.content);
        if (!resolved) throw new Error('Fixture resolved target cannot be decoded');
        const key = resolveRegistryKey(stored.type, resolved);
        const component = key ? await loadFullscreenComponent(key) : null;
        if (!component) throw new Error('Fixture fullscreen is unregistered');
        if (active) fullscreen = { id: stored.embed_id, sourceChatId: detail.sourceChatId,
          component: component as Component<Record<string, unknown>>,
          data: { decodedContent: resolved, embedData: { ...stored },
            chatEmbedIds: content.embed_ids, focusChildEmbedId: target.focusChildEmbedId } };
      } catch (error) {
        if (active) failure = error instanceof Error ? error.message : 'Fixture fullscreen failed';
      }
    };
    // Fixture-only trigger uses the same store/update event path as streamed
    // embeds. It does not replace props or directly invoke component callbacks.
    const finish = () => {
      if (!hydrateContent) return;
      seedCarrier(hydrateContent);
      chatSyncService.dispatchEvent(new CustomEvent('embedUpdated', {
        detail: { embed_id: id, status: hydrateContent.status },
      }));
    };
    document.addEventListener('embedfullscreen', expanded);
    document.addEventListener('preview:finish-authored-results', finish);
    ready = true;
    const groupTarget = groupHost;
    if (renderViaGroup && groupTarget) {
      void (async () => {
        const [{ GroupRenderer }, { disposeEmbedTree }] = await Promise.all([
          import('../enter_message/extensions/embed_renderers/GroupRenderer'),
          import('../enter_message/extensions/embed_renderers/mountedEmbedLifecycle'),
        ]);
        if (!active) return;
        disposeGroup = () => disposeEmbedTree(groupTarget, false);
        // Deliberately no data-embed-chat-id ancestor or ambient source context:
        // the actual renderer must provide attrs.sourceChatId to its Svelte root.
        await new GroupRenderer().render({ attrs: { id, type: 'authored-results',
          status: content.status, contentRef: `embed:${id}`, sourceChatId },
          container: groupTarget, content: groupTarget });
      })().catch(error => { if (active) failure = error instanceof Error ? error.message : 'Fixture group mount failed'; });
    }
    if (initialFullscreen) open(id);
    return () => {
      active = false;
      document.removeEventListener('embedfullscreen', expanded);
      document.removeEventListener('preview:finish-authored-results', finish);
      disposeGroup?.();
    };
  });
</script>

<div class="authored-fixture" data-testid="authored-results-fixture" data-ready={ready} data-stored-images={storedImageEvidence}>
  <div class="read-only-message">
    {#if renderViaGroup}<div bind:this={groupHost} data-testid="authored-group-renderer-host"></div>
    {:else if ready}
      <AuthoredResultsEmbedPreview {id} {content} {isMobile} status={content.status}
        onFullscreen={() => open(id)} />
    {/if}
    {#if failure}<p role="alert" data-testid="authored-fixture-error">{failure}</p>{/if}
  </div>
  <!-- Match ActiveChat: fullscreen is outside the message markdown styles. -->
  {#if fullscreen}
    {@const Fullscreen = fullscreen.component}
    <div class="fullscreen-host" data-testid="authored-fixture-fullscreen" data-embed-id={fullscreen.id}
      data-source-chat-id={fullscreen.sourceChatId ?? ''}>
      <Fullscreen data={fullscreen.data} embedId={fullscreen.id} onClose={closeFullscreen}
        hasNextEmbed={navigation && fullscreenIndex >= 0 && fullscreenIndex < children.length - 1}
        hasPreviousEmbed={navigation && fullscreenIndex > 0}
        onNavigateNext={() => { const next = children[fullscreenIndex + 1]; if (next) open(next.embed_id); }}
        onNavigatePrevious={() => { const previous = children[fullscreenIndex - 1]; if (previous) open(previous.embed_id); }} />
    </div>
  {/if}
</div>

<style>
  .authored-fixture { width: 100%; min-width: 0; }
  .fullscreen-host { position: fixed; inset: 0; z-index: 10000; background: var(--color-grey-0); }
</style>
