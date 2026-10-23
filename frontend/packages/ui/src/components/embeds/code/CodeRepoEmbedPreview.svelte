<!--
  frontend/packages/ui/src/components/embeds/code/CodeRepoEmbedPreview.svelte

  Preview card for GitHub repository embeds.
  Uses UnifiedEmbedPreview as the common shell and shows repo identity, owner,
  language/license, and high-signal repository stats.
-->

<script lang="ts">

  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
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
    presentationOnly?: boolean;
    resultContext?: 'auto' | 'chat' | 'results';
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
    stars,
    forks,
    openIssues,
    updatedAt,
    status = 'finished',
    taskId,
    isMobile = false,
    presentationOnly = false,
    resultContext = 'auto',
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
  resultPreview={true}
  {presentationOnly}
  {resultContext}
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

  {#snippet details()}
    <div data-testid="code-repo-preview-details" class="catalog-result-preview">
      <ResultEmbedCard titleTestId="code-repo-title" title={displayName} sourceLabel={owner} description={description} faviconUrl={avatar} textFirst={true}>
        {#snippet facts()}{#if stars != null}<ResultEmbedInfo icon="Star" label="Stars" value={formatCount(stars)}>{#snippet children()}GitHub stars: {stars}{#if primaryLanguage || license}<p>{statusText}</p>{/if}{#if formatUpdated(updatedAt)}<p>Updated {formatUpdated(updatedAt)}</p>{/if}{/snippet}</ResultEmbedInfo>{/if}
{#if forks != null}<ResultEmbedInfo icon="GitFork" label="Forks" value={formatCount(forks)}>{#snippet children()}Repository forks: {forks}{/snippet}</ResultEmbedInfo>{/if}
{#if openIssues != null}<ResultEmbedInfo icon="CircleDot" label="Open issues" value={formatCount(openIssues)}>{#snippet children()}Open repository issues: {openIssues}{/snippet}</ResultEmbedInfo>{/if}
{#if stars == null && (primaryLanguage || license || formatUpdated(updatedAt))}<ResultEmbedInfo icon="Code" label="Repository details">{#snippet children()}{#if primaryLanguage || license}<p>{statusText}</p>{/if}{#if formatUpdated(updatedAt)}<p>Updated {formatUpdated(updatedAt)}</p>{/if}{/snippet}</ResultEmbedInfo>{/if}{/snippet}
      </ResultEmbedCard>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .catalog-result-preview { width: 100%; height: 100%; min-width: 0; }
</style>
