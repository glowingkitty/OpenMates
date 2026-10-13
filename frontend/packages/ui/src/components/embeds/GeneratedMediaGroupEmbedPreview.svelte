<!-- Skill-use parent card for one invocation with zero or more generated children. -->
<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from './UnifiedEmbedPreview.svelte';
  import { generatedMediaChildIds } from './generatedMediaGroup';

  interface Props {
    id: string;
    appId: string;
    skillId: string;
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    resultCount?: number;
    childEmbedIds?: string[];
    error?: string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id, appId, skillId, status, resultCount, childEmbedIds = [], error = '',
    taskId, isMobile = false, onFullscreen,
  }: Props = $props();
  let currentCount = $state<number | undefined>(undefined);
  let currentError = $state<string | undefined>(undefined);
  const skillName = $derived($text(`app_skills.${appId}.${skillId}`));
  const count = $derived(Math.max(currentCount ?? 0, resultCount ?? 0, childEmbedIds.length));

  function handleUpdated(data: { decodedContent: Record<string, unknown> | null }) {
    const content = data.decodedContent;
    if (!content) return;
    currentCount = Math.max(
      typeof content.result_count === 'number' ? content.result_count : 0,
      generatedMediaChildIds(content).length,
    );
    currentError = typeof content.error === 'string' ? content.error : undefined;
  }
</script>

<UnifiedEmbedPreview
  {id} {appId} {skillId} skillIconName={appId === 'models3d' ? '3dmodels' : appId}
  {status} {skillName} {taskId} {isMobile} {onFullscreen}
  onEmbedDataUpdated={handleUpdated}
  customStatusText={count > 0 ? `${count} · ${$text('apps_workspace.results')}` : undefined}
>
  {#snippet details()}
    <div class="generated-media-parent" data-testid="generated-media-parent-preview">
      <span class="skill-name">{skillName}</span>
      {#if count > 0}<span class="result-count">{count} {$text('apps_workspace.results')}</span>{/if}
      {#if currentError || error}<span class="partial-error">{currentError || error}</span>{/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .generated-media-parent { display: flex; height: 100%; flex-direction: column; justify-content: center; gap: var(--spacing-4); padding: var(--spacing-8); color: var(--color-font-primary); background: linear-gradient(135deg, var(--color-grey-20), var(--color-grey-25)); }
  .skill-name { font-size: var(--font-size-lg); font-weight: var(--font-weight-bold); }
  .result-count, .partial-error { color: var(--color-font-secondary); font-size: var(--font-size-sm); }
</style>
