<!--
  frontend/packages/ui/src/components/embeds/code/CodeRepoEmbedFullscreen.svelte

  Fullscreen view for GitHub repository embeds.
  Uses UnifiedEmbedFullscreen and renders repository details from decoded TOON
  content produced by the GitHub provider.
-->

<script lang="ts">
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { proxyImage, MAX_WIDTH_CHANNEL_THUMBNAIL } from '../../../utils/imageProxy';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat
  }: Props = $props();

  let dc = $derived(data.decodedContent ?? {});
  let url = $derived(asString(dc.html_url) || asString(dc.url) || '');
  let fullName = $derived(asString(dc.full_name) || url);
  let name = $derived(asString(dc.name) || fullName.split('/').pop() || fullName);
  let owner = $derived(asString(dc.owner_login) || fullName.split('/')[0] || 'GitHub');
  let description = $derived(asString(dc.description));
  let avatar = $derived(proxyImage(asString(dc.owner_avatar_url), MAX_WIDTH_CHANNEL_THUMBNAIL));
  let language = $derived(asString(dc.primary_language));
  let license = $derived(asString(dc.license_spdx_id) && asString(dc.license_spdx_id) !== 'NOASSERTION' ? asString(dc.license_spdx_id) : asString(dc.license_name));
  let languages = $derived(toArray(dc.languages));
  let contributors = $derived(toArray(dc.contributors));

  function asString(value: unknown): string | undefined {
    return typeof value === 'string' && value.length > 0 ? value : undefined;
  }

  function asNumber(value: unknown): number {
    return typeof value === 'number' && Number.isFinite(value) ? value : 0;
  }

  function toArray(value: unknown): Record<string, unknown>[] {
    return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => item && typeof item === 'object' && !Array.isArray(item)) : [];
  }

  function formatCount(value: unknown): string {
    return new Intl.NumberFormat().format(asNumber(value));
  }

  function formatDate(value: unknown): string {
    if (typeof value !== 'string') return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' });
  }

  function firstLine(value: unknown): string {
    return asString(value)?.split('\n')[0] || '';
  }
</script>

<ResultEmbedFullscreen
  result={Object.fromEntries(["full_name", "name", "owner_login", "description", "html_url", "primary_language", "license_name", "stars", "forks", "open_issues"].filter(key => dc[key] !== undefined).map(key => [key, dc[key]]))}
  appId="code"
  skillId="repo"
  embedHeaderTitle={fullName}
  embedHeaderSubtitle={[language, license].filter(Boolean).join(' · ') || 'GitHub repository'}
  embedHeaderFaviconUrl={avatar}
  embedHeaderFaviconIsCircular={true}
  skillIconName="github"
  showSkillIcon={true}
  currentEmbedId={embedId}
  {onClose}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet embedHeaderCta()}
    {#if url}
      <EmbedHeaderCtaButton href={url} label="Open on GitHub" />
    {/if}
  {/snippet}

  {#snippet summary()}{#each [['stars', 'Star', 'Stars'], ['forks', 'GitFork', 'Forks'], ['open_issues', 'CircleDot', 'Open issues'], ['watchers', 'Eye', 'Watchers']] as [key, icon, label]}
{#if typeof dc[key] === 'number'}<ResultEmbedInfo {icon} {label} value={formatCount(dc[key])}>{#snippet children()}{label}: {formatCount(dc[key])}{/snippet}</ResultEmbedInfo>{/if}{/each}{/snippet}

  {#snippet detailContent()}
    <div class="repo-fullscreen" data-testid="code-repo-fullscreen">
      <section class="repo-overview">
        <div class="repo-owner-row">
          {#if avatar}<img src={avatar} alt="" class="owner-avatar" loading="lazy" use:handleImageError />{/if}
          <div>
            <p class="eyebrow">{owner}</p>
            <h2>{name}</h2>
          </div>
        </div>
        {#if description}<p class="description">{description}</p>{/if}
      </section>

      <div class="project-facts">
        {#if dc.default_branch || license || formatDate(dc.created_at) || formatDate(dc.pushed_at) || dc.latest_release_tag || firstLine(dc.latest_commit_message)}<ResultEmbedInfo icon="GitBranch" label="Project details">{#snippet children()}
          {#if asString(dc.default_branch)}<p>Default branch: {asString(dc.default_branch)}</p>{/if}
          {#if license}<p>License: {license}</p>{/if}
          {#if formatDate(dc.created_at)}<p>Created: {formatDate(dc.created_at)}</p>{/if}
          {#if formatDate(dc.pushed_at)}<p>Last pushed: {formatDate(dc.pushed_at)}</p>{/if}
          {#if asString(dc.latest_release_tag)}<p>Latest release: {asString(dc.latest_release_tag)}</p>{/if}
          {#if firstLine(dc.latest_commit_message)}<p>Latest commit: {firstLine(dc.latest_commit_message)}</p>{/if}
        {/snippet}</ResultEmbedInfo>{/if}
      </div>

      {#if languages.length > 0}
        <section class="details-card">
          <h3>Languages</h3>
          <div class="languages">
            {#each languages as row}
              <div class="language-row">
                <span>{asString(row.language)}</span>
                <div class="language-bar"><i style={`width: ${asNumber(row.percent)}%`}></i></div>
                <span>{asNumber(row.percent).toFixed(1)}%</span>
              </div>
            {/each}
          </div>
        </section>
      {/if}

      {#if contributors.length > 0}
        <section class="details-card">
          <h3>Top Contributors</h3>
          <div class="contributors">
            {#each contributors as contributor}
              <a class="contributor" href={asString(contributor.html_url)} target="_blank" rel="noopener noreferrer">
                {#if asString(contributor.avatar_url)}<img src={proxyImage(asString(contributor.avatar_url), MAX_WIDTH_CHANNEL_THUMBNAIL)} alt="" loading="lazy" use:handleImageError />{/if}
                <span>{asString(contributor.login)}</span>
                <small>{formatCount(contributor.contributions)} commits</small>
              </a>
            {/each}
          </div>
        </section>
      {/if}
    </div>
  {/snippet}
</ResultEmbedFullscreen>

<style>
 .repo-fullscreen { display:flex; flex-direction:column; gap:var(--spacing-6); width:100%; }
.repo-owner-row { display:flex; align-items:center; gap:var(--spacing-3); } .owner-avatar,.contributor img { width:36px;height:36px;border-radius:50%; } .eyebrow,.description,.contributor small {color:var(--color-font-secondary);} h2,h3,p {margin:0;} h2 {font-size:var(--font-size-h4);overflow-wrap:anywhere;} h3 {font-size:var(--font-size-p);margin-bottom:var(--spacing-3);} .description {margin-top:var(--spacing-3);line-height:1.5;} .languages,.contributors {display:flex;flex-direction:column;gap:var(--spacing-3);} .language-row {display:grid;grid-template-columns:minmax(4rem,1fr) 2fr 3rem;gap:var(--spacing-3);align-items:center;font-size:var(--font-size-small);} .language-bar {height:6px;border-radius:var(--radius-full);background:var(--color-grey-20);overflow:hidden;} .language-bar i {display:block;height:100%;background:var(--color-app-code);} .contributor {display:flex;align-items:center;flex-wrap:wrap;gap:var(--spacing-3);text-decoration:none;color:var(--color-font-primary);}
</style>
