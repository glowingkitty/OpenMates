<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '../../../i18n/translations';

  let { runId, onFullscreen }: { runId: string; onFullscreen: () => void } = $props();
</script>

<UnifiedEmbedPreview
  id={runId}
  presentationOnly
  appId="workflows"
  skillId="run"
  skillIconName="workflow"
  status="finished"
  skillName={$text('workflows.run_embed.title')}
  showSkillIcon
  {onFullscreen}
>
  {#snippet details()}
    <div class="run-preview" data-testid="workflow-run-embed-preview">
      <strong>{$text('workflows.run_embed.title')}</strong>
      <span>{$text('workflows.run_embed.open_detail')}</span>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .run-preview { display:flex; height:100%; flex-direction:column; justify-content:center; gap:var(--spacing-3); padding:var(--spacing-6); box-sizing:border-box; }
  strong { color:var(--color-font-primary); font-size:var(--font-size-sm); }
  span { color:var(--color-font-secondary); font-size:var(--font-size-xs); }
</style>
