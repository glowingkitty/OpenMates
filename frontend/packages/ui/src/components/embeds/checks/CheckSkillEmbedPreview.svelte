<!--
  Chat preview for the plans.check skill result: an unsaved draft Check that
  has never run. Wraps the shared Check card; running is not offered yet.
  Spec: checks.gui.preview.
-->
<script lang="ts">
  import CheckEmbedPreview from './CheckEmbedPreview.svelte';
  import { checkViewFromSkill } from './checkSkillView';

  interface Props {
    id: string;
    data: Record<string, unknown>;
    isMobile?: boolean;
    onFullscreen: () => void;
  }
  let { id, data, isMobile = false, onFullscreen }: Props = $props();
  const check = $derived(checkViewFromSkill(data, id));
</script>

<CheckEmbedPreview {id} {check} {isMobile} status="finished" {onFullscreen} />
