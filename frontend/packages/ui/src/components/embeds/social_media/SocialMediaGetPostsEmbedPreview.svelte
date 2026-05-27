<!--
  frontend/packages/ui/src/components/embeds/social_media/SocialMediaGetPostsEmbedPreview.svelte

  Preview card for Social Media / Get posts parent embeds.
  Uses UnifiedEmbedPreview and shows the requested profile/page plus post count
  while child post embeds load separately.

  Architecture: docs/architecture/apps/social-media.md
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { socialProviderLabel } from './socialMediaEmbedUtils';

  interface Props {
    id: string;
    query?: string;
    provider?: string;
    result_count?: number;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    taskId?: string;
    skillTaskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    query: queryProp,
    provider: providerProp,
    result_count: resultCountProp,
    status: statusProp,
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let localQuery = $state('Social media posts');
  let localProvider = $state('Social Media');
  let localResultCount = $state(0);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localTaskId = $state<string | undefined>(undefined);
  let errorMessage = $state('');

  $effect(() => {
    localQuery = queryProp || 'Social media posts';
    localProvider = socialProviderLabel(providerProp);
    localResultCount = resultCountProp || 0;
    localStatus = statusProp || 'processing';
    localTaskId = taskIdProp;
  });

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (isStatus(data.status)) localStatus = data.status;
    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = socialProviderLabel(content.provider);
    if (typeof content.result_count === 'number') localResultCount = content.result_count;
    if (typeof content.error === 'string') errorMessage = content.error;
  }

  function isStatus(value: string): value is 'processing' | 'finished' | 'error' | 'cancelled' {
    return value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled';
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="social_media"
  skillId="get-posts"
  skillIconName="search"
  status={localStatus}
  skillName="Get posts"
  {isMobile}
  showSkillIcon={true}
  taskId={localTaskId}
  {onFullscreen}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="social-parent-preview">
      <div class="query">{localQuery}</div>
      <div class="provider">{$text('embeds.via')} {localProvider}</div>
      {#if localStatus === 'finished'}
        <div class="count">{localResultCount} posts</div>
      {:else if localStatus === 'error'}
        <div class="error">{errorMessage || $text('chat.an_error_occured')}</div>
      {:else}
        <div class="count">Fetching posts...</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .social-parent-preview {
    display: flex;
    height: 100%;
    flex-direction: column;
    justify-content: center;
    gap: var(--spacing-4);
    padding: var(--spacing-8);
  }

  .query {
    color: var(--color-text-primary);
    font-size: var(--font-size-lg);
    font-weight: 700;
    line-height: 1.15;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .provider,
  .count,
  .error {
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
  }

  .error {
    color: var(--color-danger, #d33);
  }
</style>
