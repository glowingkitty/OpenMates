<!--
  Chat preview for the plans.create skill result: a draft Plan card with the
  proposed title and goal. Wraps the shared Plan card.
-->
<script lang="ts">
  import PlanEmbedPreview from './PlanEmbedPreview.svelte';
  import { planDataFromCreate } from './planCreateData';

  interface Props {
    id: string;
    data: Record<string, unknown>;
    onFullscreen: () => void;
  }
  let { id, data, onFullscreen }: Props = $props();
  const planData = $derived(planDataFromCreate(data, id));
</script>

<PlanEmbedPreview data={planData} onOpen={() => onFullscreen()} />
