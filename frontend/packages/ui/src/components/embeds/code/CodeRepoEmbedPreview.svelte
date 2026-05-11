<!--
  frontend/packages/ui/src/components/embeds/code/CodeRepoEmbedPreview.svelte

  Preview card for GitHub repository embeds.
  Uses UnifiedEmbedPreview as the common shell and shows repo identity, owner,
  language/license, and high-signal repository stats.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { proxyImage, MAX_WIDTH_CHANNEL_THUMBNAIL } from '../../../utils/imageProxy';

  interface Props {
    id: string;
    url: string;
    fullName?: string;
    name?: string;
    ownerLogin?: string;
    ownerAvatarUrl?: string;
    description?: string;
    primaryLanguage?: string;
    licenseName?: string;
    licenseSpdxId?: string;
    stars?: number;
    forks?: number;
    openIssues?: number;
    updatedAt?: string;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    url,
    fullName,
    name,
    ownerLogin,
    ownerAvatarUrl,
    description,
    primaryLanguage,
    licenseName,
    licenseSpdxId,
    stars = 0,
    forks = 0,
    openIssues = 0,
    updatedAt,
    status = 'finished',
    taskId,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  const skillIconName = 'github';
  let displayName = $derived(fullName || [ownerLogin, name].filter(Boolean).join('/') || url);
  let shortName = $derived(name || displayName.split('/').pop() || displayName);
  let owner = $derived(ownerLogin || displayName.split('/')[0] || 'GitHub');
  let license = $derived(licenseSpdxId && licenseSpdxId !== 'NOASSERTION' ? licenseSpdxId : licenseName);
  let statusText = $derived([primaryLanguage, license].filter(Boolean).join(' · ') || 'GitHub repository');
  let avatar = $derived(proxyImage(ownerAvatarUrl, MAX_WIDTH_CHANNEL_THUMBNAIL));

  function formatCount(value: number | undefined): string {
    const count = typeof value === 'number' ? value : 0;
    if (count >= 1000) return `${(count / 1000).toFixed(count >= 10000 ? 0 : 1)}k`;
    return String(count);
  }

  function formatUpdated(value: string | undefined): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="code"
  skillId="repo"
  {skillIconName}
  {status}
  skillName={shortName}
  {taskId}
  {isMobile}
  {onFullscreen}
  faviconUrl={avatar}
  faviconIsCircular={true}
  customStatusText={statusText}
  showSkillIcon={true}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="repo-details" class:mobile={isMobileLayout} data-testid="code-repo-preview-details">
      <div class="repo-heading">
        {#if avatar}
          <img class="repo-avatar" src={avatar} alt="" loading="lazy" />
        {/if}
        <div class="repo-title-wrap">
          <div class="repo-owner">{owner}</div>
          <div class="repo-title" data-testid="code-repo-title">{shortName}</div>
        </div>
      </div>

      {#if description}
        <p class="repo-description">{description}</p>
      {/if}

      <div class="repo-stats" aria-label="Repository statistics">
        <span title="Stars">★ {formatCount(stars)}</span>
        <span title="Forks">⑂ {formatCount(forks)}</span>
        <span title="Open issues">! {formatCount(openIssues)}</span>
      </div>

      {#if formatUpdated(updatedAt)}
        <div class="repo-updated">Updated {formatUpdated(updatedAt)}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .repo-details {
    display: flex;
    flex-direction: column;
    gap: 8px;
    height: 100%;
    justify-content: center;
  }

  .repo-details.mobile {
    justify-content: flex-start;
    gap: 7px;
  }

  .repo-heading {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }

  .repo-avatar {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    flex: 0 0 auto;
  }

  .repo-title-wrap {
    min-width: 0;
  }

  .repo-owner,
  .repo-updated {
    font-size: 12px;
    color: var(--color-grey-70);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .repo-title {
    font-size: 16px;
    font-weight: 700;
    color: var(--color-grey-100);
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .repo-description {
    margin: 0;
    font-size: 13px;
    line-height: 1.35;
    color: var(--color-grey-80);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .repo-stats {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    font-size: 13px;
    font-weight: 600;
    color: var(--color-grey-80);
  }

  .repo-details.mobile .repo-title {
    font-size: 14px;
  }

  .repo-details.mobile .repo-description {
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }

  :global(.skill-icon[data-skill-icon="github"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/github.svg');
    mask-image: url('@openmates/ui/static/icons/github.svg');
  }
</style>
