<!--
  frontend/packages/ui/src/components/embeds/app_skill/GenericAppSkillEmbedPreview.svelte

  Generic preview card for app-skill-use embeds that do not have a bespoke
  renderer yet. Keeps public/example chats from exposing raw TOON metadata
  while preserving the standard UnifiedEmbedPreview card behavior.

  This is intentionally compact: specific skills should still get dedicated
  preview/fullscreen components when they need richer domain UI.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

  interface Props {
    id: string;
    appId: string;
    skillId: string;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    provider?: string;
    resultCount?: number;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    appId,
    skillId,
    status = 'processing',
    provider = '',
    resultCount,
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  function humanizeSkillId(value: string): string {
    return value
      .split(/[_-]+/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  function isMissingTranslation(value: string, key: string): boolean {
    return value === key || value === `[T:${key}]`;
  }

  let normalizedSkillId = $derived(skillId.replace(/-/g, '_'));
  let translationKey = $derived(`app_skills.${appId}.${normalizedSkillId}`);
  let fallbackSkillName = $derived(humanizeSkillId(skillId) || appId || 'App skill');
  let translatedSkillName = $derived($text(translationKey));
  let skillName = $derived(
    translatedSkillName && !isMissingTranslation(translatedSkillName, translationKey)
      ? translatedSkillName
      : fallbackSkillName,
  );
  let displaySkillId = $derived(humanizeSkillId(skillId) || skillId);

  let statusText = $derived.by(() => {
    const parts: string[] = [];
    if (typeof resultCount === 'number') {
      parts.push(`${resultCount} result${resultCount === 1 ? '' : 's'}`);
    }
    if (provider) parts.push(provider);
    return parts.join(' · ');
  });
</script>

<UnifiedEmbedPreview
  {id}
  {appId}
  {skillId}
  skillIconName="ai"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  customStatusText={statusText}
>
  {#snippet details()}
      <div class="generic-app-skill-details">
        <div class="generic-app-skill-eyebrow">{appId}</div>
      <div class="generic-app-skill-title">{displaySkillId}</div>
      {#if statusText}
        <div class="generic-app-skill-meta">{statusText}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .generic-app-skill-details {
    display: flex;
    height: 100%;
    flex-direction: column;
    justify-content: center;
    gap: var(--spacing-3);
    padding: var(--spacing-8);
    color: var(--color-font-primary);
    background:
      radial-gradient(circle at 20% 20%, color-mix(in srgb, var(--color-primary) 18%, transparent), transparent 36%),
      linear-gradient(135deg, var(--color-grey-20), var(--color-grey-25));
  }

  .generic-app-skill-eyebrow {
    color: var(--color-primary);
    font-size: var(--font-size-xs);
    font-weight: var(--font-weight-bold);
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .generic-app-skill-title {
    font-size: var(--font-size-lg);
    font-weight: var(--font-weight-bold);
    line-height: 1.15;
  }

  .generic-app-skill-meta {
    color: var(--color-font-secondary);
    font-size: var(--font-size-sm);
    line-height: 1.35;
  }
</style>
