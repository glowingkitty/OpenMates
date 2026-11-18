<!-- frontend/packages/ui/src/components/RecommendationEmbedPreview.svelte
     One chat recommendation rendered as an embed preview card (UnifiedEmbedPreview,
     presentation only: no embed record, sync or context menu). Memory items use the
     insight icon of saved memories; workflow items use the Workflows app identity; Project focus items the Projects app identity.
     Clicking the card opens the same draft as the Create/Update button below it.
     Spec: app-memories.suggestions.post-processor
-->
<script lang="ts">
  import UnifiedEmbedPreview from './embeds/UnifiedEmbedPreview.svelte';
  import { text } from '../i18n/translations';
  import type { RecommendationCardItem } from '../types/recommendations';

  interface Props {
    item: RecommendationCardItem;
    onOpen: () => void;
  }
  let { item, onOpen }: Props = $props();

  const IDENTITY = {
    memory: { appId: 'openmates', icon: 'insight', label: 'recommendations.type_memory' },
    workflow: { appId: 'workflows', icon: 'workflow', label: 'recommendations.type_workflow' },
    focus: { appId: 'projects', icon: 'project', label: 'recommendations.type_focus' },
  } as const;
  let identity = $derived(IDENTITY[item.kind]);
  let typeLabel = $derived($text(identity.label));
</script>

<UnifiedEmbedPreview
  id={`recommendation-${item.id}`}
  presentationOnly
  appId={identity.appId}
  appIconName={identity.icon}
  skillId={item.kind}
  skillIconName={identity.icon}
  status="finished"
  skillName={typeLabel}
  showStatus={false}
  showSkillIcon={false}
  onFullscreen={onOpen}
>
  {#snippet details()}
    <!-- The embed header already names the type (skillName), so the body shows only title and summary. -->
    <div class="recommendation-preview" data-testid="recommendation-embed" data-kind={item.kind}>
      <strong data-testid="recommendation-title">{item.title}</strong>
      <span class="summary" data-testid="recommendation-summary">{item.summary}</span>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .recommendation-preview {
    display: flex;
    height: 100%;
    flex-direction: column;
    justify-content: center;
    gap: var(--spacing-2);
    /* docs/design-guide/result-embeds.md: 48px left/right text safety gap on compact cards. */
    padding: var(--spacing-4) 48px;
    box-sizing: border-box;
    text-align: start;
  }
  strong {
    display: -webkit-box;
    overflow: hidden;
    color: var(--color-font-primary);
    font-size: var(--font-size-sm);
    line-height: 1.25;
    overflow-wrap: anywhere;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }
  .summary {
    display: -webkit-box;
    overflow: hidden;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    line-height: 1.35;
    overflow-wrap: anywhere;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
  }
</style>
