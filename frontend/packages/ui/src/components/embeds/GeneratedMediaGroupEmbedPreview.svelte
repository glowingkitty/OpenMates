<!-- Skill-use parent card for one invocation with zero or more generated children. -->
<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from './UnifiedEmbedPreview.svelte';
  import GeneratedMediaThumbnails from './GeneratedMediaThumbnails.svelte';
  import { generatedMediaChildIds } from './generatedMediaGroup';

  interface Props {
    id: string;
    appId: string;
    skillId: string;
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    resultCount?: number;
    childEmbedIds?: string[];
    /** Prompt supplied by the manifest; otherwise taken from the first child. */
    prompt?: string;
    error?: string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id, appId, skillId, status, resultCount, childEmbedIds = [], prompt: promptProp, error = '',
    taskId, isMobile = false, onFullscreen,
  }: Props = $props();
  let currentCount = $state<number | undefined>(undefined);
  let currentError = $state<string | undefined>(undefined);
  let currentChildIds = $state<string[] | undefined>(undefined);
  let childPrompt = $state<string | undefined>(undefined);
  const prompt = $derived(promptProp?.trim() || childPrompt);
  const skillName = $derived($text(`app_skills.${appId}.${skillId}`));
  const childIds = $derived(currentChildIds ?? childEmbedIds);
  const count = $derived(Math.max(currentCount ?? 0, resultCount ?? 0, childIds.length));

  function handleUpdated(data: { decodedContent: Record<string, unknown> | null }) {
    const content = data.decodedContent;
    if (!content) return;
    currentCount = Math.max(
      typeof content.result_count === 'number' ? content.result_count : 0,
      generatedMediaChildIds(content).length,
    );
    currentError = typeof content.error === 'string' ? content.error : undefined;
    const ids = generatedMediaChildIds(content);
    if (ids.length > 0) currentChildIds = ids;
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
      {#if childIds.length > 0}
        <GeneratedMediaThumbnails childEmbedIds={childIds} onPrompt={(value) => { childPrompt = value; }} />
      {/if}
      {#if prompt}<p class="prompt" data-testid="generated-media-parent-prompt">{prompt}</p>{/if}
      {#if currentError || error}<span class="partial-error">{currentError || error}</span>{/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .generated-media-parent { display: flex; flex-direction: column; gap: var(--spacing-3); height: 100%; min-height: 0; box-sizing: border-box; padding: var(--spacing-3) 0 var(--spacing-6); color: var(--color-font-primary); }
  /* The first lines of the prompt that fit; the full prompt stays in fullscreen. */
  .prompt { margin: 0; flex: 0 0 auto; font-size: var(--font-size-sm); line-height: 1.3; color: var(--color-font-secondary); display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; overflow: hidden; overflow-wrap: anywhere; }
  .partial-error { color: var(--color-font-secondary); font-size: var(--font-size-sm); }
</style>
