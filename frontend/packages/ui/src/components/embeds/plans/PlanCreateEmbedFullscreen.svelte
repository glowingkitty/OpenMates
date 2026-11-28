<!--
  Fullscreen for the plans.create skill result, with the saved Plan's
  assumptions, Checks and linked Tasks in the standard embed shell.
-->
<script lang="ts">
  import { getContext } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedFullscreenCommonProps, type EmbedFullscreenRawData, type EmbedSourceChatContext } from '../../../types/embedFullscreen';
  import PlanEmbedFullscreen from './PlanEmbedFullscreen.svelte';
  import { planDataFromCreate, watchCreatedPlan } from './planCreateData';
  import { openChatById, type PlanEmbedData } from './planEmbedModel';

  interface Props extends EmbedFullscreenCommonProps { data: EmbedFullscreenRawData; }
  let { data, onClose, embedId, hasPreviousEmbed = false, hasNextEmbed = false,
    onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat }: Props = $props();
  const source = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);
  let saved = $state<PlanEmbedData | null>(null);
  const content = $derived(data.decodedContent ?? {});
  const planData = $derived(saved ?? planDataFromCreate(content, embedId ?? 'draft-plan'));
  $effect(() => {
    saved = null;
    return watchCreatedPlan(content, source, (plan) => { saved = plan; });
  });
</script>

<UnifiedEmbedFullscreen appId="plans" skillId="create" skillIconName="planning" showShare={false}
  testId="plan-create-fullscreen" {onClose} embedHeaderTitle={planData.plan.title}
  currentEmbedId={embedId} {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}
  navigateDirection={navigateDirection ?? undefined} {showChatButton} {onShowChat}>
  {#snippet content()}
    <PlanEmbedFullscreen data={planData}
      onOpenChat={(chatId) => { onClose(); openChatById(chatId); }}
      onOpenTask={(taskId) => { onClose(); window.location.hash = `task-id=${encodeURIComponent(taskId)}`; }} />
  {/snippet}
</UnifiedEmbedFullscreen>
