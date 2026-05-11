<!--
  frontend/packages/ui/src/components/embeds/code/CodeRepoEmbedFullscreen.svelte

  Fullscreen view for GitHub repository embeds.
  Uses UnifiedEmbedFullscreen and renders repository details from decoded TOON
  content produced by the GitHub provider.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
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

<UnifiedEmbedFullscreen
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

  {#snippet content()}
    <div class="repo-fullscreen" data-testid="code-repo-fullscreen">
      <section class="repo-overview">
        <div class="repo-owner-row">
          {#if avatar}<img src={avatar} alt="" class="owner-avatar" loading="lazy" />{/if}
          <div>
            <p class="eyebrow">{owner}</p>
            <h2>{name}</h2>
          </div>
        </div>
        {#if description}<p class="description">{description}</p>{/if}
      </section>

      <section class="stats-grid" aria-label="Repository stats">
        <div><strong>{formatCount(dc.stars)}</strong><span>Stars</span></div>
        <div><strong>{formatCount(dc.forks)}</strong><span>Forks</span></div>
        <div><strong>{formatCount(dc.open_issues)}</strong><span>Open issues</span></div>
        <div><strong>{formatCount(dc.watchers)}</strong><span>Watchers</span></div>
      </section>

      <section class="details-card">
        <h3>Project Details</h3>
        <dl>
          <div><dt>Default branch</dt><dd>{asString(dc.default_branch) || 'unknown'}</dd></div>
          <div><dt>License</dt><dd>{license || 'unknown'}</dd></div>
          <div><dt>Created</dt><dd>{formatDate(dc.created_at) || 'unknown'}</dd></div>
          <div><dt>Last pushed</dt><dd>{formatDate(dc.pushed_at) || 'unknown'}</dd></div>
          {#if asString(dc.latest_release_tag)}<div><dt>Latest release</dt><dd>{asString(dc.latest_release_tag)}</dd></div>{/if}
          {#if firstLine(dc.latest_commit_message)}<div><dt>Latest commit</dt><dd>{firstLine(dc.latest_commit_message)}</dd></div>{/if}
        </dl>
      </section>

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
                {#if asString(contributor.avatar_url)}<img src={proxyImage(asString(contributor.avatar_url), MAX_WIDTH_CHANNEL_THUMBNAIL)} alt="" loading="lazy" />{/if}
                <span>{asString(contributor.login)}</span>
                <small>{formatCount(contributor.contributions)} commits</small>
              </a>
            {/each}
          </div>
        </section>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .repo-fullscreen {
    display: flex;
    flex-direction: column;
    gap: 18px;
    max-width: 860px;
    margin: 0 auto;
    padding: 24px 16px 120px;
  }

  .repo-overview,
  .details-card,
  .stats-grid > div {
    border: 1px solid var(--color-grey-20);
    border-radius: 18px;
    background: var(--color-background-secondary);
  }

  .repo-overview,
  .details-card {
    padding: 18px;
  }

  .repo-owner-row {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .owner-avatar,
  .contributor img {
    width: 42px;
    height: 42px;
    border-radius: 50%;
  }

  .eyebrow {
    margin: 0 0 2px;
    color: var(--color-grey-70);
    font-size: 14px;
  }

  h2,
  h3,
  .description {
    margin: 0;
  }

  h2 {
    font-size: 24px;
    line-height: 1.2;
  }

  h3 {
    font-size: 16px;
    margin-bottom: 12px;
  }

  .description {
    margin-top: 14px;
    color: var(--color-grey-80);
    line-height: 1.5;
  }

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
  }

  .stats-grid > div {
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .stats-grid strong {
    font-size: 20px;
    color: var(--color-grey-100);
  }

  .stats-grid span,
  dt,
  .contributor small {
    color: var(--color-grey-70);
    font-size: 13px;
  }

  dl {
    display: grid;
    gap: 10px;
    margin: 0;
  }

  dl div {
    display: grid;
    grid-template-columns: 140px 1fr;
    gap: 12px;
  }

  dd {
    margin: 0;
    color: var(--color-grey-100);
  }

  .languages {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .language-row {
    display: grid;
    grid-template-columns: 110px 1fr 52px;
    align-items: center;
    gap: 10px;
    font-size: 14px;
  }

  .language-bar {
    height: 8px;
    overflow: hidden;
    border-radius: 999px;
    background: var(--color-grey-20);
  }

  .language-bar i {
    display: block;
    height: 100%;
    border-radius: inherit;
    background: var(--color-app-code);
  }

  .contributors {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 10px;
  }

  .contributor {
    display: grid;
    grid-template-columns: 42px 1fr;
    grid-template-rows: auto auto;
    column-gap: 10px;
    align-items: center;
    color: var(--color-grey-100);
    text-decoration: none;
  }

  .contributor img {
    grid-row: 1 / span 2;
  }

  @container fullscreen (max-width: 620px) {
    .stats-grid {
      grid-template-columns: repeat(2, 1fr);
    }

    dl div,
    .language-row {
      grid-template-columns: 1fr;
      gap: 4px;
    }
  }

  :global(.skill-icon[data-skill-icon="github"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/github.svg');
    mask-image: url('@openmates/ui/static/icons/github.svg');
  }
</style>
