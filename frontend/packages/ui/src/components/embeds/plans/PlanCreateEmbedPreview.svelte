<!--
  Chat preview for the plans.create skill result. Shows the saved Plan's
  progress once the browser can read it.
-->
<script lang="ts">
  import { getContext } from 'svelte';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../../types/embedFullscreen';
  import PlanEmbedPreview from './PlanEmbedPreview.svelte';
  import { planDataFromCreate, watchCreatedPlan } from './planCreateData';
  import type { PlanEmbedData } from './planEmbedModel';

  interface Props {
    id: string;
    data: Record<string, unknown>;
    onFullscreen: () => void;
  }
  let { id, data, onFullscreen }: Props = $props();
  const source = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);
  let saved = $state<PlanEmbedData | null>(null);
  const planData = $derived(saved ?? planDataFromCreate(data, id));
  $effect(() => {
    saved = null;
    return watchCreatedPlan(data, source, (plan) => { saved = plan; });
  });
</script>

<PlanEmbedPreview {id} data={planData} {onFullscreen} />
