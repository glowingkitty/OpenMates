<!--
  Chat preview for the plans.specification skill result: an unsaved draft
  Specification. Wraps the shared Specification card; no layout of its own.
  Contract: specifications/features/specifications/specification.yml.
-->
<script lang="ts">
  import SpecificationEmbedPreview from './SpecificationEmbedPreview.svelte';
  import { specificationListItemFromSkill } from './specificationSkillDocument';

  interface Props {
    id: string;
    data: Record<string, unknown>;
    isMobile?: boolean;
    onFullscreen: () => void;
  }
  let { id, data, isMobile = false, onFullscreen }: Props = $props();
  const item = $derived(specificationListItemFromSkill(data, id));
</script>

<SpecificationEmbedPreview {id} {item} {isMobile} {onFullscreen} />
