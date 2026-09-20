<script lang="ts">
  import type {
    NewsroomAction,
    NewsroomArticleContent,
    NewsroomItem,
    NewsroomSurfaceData,
    NewsroomView,
  } from './types';

  interface Props {
    view: NewsroomView;
    locale: 'en' | 'de';
    data: NewsroomSurfaceData;
    onAction: (action: NewsroomAction) => void;
  }

  let { view, locale, data, onAction }: Props = $props();

  let searchOpen = $state(false);
  let searchTerm = $state('');
  let activeSlide = $state(0);

  const isBlogSurface = $derived(view === 'blog' || view === 'blog-post');
  const isIndex = $derived(view === 'news' || view === 'blog');
  const sidebarItems = $derived(isBlogSurface ? data.blogItems : data.newsItems);
  const pageLabel = $derived(isBlogSurface ? data.blogLabel : data.newsLabel);
  const hero = $derived(isBlogSurface ? data.heroBlog : data.heroNews);
  const primaryItems = $derived(isBlogSurface ? data.blogItems : data.newsItems);
  const selectedArticle = $derived(view === 'blog-post' ? data.blogArticle : data.releaseArticle);

  const filteredPrimaryItems = $derived.by(() => {
    const query = searchTerm.trim().toLocaleLowerCase(locale);
    if (!query) return primaryItems;
    return primaryItems.filter((item) =>
      `${item.eyebrow} ${item.title} ${item.excerpt}`.toLocaleLowerCase(locale).includes(query),
    );
  });

  function act(type: NewsroomAction['type'], itemId?: string) {
    onAction({ type, itemId });
  }

  function setSlide(next: number) {
    activeSlide = (next + 3) % 3;
  }
</script>

{#snippet icon(name: string)}
    <span class={`clickable-icon icon_${name} newsroom-icon`} aria-hidden="true"></span>
  {/snippet}

  {#snippet media(shape: NewsroomItem['mediaShape'], label: string, showPlay = true)}
    <div class:portrait={shape === 'portrait'} class="media-placeholder" aria-label={label}>
      <div class="media-grid" aria-hidden="true"></div>
      {#if showPlay}
        <span class="media-play" aria-hidden="true">{@render icon('play')}</span>
      {/if}
    </div>
  {/snippet}

  {#snippet card(item: NewsroomItem, wide = false)}
    <button
      type="button"
      class:wide
      class:portrait-card={item.mediaShape === 'portrait'}
      class="content-card"
      data-testid={`newsroom-card-${item.id}`}
      onclick={() => act(item.kind === 'coverage' ? 'open-social' : 'open-item', item.id)}
    >
      {#if item.mediaShape !== 'none'}
        {@render media(item.mediaShape, `${item.title} media preview`, item.kind !== 'blog')}
      {/if}
      <span class="card-copy">
        <span class="eyebrow-row">
          <span class="eyebrow">{item.eyebrow}</span>
          {#if item.language}<span class="language-pill">{item.language}</span>{/if}
        </span>
        <strong>{item.title}</strong>
        <span class="card-excerpt">{item.excerpt}</span>
        <span class="card-meta">
          <span>{item.publishedLabel}</span>
          {#if item.readTime}<span>{item.readTime}</span>{/if}
        </span>
      </span>
    </button>
  {/snippet}

  {#snippet sectionHeader(title: string, searchable = false)}
    <div class="section-header">
      <h2>{title}</h2>
      {#if searchable}
        <div class="search-control" class:open={searchOpen}>
          {#if searchOpen}
            <label>
              <span class="sr-only">{data.searchLabel}</span>
              <input
                data-testid="newsroom-search-input"
                type="search"
                placeholder={data.searchLabel}
                bind:value={searchTerm}
              />
            </label>
          {/if}
          <button
            data-testid="newsroom-search-toggle"
            type="button"
            aria-label={data.searchLabel}
            aria-expanded={searchOpen}
            onclick={() => (searchOpen = !searchOpen)}
          >
            {@render icon(searchOpen ? 'close' : 'search')}
            <span>{data.searchLabel}</span>
          </button>
        </div>
      {/if}
    </div>
  {/snippet}

  {#snippet socialRail()}
    <section class="content-section" aria-labelledby="social-title">
      <div class="section-header">
        <h2 id="social-title">{data.socialLabel}</h2>
      </div>
      <div class="social-rail" data-testid="newsroom-social-rail">
        {#each data.socialItems as item (item.id)}
          {@render card(item)}
        {/each}
      </div>
      <div class="follow-row">
        <span>{data.followLabel}</span>
        <span>Instagram</span><span>Mastodon</span><span>LinkedIn</span>
      </div>
    </section>
  {/snippet}

  {#snippet mediaSlideshow(label: string)}
    <div class="slideshow" data-testid="newsroom-slideshow">
      <button type="button" class="slide-arrow previous" aria-label="Previous media" onclick={() => setSlide(activeSlide - 1)}>‹</button>
      <div class="slide-frame">
        {@render media('landscape', `${label}, slide ${activeSlide + 1}`, true)}
        <span class="slide-number">{activeSlide + 1} / 3</span>
      </div>
      <button type="button" class="slide-arrow next" aria-label="Next media" onclick={() => setSlide(activeSlide + 1)}>›</button>
      <div class="slide-dots" aria-hidden="true">
        {#each [0, 1, 2] as dot}
          <span class:active={dot === activeSlide}></span>
        {/each}
      </div>
    </div>
  {/snippet}

  {#snippet articleBody(article: NewsroomArticleContent, isRelease: boolean)}
    <article class="article-body">
      <header class="article-byline">
        <span class="avatar" aria-hidden="true">OM</span>
        <span><strong>{article.byline}</strong><small>{article.publishedLabel}</small></span>
      </header>

      <p class="article-intro">{article.intro}</p>
      <p>{article.paragraphs[0]}</p>
      {@render mediaSlideshow(isRelease ? 'Workflow automation demo' : 'Agentic coding guardrails')}
      <p>{article.paragraphs[1]}</p>
      <div class="article-media-row">
        {@render media('landscape', 'Article example media', true)}
      </div>
      <p>{article.paragraphs[2]}</p>

      <aside class="prompt-card">
        <span>{article.promptTitle}</span>
        <blockquote>{article.promptBody}</blockquote>
        <button type="button" onclick={() => act('open-app')}>
          {@render icon('copy')}
          Copy
        </button>
      </aside>

      <p class="contact-line">
        {isRelease ? 'For further questions, contact press@openmates.org' : 'Questions or feedback? marco@openmates.org'}
      </p>
    </article>
  {/snippet}

<div class="newsroom-shell" data-testid="newsroom-surface" data-view={view} data-locale={locale}>
  <header class="topbar">
    <a href={isBlogSurface ? '/blog' : '/news'} class="brand" onclick={(event) => event.preventDefault()}>
      <strong>{data.brand}</strong>
      <span>{pageLabel}</span>
    </a>
    <button type="button" class="primary-cta" onclick={() => act(view === 'release' ? 'try-feature' : 'open-app')}>
      {view === 'release' ? data.tryItLabel : data.openAppLabel}
    </button>
  </header>

  <div class="surface-layout">
    <aside class="publication-sidebar" aria-label={`${pageLabel} archive`}>
      <div class="sidebar-heading">
        <strong>{pageLabel}</strong>
        <span>{isBlogSurface ? data.latestBlogLabel : data.latestNewsLabel}</span>
      </div>
      <nav>
        {#each sidebarItems as item (item.id)}
          <button type="button" onclick={() => act('open-item', item.id)}>
            <span class="sidebar-dot" aria-hidden="true"></span>
            <span><strong>{item.title}</strong><small>{item.publishedLabel}</small></span>
          </button>
        {/each}
      </nav>
    </aside>

    <nav class="mobile-publication-rail" aria-label={`${pageLabel} recent publications`}>
      {#each sidebarItems.slice(0, 4) as item (item.id)}
        <button type="button" onclick={() => act('open-item', item.id)}>
          <span>{item.eyebrow}</span>
          <strong>{item.title}</strong>
        </button>
      {/each}
    </nav>

    <main>
      {#if view === 'social-post'}
        <section class="social-detail" aria-labelledby="social-post-title">
          <div class="detail-actions">
            <button type="button" aria-label="Close preview" onclick={() => act('open-item')}>{@render icon('close')}</button>
          </div>
          <div class="social-detail-grid">
            {@render media('portrait', 'OpenMates social post media', false)}
            <div class="social-detail-copy">
              <div class="social-author"><span class="avatar" aria-hidden="true">OM</span><strong>OpenMates</strong></div>
              <h1 id="social-post-title">{data.socialItems[0].title}</h1>
              <p>{data.socialItems[0].excerpt} This archived copy remains readable and searchable without loading media from a social platform.</p>
              <time>{data.socialItems[0].publishedLabel}</time>
              <button class="text-action" type="button" onclick={() => act('open-social', data.socialItems[0].id)}>
                {data.viewOriginalLabel} ↗
              </button>
            </div>
          </div>
          <hr />
          {@render sectionHeader(data.morePostsLabel)}
          <div class="social-rail">
            {#each data.socialItems.slice(1) as item (item.id)}{@render card(item)}{/each}
          </div>
          <div class="follow-row"><span>{data.followLabel}</span><span>Instagram</span><span>Mastodon</span><span>LinkedIn</span></div>
        </section>
      {:else}
        <section class="feature-hero" class:detail-hero={!isIndex} aria-labelledby="newsroom-hero-title">
          <div class="hero-copy">
            {#if !isIndex}
              <button class="hero-close" type="button" aria-label="Close article" onclick={() => act('open-item')}>{@render icon('close')}</button>
            {/if}
            {#if hero.kicker}<span class="hero-kicker">{hero.kicker}</span>{/if}
            <span class="hero-eyebrow">{hero.eyebrow}</span>
            <h1 id="newsroom-hero-title">{hero.title}</h1>
            <p>{hero.meta}</p>
            {#if isIndex}
              <button type="button" class="hero-link" onclick={() => act('open-item', isBlogSurface ? data.blogItems[0].id : 'workflow-automation')}>
                {@render icon('search')}{hero.actionLabel}
              </button>
            {/if}
          </div>
          <div class="hero-media">{@render media('landscape', `${hero.title} video`, true)}</div>
        </section>

        {#if isIndex}
          <div class="index-content">
            <section class="content-section" aria-labelledby="latest-title">
              {@render sectionHeader(isBlogSurface ? data.latestBlogLabel : data.latestNewsLabel, true)}
              {#if filteredPrimaryItems.length > 0}
                <div class="content-grid">
                  {#each filteredPrimaryItems as item, index (item.id)}
                    {@render card(item, index === 0)}
                  {/each}
                </div>
              {:else}
                <p class="empty-state">No matching posts.</p>
              {/if}
              {#if !isBlogSurface}
                <div class="news-actions">
                  <button type="button" onclick={() => act('press-kit')}>{@render icon('download')}{data.pressKitLabel}</button>
                  <button type="button" onclick={() => act('press-inquiry')}>@ {data.pressInquiryLabel}</button>
                  <button type="button" onclick={() => act('subscribe-news')}>+ {data.subscribeLabel}</button>
                </div>
              {/if}
            </section>

            {@render socialRail()}

            {#if isBlogSurface}
              <section class="content-section" aria-labelledby="news-cross-title">
                {@render sectionHeader(data.latestNewsLabel)}
                <div class="content-grid compact">
                  {#each data.newsItems.slice(0, 3) as item, index (item.id)}{@render card(item, index === 0)}{/each}
                </div>
              </section>
            {:else}
              <section class="content-section" aria-labelledby="coverage-title">
                {@render sectionHeader(data.coverageLabel)}
                <div class="content-grid compact">
                  {#each data.coverageItems as item (item.id)}{@render card(item)}{/each}
                </div>
              </section>
              <section class="content-section" aria-labelledby="blog-cross-title">
                {@render sectionHeader(data.latestBlogLabel)}
                <div class="content-grid compact">
                  {#each data.blogItems.slice(0, 2) as item (item.id)}{@render card(item)}{/each}
                </div>
              </section>
            {/if}
          </div>
        {:else}
          <div class="detail-content">
            {#if view === 'release'}
              <div class="release-summary">
                <button type="button" class="speak-placeholder">▶ Speak announcement</button>
                <p>{selectedArticle.intro}</p>
                <div class="news-actions">
                  <button type="button" onclick={() => act('press-kit')}>{@render icon('download')}{data.pressKitLabel}</button>
                  <button type="button" onclick={() => act('subscribe-news')}>+ {data.subscribeLabel}</button>
                </div>
              </div>
            {/if}
            {@render articleBody(selectedArticle, view === 'release')}
            <section class="content-section related-section" aria-labelledby="related-title">
              {@render sectionHeader(view === 'release' ? data.latestNewsLabel : data.relatedLabel)}
              <div class="content-grid compact">
                {#each (view === 'release' ? data.newsItems.slice(1, 3) : data.blogItems.slice(1, 3)) as item (item.id)}
                  {@render card(item)}
                {/each}
              </div>
            </section>
          </div>
        {/if}
      {/if}
    </main>
  </div>
</div>

<style>
  .newsroom-shell {
    width: min(100%, 90rem);
    min-height: 58rem;
    margin: 0 auto;
    overflow: hidden;
    border: 1px solid var(--color-grey-25);
    border-radius: var(--radius-6);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: var(--shadow-lg);
  }

  button, input { font: inherit; }
  button { color: inherit; }
  button:focus-visible, a:focus-visible, input:focus-visible {
    outline: 0.125rem solid var(--color-button-primary);
    outline-offset: 0.1875rem;
  }

  .sr-only, .sr-only:not(:focus):not(:active) {
    position: absolute;
    width: 0.0625rem;
    height: 0.0625rem;
    padding: 0;
    margin: -0.0625rem;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  .topbar {
    position: sticky;
    top: 0;
    z-index: var(--z-index-sticky);
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 4.5rem;
    padding: var(--spacing-8) var(--spacing-12);
    border-bottom: 1px solid var(--color-grey-25);
    background: color-mix(in srgb, var(--color-grey-0) 94%, transparent);
    backdrop-filter: blur(1rem);
  }

  .brand {
    display: grid;
    color: var(--color-font-primary);
    text-decoration: none;
    line-height: 1.05;
  }

  .brand strong { color: var(--color-primary-start); font-size: var(--font-size-p); }
  .brand span { color: var(--color-font-secondary); font-size: var(--font-size-xxs); }

  .primary-cta {
    min-height: 2.75rem;
    padding: 0 var(--spacing-10);
    border: 0;
    border-radius: var(--radius-full);
    background: var(--color-button-primary);
    color: var(--color-font-button);
    box-shadow: var(--shadow-md);
    cursor: pointer;
    font-weight: 700;
  }

  .surface-layout {
    display: grid;
    grid-template-columns: 17rem minmax(0, 1fr);
    min-height: calc(58rem - 4.5rem);
  }

  .publication-sidebar {
    padding: var(--spacing-12) var(--spacing-8);
    border-right: 1px solid var(--color-grey-25);
    background: var(--color-grey-10);
  }

  .sidebar-heading { display: grid; gap: var(--spacing-2); margin-bottom: var(--spacing-10); }
  .sidebar-heading strong { font-size: var(--font-size-h3); }
  .sidebar-heading span { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
  .publication-sidebar nav { display: grid; gap: var(--spacing-2); }

  .publication-sidebar nav button {
    display: grid;
    grid-template-columns: 0.625rem minmax(0, 1fr);
    gap: var(--spacing-5);
    align-items: start;
    width: 100%;
    padding: var(--spacing-6);
    border: 0;
    border-radius: var(--radius-4);
    background: transparent;
    cursor: pointer;
    text-align: left;
  }

  .publication-sidebar nav button:hover { background: var(--color-grey-20); }
  .publication-sidebar nav button > span:last-child { display: grid; gap: var(--spacing-2); min-width: 0; }
  .publication-sidebar nav strong { font-size: var(--font-size-small); line-height: 1.3; }
  .publication-sidebar nav small { color: var(--color-font-secondary); font-size: var(--font-size-tiny); }
  .sidebar-dot { width: 0.625rem; height: 0.625rem; margin-top: 0.25rem; border-radius: var(--radius-full); background: var(--color-primary); }

  .mobile-publication-rail { display: none; }
  main { min-width: 0; padding: var(--spacing-8); background: var(--color-grey-20); }

  .feature-hero {
    position: relative;
    display: grid;
    grid-template-columns: minmax(15rem, 0.85fr) minmax(20rem, 1.15fr);
    gap: var(--spacing-16);
    align-items: center;
    min-height: 18rem;
    padding: var(--spacing-20);
    overflow: hidden;
    border-radius: var(--radius-6);
    background: var(--color-primary);
    color: var(--color-font-button);
    box-shadow: var(--shadow-lg);
  }

  .hero-copy { position: relative; display: grid; justify-items: start; gap: var(--spacing-5); z-index: 1; }
  .hero-copy h1 { max-width: 20ch; margin: 0; font-size: clamp(1.75rem, 3vw, 3rem); line-height: 1.05; }
  .hero-copy p { margin: 0; opacity: 0.8; font-size: var(--font-size-small); }
  .hero-kicker, .hero-eyebrow { font-size: var(--font-size-xs); font-weight: 700; opacity: 0.86; }
  .hero-kicker { text-transform: uppercase; letter-spacing: 0.08em; }

  .hero-link, .hero-close {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-4);
    min-height: 2.75rem;
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font-weight: 700;
  }

  .hero-close { position: absolute; top: calc(-1 * var(--spacing-10)); right: calc(-1 * var(--spacing-10)); width: 2.75rem; justify-content: center; border-radius: var(--radius-full); background: color-mix(in srgb, var(--color-grey-100) 18%, transparent); }
  .hero-media { min-width: 0; }

  .media-placeholder {
    position: relative;
    aspect-ratio: 16 / 9;
    overflow: hidden;
    border-radius: var(--radius-5);
    background: var(--color-grey-10);
    box-shadow: var(--shadow-md);
  }

  .media-placeholder.portrait { aspect-ratio: 4 / 5; }
  .media-grid {
    position: absolute;
    inset: 0;
    background:
      linear-gradient(45deg, var(--color-grey-20) 25%, transparent 25%, transparent 75%, var(--color-grey-20) 75%),
      linear-gradient(45deg, var(--color-grey-20) 25%, var(--color-grey-10) 25%, var(--color-grey-10) 75%, var(--color-grey-20) 75%);
    background-position: 0 0, 1rem 1rem;
    background-size: 2rem 2rem;
  }

  .media-play {
    position: absolute;
    inset: 50% auto auto 50%;
    display: grid;
    place-items: center;
    width: 3.25rem;
    height: 3.25rem;
    transform: translate(-50%, -50%);
    border-radius: var(--radius-full);
    background: color-mix(in srgb, var(--color-grey-0) 86%, transparent);
    color: var(--color-font-primary);
    box-shadow: var(--shadow-md);
  }

  .newsroom-icon { width: 1.1rem; height: 1.1rem; color: currentColor; }
  .index-content, .detail-content { width: min(100%, 58rem); margin: 0 auto; }
  .content-section { margin-top: var(--spacing-24); }
  .section-header { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-8); margin-bottom: var(--spacing-10); }
  .section-header h2 { margin: 0; font-size: var(--font-size-h2); }

  .search-control, .search-control button { display: flex; align-items: center; gap: var(--spacing-4); }
  .search-control { padding: var(--spacing-2); border: 1px solid transparent; border-radius: var(--radius-full); }
  .search-control.open { border-color: var(--color-grey-30); background: var(--color-grey-0); }
  .search-control input { width: min(14rem, 30vw); min-height: 2.5rem; border: 0; background: transparent; color: var(--color-font-primary); font-size: var(--font-size-p); }
  .search-control input:focus-visible { outline: none; }
  .search-control button { min-height: 2.5rem; padding: 0 var(--spacing-6); border: 0; border-radius: var(--radius-full); background: transparent; cursor: pointer; color: var(--color-font-secondary); }

  .content-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--spacing-10); }
  .content-grid.compact { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .content-card {
    display: grid;
    grid-template-rows: auto 1fr;
    min-width: 0;
    overflow: hidden;
    padding: 0;
    border: 1px solid var(--color-grey-25);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-sm);
    cursor: pointer;
    text-align: left;
    transition:
      transform var(--duration-fast) var(--easing-default),
      box-shadow var(--duration-fast) var(--easing-default);
  }

  .content-card:hover { transform: translateY(-0.125rem); box-shadow: var(--shadow-md); }
  .content-card.wide { grid-column: 1 / -1; grid-template-columns: minmax(0, 1.15fr) minmax(15rem, 0.85fr); grid-template-rows: auto; }
  .content-card.wide .media-placeholder { border-radius: 0; height: 100%; }
  .content-card > .media-placeholder { border-radius: 0; box-shadow: none; }
  .card-copy { display: grid; align-content: start; gap: var(--spacing-5); padding: var(--spacing-10); min-width: 0; }
  .card-copy strong { font-size: var(--font-size-h3); line-height: 1.2; }
  .eyebrow-row, .card-meta { display: flex; justify-content: space-between; gap: var(--spacing-4); }
  .eyebrow, .card-meta, .language-pill { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
  .card-excerpt { color: var(--color-font-tertiary); font-size: var(--font-size-small); line-height: 1.5; }
  .language-pill { padding: var(--spacing-1) var(--spacing-4); border-radius: var(--radius-full); background: var(--color-grey-20); }

  .social-rail { display: flex; gap: var(--spacing-10); overflow-x: auto; padding: var(--spacing-2) var(--spacing-2) var(--spacing-8); scroll-snap-type: x proximity; }
  .social-rail .content-card { flex: 0 0 14rem; scroll-snap-align: start; }
  .social-rail .card-excerpt { display: none; }
  .follow-row { display: flex; flex-wrap: wrap; justify-content: center; gap: var(--spacing-8); color: var(--color-font-secondary); font-size: var(--font-size-xs); }

  .news-actions { display: flex; flex-wrap: wrap; justify-content: center; gap: var(--spacing-6); margin-top: var(--spacing-10); }
  .news-actions button, .text-action, .speak-placeholder {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-4);
    min-height: 2.75rem;
    padding: 0 var(--spacing-6);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-full);
    background: var(--color-grey-0);
    cursor: pointer;
    font-weight: 700;
  }

  .empty-state { padding: var(--spacing-20); border-radius: var(--radius-5); background: var(--color-grey-0); text-align: center; color: var(--color-font-secondary); }
  .release-summary, .article-body { box-sizing: border-box; width: min(100%, 43rem); margin: var(--spacing-16) auto 0; }
  .release-summary { padding: var(--spacing-12); border-radius: var(--radius-5); background: var(--color-grey-0); }
  .release-summary p { line-height: 1.7; }
  .release-summary .news-actions { justify-content: flex-start; }
  .speak-placeholder { padding: 0; border: 0; background: transparent; }

  .article-body { display: grid; gap: var(--spacing-10); padding: var(--spacing-12); border-radius: var(--radius-6); background: var(--color-grey-0); }
  .article-byline, .social-author { display: flex; align-items: center; gap: var(--spacing-6); }
  .article-byline > span:last-child { display: grid; gap: var(--spacing-1); }
  .article-byline small { color: var(--color-font-secondary); }
  .avatar { display: grid; place-items: center; width: 2.75rem; height: 2.75rem; border-radius: var(--radius-full); background: var(--color-primary); color: var(--color-font-button); font-size: var(--font-size-tiny); font-weight: 800; }
  .article-body p { margin: 0; line-height: 1.75; }
  .article-intro { font-size: 1.125rem; font-weight: 700; }
  .article-media-row { width: min(100%, 34rem); margin: 0 auto; }

  .slideshow { position: relative; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: var(--spacing-5); margin: var(--spacing-8) calc(-1 * var(--spacing-8)); }
  .slide-frame { position: relative; min-width: 0; }
  .slide-arrow { width: 2.75rem; height: 2.75rem; border: 0; border-radius: var(--radius-full); background: var(--color-grey-20); cursor: pointer; font-size: 1.5rem; }
  .slide-number { position: absolute; right: var(--spacing-4); bottom: var(--spacing-4); padding: var(--spacing-2) var(--spacing-4); border-radius: var(--radius-full); background: color-mix(in srgb, var(--color-grey-0) 88%, transparent); font-size: var(--font-size-tiny); }
  .slide-dots { grid-column: 1 / -1; display: flex; justify-content: center; gap: var(--spacing-3); }
  .slide-dots span { width: 0.5rem; height: 0.5rem; border-radius: var(--radius-full); background: var(--color-grey-40); }
  .slide-dots span.active { background: var(--color-primary-start); }

  .prompt-card { display: grid; gap: var(--spacing-6); padding: var(--spacing-10); border: 1px solid var(--color-grey-25); border-radius: var(--radius-5); background: var(--color-grey-10); box-shadow: var(--shadow-sm); }
  .prompt-card > span { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
  .prompt-card blockquote { margin: 0; line-height: 1.6; }
  .prompt-card button { justify-self: end; display: inline-flex; align-items: center; gap: var(--spacing-4); min-height: 2.5rem; padding: 0 var(--spacing-6); border: 0; background: transparent; cursor: pointer; }
  .contact-line { text-align: center; color: var(--color-primary-start); font-weight: 700; }
  .related-section { padding-top: var(--spacing-12); border-top: 1px solid var(--color-grey-30); }

  .social-detail { position: relative; box-sizing: border-box; width: min(100%, 58rem); min-height: 48rem; margin: 0 auto; padding: var(--spacing-16); border-radius: var(--radius-6); background: var(--color-grey-0); }
  .detail-actions { display: flex; justify-content: flex-end; }
  .detail-actions button { display: grid; place-items: center; width: 2.75rem; height: 2.75rem; border: 0; border-radius: var(--radius-full); background: var(--color-grey-20); cursor: pointer; }
  .social-detail-grid { display: grid; grid-template-columns: minmax(14rem, 0.85fr) minmax(16rem, 1.15fr); gap: var(--spacing-20); align-items: center; width: min(100%, 45rem); margin: var(--spacing-10) auto var(--spacing-24); }
  .social-detail-copy { display: grid; gap: var(--spacing-8); }
  .social-detail-copy h1 { margin: 0; font-size: var(--font-size-h2); line-height: 1.15; }
  .social-detail-copy p { margin: 0; line-height: 1.65; }
  .social-detail-copy time { color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .text-action { justify-self: start; }
  .social-detail hr { border: 0; border-top: 1px solid var(--color-grey-30); }

  @media (max-width: 68rem) {
    .surface-layout { grid-template-columns: 14rem minmax(0, 1fr); }
    .feature-hero { grid-template-columns: minmax(14rem, 0.9fr) minmax(16rem, 1.1fr); padding: var(--spacing-12); }
    .hero-copy h1 { font-size: 2rem; }
  }

  @media (max-width: 48rem) {
    .newsroom-shell { min-height: 100%; border: 0; border-radius: 0; box-shadow: none; }
    .topbar { padding: var(--spacing-6) var(--spacing-8); }
    .surface-layout { display: block; min-height: 0; }
    .publication-sidebar { display: none; }
    .mobile-publication-rail { display: flex; gap: var(--spacing-5); overflow-x: auto; padding: var(--spacing-6) var(--spacing-8); border-bottom: 1px solid var(--color-grey-25); background: var(--color-grey-10); scroll-snap-type: x mandatory; }
    .mobile-publication-rail button { flex: 0 0 12.5rem; display: grid; gap: var(--spacing-2); padding: var(--spacing-6); border: 1px solid var(--color-grey-25); border-radius: var(--radius-4); background: var(--color-grey-0); text-align: left; scroll-snap-align: start; }
    .mobile-publication-rail span { color: var(--color-font-secondary); font-size: var(--font-size-tiny); }
    .mobile-publication-rail strong { font-size: var(--font-size-small); line-height: 1.3; }
    main { padding: var(--spacing-6); }
    .feature-hero { grid-template-columns: 1fr; min-height: 0; padding: var(--spacing-10); gap: var(--spacing-10); }
    .hero-copy h1 { font-size: var(--font-size-h2-mobile); }
    .hero-media { order: -1; }
    .hero-close { top: 0; right: 0; }
    .content-section { margin-top: var(--spacing-16); }
    .section-header { align-items: flex-start; flex-wrap: wrap; }
    .section-header h2 { font-size: var(--font-size-h2-mobile); }
    .search-control.open { flex: 1 1 10rem; min-width: 0; }
    .search-control label { flex: 1; min-width: 0; }
    .search-control button span:last-child { display: none; }
    .search-control input { width: 100%; min-width: 0; }
    .content-grid, .content-grid.compact { grid-template-columns: 1fr; }
    .content-card.wide { grid-column: auto; grid-template-columns: 1fr; }
    .news-actions { justify-content: flex-start; overflow-x: auto; flex-wrap: nowrap; padding-bottom: var(--spacing-4); }
    .news-actions button { flex: 0 0 auto; }
    .article-body, .release-summary, .social-detail { padding: var(--spacing-8); }
    .slideshow { margin-inline: calc(-1 * var(--spacing-6)); gap: var(--spacing-2); }
    .slide-arrow { width: 2.25rem; height: 2.25rem; }
    .social-detail-grid { grid-template-columns: 1fr; gap: var(--spacing-10); }
    .social-detail-grid > .media-placeholder { width: min(100%, 18rem); margin: 0 auto; }
    .social-detail { min-height: 0; }
  }

  @media (prefers-reduced-motion: reduce) {
    .content-card { transition: none; }
    .content-card:hover { transform: none; }
  }
</style>
