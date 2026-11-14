<!--
  Fullscreen for the plans.create skill result: the draft Plan in the shared
  Plan view inside the standard embed fullscreen shell.
-->
<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import type { EmbedFullscreenCommonProps, EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import PlanEmbedFullscreen from './PlanEmbedFullscreen.svelte';
  import { planDataFromCreate } from './planCreateData';

  interface Props extends EmbedFullscreenCommonProps { data: EmbedFullscreenRawData; }
  let { data, onClose, embedId, hasPreviousEmbed = false, hasNextEmbed = false,
    onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat }: Props = $props();
  const planData = $derived(planDataFromCreate(data.decodedContent ?? {}, embedId ?? 'draft-plan'));
</script>

<UnifiedEmbedFullscreen appId="plans" skillId="create" skillIconName="planning" showShare={false}
  testId="plan-create-fullscreen" {onClose} embedHeaderTitle={planData.plan.title}
  currentEmbedId={embedId} {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}
  navigateDirection={navigateDirection ?? undefined} {showChatButton} {onShowChat}>
  {#snippet content()}
    <PlanEmbedFullscreen data={planData} />
  {/snippet}
</UnifiedEmbedFullscreen>
