<!--
  frontend/packages/ui/src/components/interactive_questions/InteractiveQuestionEmbeds.svelte

  Renders OpenMates embed references that are attached to choice options or swipe cards.
  Uses the same large embed preview pipeline as chat messages, while preventing preview
  clicks from toggling the surrounding question control.

  Architecture: Svelte 5 / InteractiveQuestions + Unified embed previews
-->

<script lang="ts">
  import { getContext } from 'svelte';
  import EmbedPreviewLarge from '../embeds/EmbedPreviewLarge.svelte';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../types/embedFullscreen';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import { embedStore } from '../../services/embedStore';
  import { resolveExampleChatEmbedRef } from '../../demo_chats/exampleChatStore';
  import { isEmbedUuid, resolveReferenceableEmbedIds } from './utils/referenceableEmbeds';

  let { embedIds = [] }: { embedIds?: string[] } = $props();
  const chatId = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT)?.chatId ?? null;
  let requestedEmbedIds = $derived(embedIds.filter((embedId) => embedId.trim().length > 0));
  // Only result embeds may be referenced: app-skill embeds resolve to their
  // result children (or nothing). Nothing renders until resolved, so a
  // forbidden app-skill card never flashes.
  let resolvedEmbedIds = $state<string[]>([]);
  let normalizedEmbedIds = $derived(resolvedEmbedIds);

  $effect(() => {
    const requested = requestedEmbedIds;
    let cancelled = false;
    resolvedEmbedIds = [];
    void resolveReferenceableEmbedIds(requested, async (embedId) => {
      try {
        const embed = await resolveEmbed(embedId, { chatId });
        if (!embed) return null;
        let childEmbedIds = embed.embed_ids ?? [];
        if (childEmbedIds.length === 0 && embed.content) {
          const decoded = await decodeToonContent(embed.content);
          const ids = decoded?.embed_ids;
          if (Array.isArray(ids)) childEmbedIds = ids.filter((id): id is string => typeof id === 'string');
        }
        return { type: embed.type, childEmbedIds };
      } catch (error) {
        console.debug('[InteractiveQuestionEmbeds] Referenced embed not resolvable yet:', embedId, error);
        return null;
      }
    }, async (embedRef) => {
      // Public example chats keep their own ref namespace; private chats use the embed ref index.
      const exampleEmbedId = resolveExampleChatEmbedRef(embedRef, chatId)?.embedId;
      if (exampleEmbedId) return exampleEmbedId;
      try {
        return await embedStore.resolveByRefDeep(embedRef, chatId ?? undefined);
      } catch (error) {
        console.debug('[InteractiveQuestionEmbeds] Embed ref not resolvable yet:', embedRef, error);
        return null;
      }
    }).then((ids) => { if (!cancelled) resolvedEmbedIds = ids; });
    return () => { cancelled = true; };
  });
</script>

{#if normalizedEmbedIds.length > 0}
  <div
    class="interactive-question-embeds"
    data-testid="interactive-question-embeds"
  >
    {#each normalizedEmbedIds as embedId (embedId)}
      <div class="interactive-question-embed" data-testid="interactive-question-embed">
        <EmbedPreviewLarge
          embedRef={embedId}
          embedId={isEmbedUuid(embedId) ? embedId : null}
          carouselIndex={0}
          carouselTotal={1}
          runRef={`interactive-question-${embedId}`}
        />
      </div>
    {/each}
  </div>
{/if}

<style>
  .interactive-question-embeds {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-8, 8px);
    width: 100%;
    margin-top: var(--spacing-8, 8px);
  }

  .interactive-question-embed {
    width: 100%;
    min-width: 0;
  }

  :global(.interactive-question-embed .embed-preview-large-wrapper) {
    max-width: 100%;
  }
</style>
