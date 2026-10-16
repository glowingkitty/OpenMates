<script lang="ts">
  import { locale } from 'svelte-i18n';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '../../../i18n/translations';

  let { runId, title, description, startedAt, onFullscreen }: {
    runId: string;
    title?: string;
    description?: string;
    startedAt?: number;
    onFullscreen: () => void;
  } = $props();

  let startedLabel = $derived.by(() => {
    if (!startedAt || !Number.isFinite(startedAt)) return '';
    const date = new Date(startedAt * 1000);
    return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat($locale || 'en', {
      dateStyle: 'medium', timeStyle: 'short',
    }).format(date);
  });
</script>

<UnifiedEmbedPreview
  id={runId}
  presentationOnly
  appId="workflows"
  appIconName="workflow"
  skillId="run"
  skillIconName="workflow"
  status="finished"
  skillName={$text('workflows.run_embed.title')}
  showSkillIcon
  {onFullscreen}
>
  {#snippet details()}
    <div class="run-preview" data-testid="workflow-run-embed-preview">
      <strong>{title || $text('workflows.run_embed.title')}</strong>
      {#if description}<span class="description">{description}</span>{/if}
      {#if startedLabel}<span>{$text('workflows.run_embed.started_at')}: {startedLabel}</span>{/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .run-preview { display:flex; height:100%; flex-direction:column; justify-content:center; gap:var(--spacing-3); padding:var(--spacing-4); box-sizing:border-box; }
  strong { color:var(--color-font-primary); font-size:var(--font-size-sm); display:-webkit-box; overflow:hidden; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
  span { color:var(--color-font-secondary); font-size:var(--font-size-xs); }
  .description { display:-webkit-box; overflow:hidden; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
</style>
