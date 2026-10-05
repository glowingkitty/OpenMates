<!--
  frontend/packages/ui/src/components/embeds/wiki/WikipediaFullscreen.svelte

  Fullscreen view for Wikipedia topic links. Fetches article data on-demand
  through the OpenMates proxy when opened.

  Layout:
  - Hero thumbnail image (if available)
  - Article title + short Wikidata description
  - Extract text (article summary paragraph)
  - "Open on Wikipedia" CTA button
  - Loading skeleton while fetching

  This component does NOT use the embed system (no embed store, no encryption).
  Public article learning bundles are shared; saving a Study interest uses the encrypted memory store.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { locale, _ } from 'svelte-i18n';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE } from '../../../utils/imageProxy';
  import { getApiEndpoint } from '../../../config/api';
  import { wikipediaNameMatches, wikipediaArticleIdentity, type WikipediaArticleIdentity,
    type WikipediaRelatedArticle, type WikipediaLearningBundle } from '../../../utils/wikipediaLearning';

  interface Props {
    wikiTitle: string;
    language?: string | null;
    wikidataId?: string | null;
    displayText: string;
    thumbnailUrl?: string | null;
    description?: string | null;
    isAuthenticated: boolean;
    hasChatContext: boolean;
    onSendQuestion: (question: string, article: WikipediaArticleIdentity) => Promise<boolean>;
    onSaveInterest: (article: WikipediaArticleIdentity) => Promise<string>;
    onFindInterest: (article: WikipediaArticleIdentity) => string | null;
    onOpenInterest: (id: string) => void;
    onRelatedArticle: (article: WikipediaRelatedArticle) => void;
    onAuthenticate: () => void;
    onClose: () => void;
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let { wikiTitle, language = null, displayText, thumbnailUrl = null, description = null,
    isAuthenticated, hasChatContext, onSendQuestion, onSaveInterest, onFindInterest,
    onOpenInterest, onRelatedArticle, onAuthenticate, onClose, showChatButton = false, onShowChat }: Props = $props();
  const supportedLanguages = new Set(['en','de','zh','es','fr','pt','ru','ja','ko','it','tr','vi','id','pl','nl','ar','hi','th','cs','sv','he']);
  let wikipediaLanguage = $derived.by(() => {
    const selected = (language || $locale || 'en').toLowerCase().replace('_','-').split('-')[0];
    return supportedLanguages.has(selected) ? selected : 'en';
  });
  let isLoading = $state(true);
  let fetchError = $state(false);
  let fetchedTitle = $state('');
  let fetchedDescription = $state('');
  let fetchedImageUrl = $state('');
  let articleExtract = $state('');
  let articleTitle = $derived(fetchedTitle || displayText);
  let articleDescription = $derived(fetchedDescription || description || '');
  let articleImageUrl = $derived(fetchedImageUrl || thumbnailUrl || '');
  let article = $derived(wikipediaArticleIdentity(fetchedTitle || wikiTitle, wikipediaLanguage));
  let articleUrl = $derived(article.source_url);
  let proxiedImage = $derived(articleImageUrl ? proxyImage(articleImageUrl, MAX_WIDTH_HEADER_IMAGE) : '');
  let bundle = $state<WikipediaLearningBundle | null>(null);
  let guideLoading = $state(false);
  let guideError = $state(false);
  let actionError = $state<string | null>(null);
  let busyAction = $state<string | null>(null);
  let savedInterestId = $state<string | null>(null);
  let controller: AbortController;

  async function loadGuide() {
    if (!isAuthenticated || guideLoading || controller?.signal.aborted) return;
    guideLoading = true;
    guideError = false;
    try {
      const response = await fetch(getApiEndpoint(`/v1/wikipedia/learning?title=${encodeURIComponent(article.canonical_title)}&language=${wikipediaLanguage}`), {
        credentials: 'include', headers: { Accept: 'application/json' }, signal: controller.signal,
      });
      if (!response.ok) throw new Error('Guide unavailable');
      const data = await response.json() as WikipediaLearningBundle;
      if (data.language !== wikipediaLanguage || !wikipediaNameMatches(article.canonical_title, data.canonical_title)
        || !Array.isArray(data.questions) || !Array.isArray(data.related_articles)) throw new Error('Invalid guide');
      bundle = data;
    } catch {
      if (!controller.signal.aborted) guideError = true;
    } finally { guideLoading = false; }
  }

  onMount(() => {
    controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(getApiEndpoint(`/v1/wikipedia/summary?title=${encodeURIComponent(wikiTitle)}&language=${wikipediaLanguage}`), {
          credentials: 'include', headers: { Accept: 'application/json' }, signal: controller.signal,
        });
        if (!response.ok) throw new Error('Article unavailable');
        const data = await response.json();
        // Redirects must also preserve the visible topic name.
        if (!wikipediaNameMatches(displayText, data.title || data.canonical_title || '')) throw new Error('Article name mismatch');
        fetchedTitle = data.title || data.canonical_title;
        fetchedDescription = data.description || '';
        fetchedImageUrl = data.thumbnail_url || '';
        articleExtract = data.extract || '';
        savedInterestId = onFindInterest(wikipediaArticleIdentity(fetchedTitle, wikipediaLanguage));
        isLoading = false;
        await loadGuide();
      } catch { if (!controller.signal.aborted) fetchError = true; }
      finally { isLoading = false; }
    })();
    return () => controller.abort();
  });

  async function sendQuestion(question: string) {
    if (busyAction || !isAuthenticated) return;
    busyAction = question;
    actionError = null;
    try {
      if (await onSendQuestion(question, article)) onClose();
      else actionError = 'embeds.wiki.question_error.text';
    } catch { actionError = 'embeds.wiki.question_error.text'; }
    finally { busyAction = null; }
  }

  async function saveInterest() {
    if (busyAction || !isAuthenticated) return;
    busyAction = 'save';
    actionError = null;
    try { savedInterestId = await onSaveInterest(article); }
    catch { actionError = 'embeds.wiki.save_error.text'; }
    finally { busyAction = null; }
  }

  function handleOpenWikipedia() { window.open(articleUrl, '_blank', 'noopener,noreferrer'); }
</script>

<UnifiedEmbedFullscreen
  {showChatButton}
  {onShowChat}
  appId="study"
  skillId="study"
  skillIconName="study"
  embedHeaderTitle={articleTitle}
  embedHeaderSubtitle={articleDescription}
  showShare={false}
  {onClose}
>
  {#snippet embedHeaderCta()}
    {#if !isLoading && !fetchError}<EmbedHeaderCtaButton label={$_("embeds.wiki.open_on_wikipedia.text")} onclick={handleOpenWikipedia} />{/if}
  {/snippet}

  {#snippet content()}
    <div class="wiki-fullscreen-content" data-testid="wiki-fullscreen-content">
      {#if isLoading}
        <!-- Loading skeleton -->
        <div class="wiki-skeleton" role="status" aria-label={$_("embeds.wiki.loading.text")}>
          <div class="wiki-skeleton-image"></div>
          <div class="wiki-skeleton-title"></div>
          <div class="wiki-skeleton-desc"></div>
          <div class="wiki-skeleton-text"></div>
          <div class="wiki-skeleton-text short"></div>
        </div>
      {:else if fetchError}
        <div class="wiki-error">
          <p>{$_("embeds.wiki.article_not_found.text")}</p>
        </div>
      {:else}
        <!-- Hero image -->
        {#if proxiedImage}
          <div class="wiki-image-container">
            <img
              src={proxiedImage}
              alt={articleTitle}
              class="wiki-hero-image"
              onerror={handleImageError}
            />
          </div>
        {/if}

        <!-- Title + description -->
        <div class="wiki-header">
          <h2 class="wiki-title" data-testid="wiki-fullscreen-title">{articleTitle}</h2>
          {#if articleDescription}
            <p class="wiki-description">{articleDescription}</p>
          {/if}
        </div>

        <!-- Extract (article summary) -->
        {#if articleExtract}
          <div class="wiki-extract">
            <p>{articleExtract}</p>
          </div>
        {/if}

        <section class="wiki-learning" aria-label={$_('embeds.wiki.learn_more.text')} data-testid="wiki-learning">
          <h3>{$_('embeds.wiki.learn_more.text')}</h3>
          {#if !isAuthenticated}
            <button class="wiki-action" onclick={onAuthenticate} data-testid="wiki-learning-login">{$_('embeds.wiki.login_learning.text')}</button>
          {:else}
            <div class="wiki-memory-actions">
              {#if savedInterestId}
                <span role="status" data-testid="wiki-interest-saved">{$_('embeds.wiki.interest_saved.text')}</span>
                <button class="wiki-action" onclick={() => onOpenInterest(savedInterestId!)} disabled={!!busyAction}>{$_('embeds.wiki.edit_interest.text')}</button>
              {:else}
                <button class="wiki-action" onclick={saveInterest} disabled={!!busyAction} data-testid="wiki-save-interest">
                  {$_(busyAction === 'save' ? 'embeds.wiki.saving_interest.text' : 'embeds.wiki.save_interest.text')}
                </button>
              {/if}
            </div>
            <p class="wiki-learning-note">{$_('embeds.wiki.memory_privacy.text')}</p>
            {#if guideLoading}
              <p role="status" data-testid="wiki-guide-loading">{$_('embeds.wiki.loading_questions.text')}</p>
            {:else if guideError}
              <p role="status">{$_('embeds.wiki.guide_error.text')}</p>
              <button class="wiki-action" onclick={loadGuide} data-testid="wiki-guide-retry">{$_('embeds.wiki.retry_questions.text')}</button>
            {:else if bundle}
              <h4>{$_('embeds.wiki.questions.text')}</h4>
              <p class="wiki-learning-note">{$_(hasChatContext ? 'embeds.wiki.question_existing_chat.text' : 'embeds.wiki.question_new_chat.text')}</p>
              <div class="wiki-questions">
                {#each bundle.questions as question}
                  <button class="wiki-action wiki-question" onclick={() => sendQuestion(question)} disabled={!!busyAction} data-testid="wiki-question">
                    {question}
                  </button>
                {/each}
              </div>
              {#if bundle.related_articles.length}
                <h4>{$_('embeds.wiki.related_articles.text')}</h4>
                <div class="wiki-related">
                  {#each bundle.related_articles as related}
                    <button class="wiki-action" onclick={() => onRelatedArticle(related)} disabled={!!busyAction} data-testid="wiki-related-article">
                      <span>{related.title}</span>
                      {#if related.description}<small>{related.description}</small>{/if}
                    </button>
                  {/each}
                </div>
              {/if}
            {/if}
            {#if actionError}<p role="alert">{$_(actionError)}</p>{/if}
          {/if}
        </section>

        <!-- Attribution -->
        <p class="wiki-attribution">
          {$_('embeds.wiki.source_attribution.text')}
        </p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .wiki-fullscreen-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-16);
    max-width: 600px;
    margin: 0 auto;
    padding: var(--spacing-16);
    padding-bottom: var(--spacing-24);
  }

  /* Hero image */
  .wiki-image-container {
    width: 100%;
    max-width: 511px;
    border-radius: var(--radius-12);
    overflow: hidden;
  }

  .wiki-hero-image {
    width: 100%;
    height: auto;
    display: block;
    object-fit: cover;
    max-height: 340px;
  }

  /* Header: title + description */
  .wiki-header {
    width: 100%;
    text-align: left;
  }

  .wiki-title {
    font-size: var(--font-size-h3);
    font-weight: 600;
    color: var(--color-grey-90);
    margin: 0 0 var(--spacing-4) 0;
    line-height: 1.3;
  }

  .wiki-description {
    font-size: var(--font-size-small);
    color: var(--color-grey-70);
    margin: 0;
    font-style: italic;
  }

  /* Extract text */
  .wiki-extract {
    width: 100%;
    text-align: left;
  }

  .wiki-extract p {
    font-size: var(--font-size-p);
    color: var(--color-grey-80);
    line-height: 1.65;
    margin: 0;
  }

  /* Study skill icon mapping — renders the flat study.svg as mask-image (white fill)
     on the EmbedHeader's center + decorative icons, instead of the gradient circle. */
  :global(.skill-icon[data-skill-icon="study"]),
  :global(.header-skill-icon[data-skill-icon="study"]),
  :global(.deco-skill-icon[data-skill-icon="study"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/study.svg');
    mask-image: url('@openmates/ui/static/icons/study.svg');
  }

  /* Attribution */
  .wiki-attribution {
    font-size: var(--font-size-xxs);
    color: var(--color-grey-70);
    text-align: center;
    margin: 0;
  }

  /* Error state */
  .wiki-error {
    text-align: center;
    padding: var(--spacing-32);
  }

  .wiki-error p {
    font-size: var(--font-size-p);
    color: var(--color-grey-50);
  }

  /* Loading skeleton */
  .wiki-skeleton {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-12);
  }

  .wiki-skeleton-image {
    width: 100%;
    height: 200px;
    border-radius: var(--radius-12);
    background: var(--color-grey-10);
    animation: wiki-pulse 1.5s ease-in-out infinite;
  }

  .wiki-skeleton-title {
    width: 60%;
    height: 24px;
    border-radius: var(--radius-6);
    background: var(--color-grey-10);
    animation: wiki-pulse 1.5s ease-in-out infinite;
    animation-delay: 0.1s;
  }

  .wiki-skeleton-desc {
    width: 40%;
    height: 16px;
    border-radius: var(--radius-6);
    background: var(--color-grey-10);
    animation: wiki-pulse 1.5s ease-in-out infinite;
    animation-delay: 0.2s;
  }

  .wiki-skeleton-text {
    width: 100%;
    height: 14px;
    border-radius: var(--radius-6);
    background: var(--color-grey-10);
    animation: wiki-pulse 1.5s ease-in-out infinite;
    animation-delay: 0.3s;
  }

  .wiki-skeleton-text.short {
    width: 75%;
  }

  @keyframes wiki-pulse {
    0%, 100% { opacity: 0.4; }
    50% { opacity: 0.8; }
  }
  .wiki-learning { width: 100%; display: flex; flex-direction: column; gap: var(--spacing-12); text-align: left; }
  .wiki-learning h3, .wiki-learning h4, .wiki-learning p { margin: 0; }
  .wiki-learning h3 { font-size: var(--font-size-h3); }
  .wiki-learning h4 { font-size: var(--font-size-p); }
  .wiki-learning-note { font-size: var(--font-size-xs); color: var(--color-grey-70); line-height: 1.5; }
  .wiki-questions, .wiki-related { display: flex; flex-direction: column; gap: var(--spacing-8); }
  .wiki-memory-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-8); }
  .wiki-action { min-height: 44px; padding: var(--spacing-12); border: 1px solid var(--color-grey-20); border-radius: var(--radius-8); background: var(--color-grey-0); color: var(--color-grey-90); font: inherit; font-size: var(--font-size-small); text-align: left; cursor: pointer; overflow-wrap: anywhere; }
  .wiki-action:hover { background: var(--color-grey-10); }
  .wiki-action:focus-visible { outline: 2px solid var(--color-app-study-start); outline-offset: 2px; }
  .wiki-action:disabled { cursor: wait; opacity: 0.6; }
  .wiki-related .wiki-action { display: flex; flex-direction: column; align-items: flex-start; }
  .wiki-related small { font-weight: 400; display: block; color: var(--color-grey-70); margin-top: var(--spacing-4); }
</style>
