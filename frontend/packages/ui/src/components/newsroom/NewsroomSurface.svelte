<script lang="ts">
  import { tick } from "svelte";
  import NewsroomMedia from "./NewsroomMedia.svelte";
  import PublicationHeader from "./PublicationHeader.svelte";
  import PublicationCard from "./PublicationCard.svelte";
  import PublicationHero from "./PublicationHero.svelte";
  import PublicationSidebar from "./PublicationSidebar.svelte";
  import SocialPostCard from "./SocialPostCard.svelte";
  import type {
    NewsroomAction,
    NewsroomArticleContent,
    NewsroomItem,
    NewsroomSurfaceData,
    NewsroomView,
  } from "./types";

  interface Props {
    view: NewsroomView;
    locale: "en" | "de";
    data: NewsroomSurfaceData;
    onAction: (action: NewsroomAction) => void;
  }

  let { view, locale, data, onAction }: Props = $props();

  let searchOpen = $state(false);
  let searchTerm = $state("");
  let searchInput = $state<HTMLInputElement>();
  let activeSlide = $state(0);
  let sidebarOpen = $state(false);
  let visiblePrimaryCount = $state(3);
  let visibleRelatedCount = $state(2);

  const isBlogSurface = $derived(view === "blog" || view === "blog-post");
  const isIndex = $derived(view === "news" || view === "blog");
  const sidebarItems = $derived(
    isBlogSurface ? data.blogItems : data.newsItems,
  );
  const pageLabel = $derived(isBlogSurface ? data.blogLabel : data.newsLabel);
  const hero = $derived(isBlogSurface ? data.heroBlog : data.heroNews);
  const selectedArticle = $derived(
    view === "blog-post" ? data.blogArticle : data.releaseArticle,
  );
  const latestLabel = $derived(
    isBlogSurface ? data.latestBlogLabel : data.latestNewsLabel,
  );

  const normalizedQuery = $derived(searchTerm.trim().toLocaleLowerCase(locale));
  const matchesSearch = (item: NewsroomItem) =>
    !normalizedQuery ||
    `${item.eyebrow} ${item.title} ${item.excerpt} ${item.bodyText ?? ""} ${item.author ?? ""}`
      .toLocaleLowerCase(locale)
      .includes(normalizedQuery);
  const filteredNewsItems = $derived(data.newsItems.filter(matchesSearch));
  const filteredBlogItems = $derived(data.blogItems.filter(matchesSearch));
  const filteredSocialItems = $derived(data.socialItems.filter(matchesSearch));
  const filteredCoverageItems = $derived(data.coverageItems.filter(matchesSearch));
  const filteredPrimaryItems = $derived.by(() =>
    isBlogSurface ? filteredBlogItems : filteredNewsItems,
  );
  const visiblePrimaryItems = $derived(
    filteredPrimaryItems.slice(0, visiblePrimaryCount),
  );
  const hasSearchResults = $derived(
    filteredNewsItems.length +
      filteredBlogItems.length +
      filteredSocialItems.length +
      filteredCoverageItems.length >
      0,
  );
  const relatedItems = $derived(
    view === "release" ? data.newsItems.slice(1) : data.blogItems.slice(1),
  );
  const visibleRelatedItems = $derived(
    relatedItems.slice(0, visibleRelatedCount),
  );

  async function showSearch() {
    searchOpen = true;
    sidebarOpen = false;
    await tick();
    searchInput?.focus();
  }

  async function toggleSearch() {
    if (searchOpen) {
      searchOpen = false;
      searchTerm = "";
      return;
    }
    await showSearch();
  }

  function showMorePrimary() {
    visiblePrimaryCount += 2;
  }

  function showMoreRelated() {
    visibleRelatedCount += 2;
  }

  function act(type: NewsroomAction["type"], itemId?: string) {
    onAction({ type, itemId });
  }

  function openItem(item: NewsroomItem) {
    act("open-item", item.id);
    if (window.matchMedia("(max-width: 730px)").matches) sidebarOpen = false;
  }

  function setSlide(next: number) {
    const count = selectedArticle.media?.length ?? 3;
    activeSlide = (next + count) % count;
  }
</script>

{#snippet sectionTitle(title: string)}
  <div class="section-heading"><h2>{title}</h2></div>
{/snippet}

{#snippet actionButton(
  icon: string,
  label: string,
  type: NewsroomAction["type"],
)}
  <button type="button" class="utility-action" onclick={() => act(type)}>
    <span class={`clickable-icon icon_${icon}`} aria-hidden="true"></span><span
      >{label}</span
    >
  </button>
{/snippet}

{#snippet socialRail(items: NewsroomItem[] = data.socialItems)}
  <div class="social-rail" data-testid="newsroom-social-rail">
    {#each items as item (item.id)}<SocialPostCard
        {item}
        onOpen={openItem}
      />{/each}
  </div>
{/snippet}

{#snippet articleBody(article: NewsroomArticleContent, isRelease: boolean)}
  <article class="article-body">
    <header class="article-byline">
      <img class="avatar" src="/favicon.svg" alt="" aria-hidden="true" />
      <span>
        <strong>{article.byline.split("\n")[0]}</strong>
        {#if article.byline.split("\n")[1]}
          <span class="author-role">{article.byline.split("\n")[1]}</span>
        {/if}
        <small>{article.publishedLabel}</small>
      </span>
    </header>
    <p class="article-intro">{article.intro}</p>
    {#if article.bodyHtml}
      <!-- Trusted server-rendered Markdown with raw HTML disabled. -->
      <!-- eslint-disable-next-line svelte/no-at-html-tags -->
      <div class="article-markdown">{@html article.bodyHtml}</div>
    {:else if article.paragraphs}
      <p>{article.paragraphs[0]}</p>
    {/if}
    {#if article.media?.length || article.paragraphs}
      <div class="slideshow" data-testid="newsroom-slideshow">
      <button
        type="button"
        aria-label={data.previousMediaLabel}
        onclick={() => setSlide(activeSlide - 1)}>‹</button
      >
      <div class="slide-frame">
        <NewsroomMedia
          label={`${data.articleMediaLabel}, ${activeSlide + 1}`}
          source={article.media?.[activeSlide]}
          controls={article.media?.[activeSlide]?.type === "video"}
        />
        <span>{activeSlide + 1} / {article.media?.length ?? 3}</span>
      </div>
      <button
        type="button"
        aria-label={data.nextMediaLabel}
        onclick={() => setSlide(activeSlide + 1)}>›</button
      >
      </div>
    {/if}
    {#if !article.bodyHtml && article.paragraphs}
      <p>{article.paragraphs[1]}</p>
        <NewsroomMedia label={data.articleMediaLabel} />
      <p>{article.paragraphs[2]}</p>
    {/if}
    {#if article.promptTitle && article.promptBody}
      <aside class="prompt-card">
        <small>{article.promptTitle}</small>
        <blockquote>{article.promptBody}</blockquote>
        <button type="button">{data.copyLabel}</button>
      </aside>
    {/if}
    <p class="contact-line">
      {isRelease ? data.releaseContactLabel : data.blogContactLabel}
    </p>
  </article>
{/snippet}

<div
  class:sidebar-open={sidebarOpen}
  class="newsroom-shell"
  data-testid="newsroom-surface"
  data-view={view}
  data-locale={locale}
>
  <div class="sidebar-layer" class:open={sidebarOpen}>
    <PublicationSidebar
      label={pageLabel}
      {latestLabel}
      items={sidebarItems}
      onOpen={openItem}
      onClose={() => (sidebarOpen = false)}
    />
  </div>

  <div class="main-panel">
    <PublicationHeader
      label={pageLabel}
      primaryCtaLabel={view === "release" ? data.tryItLabel : data.openAppLabel}
      onPrimaryCta={() => act(view === "release" ? "try-feature" : "open-app")}
      onToggleSidebar={() => (sidebarOpen = !sidebarOpen)}
      {sidebarOpen}
    />

    <div class="publication-scroll">
      {#if view === "social-post"}
        <main class="social-detail-page">
          <button
            type="button"
            class="detail-close"
            aria-label={data.closeSocialLabel}
            onclick={() => act("open-item")}
          >
            <span class="clickable-icon icon_close" aria-hidden="true"></span>
          </button>
          <section
            class="social-detail-grid"
            aria-labelledby="social-post-title"
          >
            <div class="social-detail-media">
              <NewsroomMedia
                label={data.articleMediaLabel}
                source={data.socialItems[0].media}
                shape="portrait"
                showPlay={false}
                controls={data.socialItems[0].media?.type === "video"}
              />
            </div>
            <div class="social-detail-copy">
              <div class="author-row">
                <img class="avatar" src="/favicon.svg" alt="" aria-hidden="true" /><strong
                  >OpenMates</strong
                >
              </div>
              <h1 id="social-post-title">{data.socialItems[0].title}</h1>
              <p>
                {data.socialItems[0].bodyText ?? data.socialItems[0].excerpt}
              </p>
              <time>{data.socialItems[0].publishedLabel}</time>
              <nav class="platform-links" aria-label={data.originalPostNavLabel}>
                {#each data.socialItems[0].socialLinks ?? [] as link (link.platform)}
                  <a
                    href={link.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={link.label}
                    data-testid={`social-platform-link-${link.platform}`}
                    class="platform-link"
                  >
                    <span
                      class:icon-bluesky={link.platform === "bluesky"}
                      class:icon-instagram={link.platform === "instagram"}
                      class:icon-mastodon={link.platform === "mastodon"}
                      class="platform-icon"
                      aria-hidden="true"
                    ></span>
                  </a>
                {/each}
              </nav>
            </div>
          </section>
          <section class="content-section more-posts">
            {@render sectionTitle(data.morePostsLabel)}
            {@render socialRail(data.socialItems.slice(1))}
          </section>
        </main>
      {:else}
        <main>
          <div class="hero-frame">
            <PublicationHero
              {hero}
              detail={!isIndex}
              onOpen={() =>
                act(
                  "open-item",
                  isBlogSurface ? data.blogItems[0].id : data.newsItems[0].id,
                )}
              onClose={() => act("open-item")}
            />
          </div>

          {#if isIndex}
            <div class="content-column">
              <section class="content-section">
                <div class="section-heading section-heading-with-actions">
                  <h2>{latestLabel}</h2>
                  <div class="section-actions">
                    <div class="search-control">
                      <button
                        data-testid="newsroom-search-toggle"
                        type="button"
                        aria-label={data.searchLabel}
                        aria-expanded={searchOpen}
                        onclick={toggleSearch}
                      >
                        <span
                          class={`clickable-icon icon_${searchOpen ? "close" : "search"}`}
                          aria-hidden="true"
                        ></span><span>{data.searchLabel}</span>
                      </button>
                    </div>
                    {#if !isBlogSurface}
                      {@render actionButton(
                        "download",
                        data.pressKitLabel,
                        "press-kit",
                      )}
                      {@render actionButton(
                        "mail",
                        data.pressInquiryLabel,
                        "press-inquiry",
                      )}
                    {/if}
                  </div>
                </div>
                {#if searchOpen}
                  <div class="search-field-row">
                    <input
                      data-testid="newsroom-search-input"
                      type="search"
                      placeholder={data.searchLabel}
                      aria-label={data.searchLabel}
                      bind:this={searchInput}
                      bind:value={searchTerm}
                    />
                  </div>
                {/if}

                {#if filteredPrimaryItems.length}
                  <div class="publication-grid">
                    {#each visiblePrimaryItems as item, index (item.id)}
                      <PublicationCard
                        {item}
                        variant={index === 0 ? "featured" : "standard"}
                        onOpen={openItem}
                      />
                    {/each}
                  </div>
                {:else if !hasSearchResults}<p class="empty-state">{data.emptyStateLabel}</p>{/if}

                {#if filteredPrimaryItems.length > visiblePrimaryCount || !isBlogSurface}
                  <div class="center-actions">
                    {#if filteredPrimaryItems.length > visiblePrimaryCount}
                      <button type="button" class="utility-action" onclick={showMorePrimary}>
                        <span class="clickable-icon icon_grid" aria-hidden="true"></span>
                        <span>{data.showMoreLabel}</span>
                      </button>
                    {/if}
                    {#if !isBlogSurface}
                      {@render actionButton(
                        "announcement",
                        data.subscribeLabel,
                        "subscribe-news",
                      )}
                    {/if}
                  </div>
                {/if}
              </section>

              {#if filteredSocialItems.length}
                <section class="content-section">
                  {@render sectionTitle(data.socialLabel)}
                  {@render socialRail(filteredSocialItems)}
                  <div class="follow-row">
                    <span>{data.followLabel}:</span><strong>Instagram</strong
                    ><strong>Mastodon</strong><strong>LinkedIn</strong>
                  </div>
                </section>
              {/if}

              {#if isBlogSurface}
                {#if filteredNewsItems.length}
                  <section class="content-section">
                    {@render sectionTitle(data.latestNewsLabel)}
                    <div class="publication-grid compact-grid">
                      {#each filteredNewsItems.slice(0, 3) as item, index (item.id)}<PublicationCard
                          {item}
                          variant={index === 0 ? "featured" : "compact"}
                          onOpen={openItem}
                        />{/each}
                    </div>
                  </section>
                {/if}
              {:else}
                {#if filteredCoverageItems.length}
                  <section class="content-section">
                    {@render sectionTitle(data.coverageLabel)}
                    <div class="publication-grid compact-grid">
                      {#each filteredCoverageItems as item (item.id)}<PublicationCard
                          {item}
                          variant="compact"
                          onOpen={openItem}
                        />{/each}
                    </div>
                  </section>
                {/if}
                {#if filteredBlogItems.length}
                  <section class="content-section">
                    {@render sectionTitle(data.latestBlogLabel)}
                    <div class="publication-grid compact-grid">
                      {#each filteredBlogItems.slice(0, 2) as item (item.id)}<PublicationCard
                          {item}
                          variant="compact"
                          onOpen={openItem}
                        />{/each}
                    </div>
                  </section>
                {/if}
              {/if}
            </div>
          {:else}
            <div class="detail-column">
              {#if view === "release"}
                <section class="release-summary">
                  <p>{selectedArticle.intro}</p>
                  <div class="summary-actions">
                    {@render actionButton(
                      "download",
                      data.pressKitLabel,
                      "press-kit",
                    )}{@render actionButton(
                      "announcement",
                      data.subscribeLabel,
                      "subscribe-news",
                    )}
                  </div>
                </section>
              {/if}
              {@render articleBody(selectedArticle, view === "release")}
              {#if relatedItems.length}
                <section class="content-section related-section">
                  {@render sectionTitle(
                    view === "release" ? data.latestNewsLabel : data.moreBlogPostsLabel,
                  )}
                  <div class="publication-grid compact-grid">
                    {#each visibleRelatedItems as item (item.id)}<PublicationCard
                        {item}
                        variant="compact"
                        onOpen={openItem}
                      />{/each}
                  </div>
                  {#if relatedItems.length > visibleRelatedCount}
                    <div class="center-actions">
                      <button type="button" class="utility-action" onclick={showMoreRelated}>
                        <span class="clickable-icon icon_grid" aria-hidden="true"></span>
                        <span>{data.showMoreLabel}</span>
                      </button>
                    </div>
                  {/if}
                </section>
              {/if}
            </div>
          {/if}
        </main>
      {/if}
    </div>
  </div>
</div>

<style>
  .newsroom-shell {
    --publication-sidebar-width: 20.3125rem;
    --publication-shell-gap: 0.625rem;
    --publication-content-max-width: 44.5rem;
    --publication-hero-block-size: 21rem;
    --publication-featured-card-min-height: 14rem;
    --publication-card-body-min-height: 10rem;
    --publication-social-card-width: 15.5rem;
    --publication-social-card-ratio: 5 / 8;
    --publication-social-media-ratio: 5 / 8;
    box-sizing: border-box;
    display: grid;
    width: 100%;
    height: 100dvh;
    min-height: 0;
    grid-template-columns: var(--publication-sidebar-width) minmax(0, 1fr);
    gap: var(--publication-shell-gap);
    overflow: hidden;
    background: var(--color-grey-20);
    color: var(--color-font-primary);
    transition: grid-template-columns var(--duration-normal) var(--easing-default);
  }
  .newsroom-shell:not(.sidebar-open) {
    grid-template-columns: 0 minmax(0, 1fr);
    gap: 0;
  }

  /* Full-page fixtures fill the capture canvas; no negative margins or second
     outer scrolling viewport, which displaced the header on mobile Safari. */
  :global(.preview-page.capture-mode .preview-layout .preview-container:has(.newsroom-shell)) {
    padding: 0;
    align-items: flex-start;
  }
  :global(.capture-mode .preview-viewport:has(.newsroom-shell)),
  :global(.capture-mode .component-mount:has(.newsroom-shell)) {
    align-items: flex-start;
  }

  .sidebar-layer {
    min-width: 0;
    height: 100dvh;
    position: sticky;
    top: 0;
    visibility: hidden;
    transform: translateX(-100%);
    transition:
      visibility var(--duration-normal) var(--easing-default),
      transform var(--duration-normal) var(--easing-default);
  }
  .sidebar-layer.open {
    visibility: visible;
    transform: translateX(0);
  }
  .main-panel {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr);
    height: 100%;
    min-height: 0;
    min-width: 0;
    overflow: hidden;
    border-radius: var(--radius-5) 0 0 var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-sm);
  }
  .publication-scroll {
    min-height: 0;
    overflow: auto;
    background: var(--color-grey-20);
  }
  main {
    box-sizing: border-box;
    min-height: 100%;
    padding-bottom: var(--spacing-20);
  }
  .hero-frame {
    padding: 0 var(--spacing-5);
    background: var(--color-grey-0);
  }
  .content-column,
  .detail-column {
    box-sizing: border-box;
    width: min(
      calc(100% - 2 * var(--spacing-10)),
      var(--publication-content-max-width)
    );
    margin: 0 auto;
  }
  .content-section {
    margin-top: var(--spacing-24);
  }
  .section-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--spacing-12);
  }
  .section-heading h2 {
    margin: 0;
    font-size: var(--font-size-h2-mobile);
    line-height: 1.25;
  }
  .section-heading-with-actions {
    gap: var(--spacing-8);
  }
  .section-actions {
    display: flex;
    align-items: center;
    gap: var(--spacing-8);
  }

  .utility-action,
  .search-control button {
    all: unset;
    display: inline-flex;
    min-height: 2.5rem;
    align-items: center;
    gap: var(--spacing-3);
    cursor: pointer;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
    font-weight: 700;
    white-space: nowrap;
  }
  .utility-action :global(.clickable-icon),
  .search-control :global(.clickable-icon) {
    width: 1.25rem;
    height: 1.25rem;
    background-color: currentColor;
  }
  .search-control {
    display: flex;
    align-items: center;
  }
  .search-field-row {
    display: flex;
    justify-content: flex-end;
    margin: calc(-1 * var(--spacing-6)) 0 var(--spacing-12);
  }
  .search-field-row input {
    box-sizing: border-box;
    width: min(100%, 24rem);
    min-height: 2.5rem;
    padding: 0 var(--spacing-5);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-full);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    font: inherit;
  }
  .search-field-row input:focus-visible {
    outline: 0.125rem solid var(--color-primary-start);
    outline-offset: 0.125rem;
  }
  .publication-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--spacing-16);
  }
  .compact-grid {
    align-items: start;
  }
  .center-actions {
    display: flex;
    justify-content: center;
    gap: var(--spacing-10);
    margin-top: var(--spacing-10);
  }
  .empty-state {
    padding: var(--spacing-16);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    text-align: center;
  }
  .social-rail {
    display: flex;
    gap: var(--spacing-8);
    overflow-x: auto;
    padding: var(--spacing-2) var(--spacing-2) var(--spacing-8);
    scroll-snap-type: x proximity;
  }
  .follow-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-8);
    padding: var(--spacing-8);
    color: var(--color-font-secondary);
    font-size: var(--font-size-tiny);
  }

  .release-summary,
  .article-body {
    box-sizing: border-box;
    width: min(100%, 44rem);
    margin: var(--spacing-16) auto 0;
  }
  .release-summary {
    display: grid;
    gap: var(--spacing-6);
    padding: 0;
  }
  .release-summary p {
    width: min(100%, 34rem);
    margin: 0 auto;
    line-height: 1.65;
  }
  .summary-actions {
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: var(--spacing-8);
  }
  .article-body {
    display: grid;
    gap: var(--spacing-10);
    padding: 0;
    user-select: text;
    -webkit-user-select: text;
    -moz-user-select: text;
    -ms-user-select: text;
  }
  .article-body :global(*) {
    user-select: text;
    -webkit-user-select: text;
    -moz-user-select: text;
    -ms-user-select: text;
  }
  .article-body p {
    margin: 0;
    line-height: 1.75;
  }
  .article-markdown {
    display: grid;
    gap: var(--spacing-8);
    min-width: 0;
  }
  .article-markdown :global(h1),
  .article-markdown :global(h2),
  .article-markdown :global(h3) {
    margin: var(--spacing-6) 0 0;
    line-height: 1.25;
  }
  .article-markdown :global(p),
  .article-markdown :global(ul),
  .article-markdown :global(ol) {
    margin: 0;
    line-height: 1.75;
  }
  .article-markdown :global(.publication-media-group) {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(15rem, 100%), 1fr));
    gap: var(--spacing-5);
    margin: var(--spacing-5) 0;
  }
  .article-markdown :global(.publication-media-group img),
  .article-markdown :global(.publication-media-group video) {
    display: block;
    width: 100%;
    height: 100%;
    max-height: 32rem;
    object-fit: cover;
    border-radius: var(--radius-4);
  }
  .article-intro {
    font-size: 1.15rem;
    font-weight: 700;
  }
  .article-byline,
  .author-row {
    display: flex;
    align-items: center;
    gap: var(--spacing-5);
  }
  .article-byline > span:last-child {
    display: grid;
    gap: var(--spacing-1);
  }
  .article-byline small {
    color: var(--color-font-secondary);
  }
  .author-role {
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }
  .avatar {
    width: 2.75rem;
    height: 2.75rem;
    flex: 0 0 2.75rem;
    object-fit: cover;
    aspect-ratio: 1;
    border-radius: 50%;
  }
  .slideshow {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--spacing-5);
  }
  .slideshow > button {
    all: unset;
    display: grid;
    width: 2.5rem;
    aspect-ratio: 1;
    place-items: center;
    border-radius: 50%;
    background: var(--color-grey-20);
    cursor: pointer;
    font-size: 1.5rem;
  }
  .slide-frame {
    position: relative;
    min-width: 0;
  }
  .slide-frame > span {
    position: absolute;
    right: var(--spacing-4);
    bottom: var(--spacing-4);
    padding: var(--spacing-2) var(--spacing-4);
    border-radius: var(--radius-full);
    background: rgba(255, 255, 255, 0.9);
    font-size: var(--font-size-tiny);
  }
  .prompt-card {
    display: grid;
    gap: var(--spacing-5);
    padding: var(--spacing-8);
    border-radius: var(--radius-4);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-sm);
  }
  .prompt-card blockquote {
    margin: 0;
    line-height: 1.55;
  }
  .prompt-card button {
    justify-self: end;
  }
  .contact-line {
    color: var(--color-primary-start);
    font-weight: 700;
    text-align: center;
  }
  .related-section {
    padding-top: var(--spacing-12);
    border-top: 1px solid var(--color-grey-30);
  }

  .social-detail-page {
    position: relative;
    box-sizing: border-box;
    width: calc(100% - var(--spacing-10));
    margin: 0 auto;
    padding: var(--spacing-16) var(--spacing-12);
    border-radius: var(--radius-8);
    background: var(--color-grey-20);
  }
  .detail-close {
    all: unset;
    position: absolute;
    top: var(--spacing-8);
    right: var(--spacing-8);
    z-index: 2;
    display: grid;
    width: 2.75rem;
    aspect-ratio: 1;
    place-items: center;
    border-radius: 50%;
    background: var(--color-grey-0);
    box-shadow: var(--shadow-md);
    cursor: pointer;
  }
  .detail-close :global(.clickable-icon) {
    width: 1.5rem;
    height: 1.5rem;
    background-color: var(--color-primary-start);
  }
  .social-detail-grid {
    display: grid;
    width: min(100%, var(--publication-content-max-width));
    grid-template-columns: 18.75rem minmax(0, 1fr);
    align-items: center;
    gap: var(--spacing-16);
    margin: 0 auto var(--spacing-32);
  }
  .social-detail-media {
    width: 100%;
  }
  .social-detail-media :global(.newsroom-media) {
    border-radius: var(--radius-8);
    box-shadow: var(--shadow-md);
  }
  .social-detail-copy {
    display: grid;
    gap: var(--spacing-8);
    user-select: text;
    -webkit-user-select: text;
  }
  .social-detail-copy h1 {
    margin: 0;
    font-size: var(--font-size-p);
    line-height: 1.4;
  }
  .social-detail-copy p {
    margin: 0;
    line-height: 1.65;
  }
  .social-detail-copy time {
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }
  .platform-links {
    display: flex;
    align-items: center;
    gap: var(--spacing-6);
  }
  .platform-link {
    display: grid;
    width: 2rem;
    aspect-ratio: 1;
    place-items: center;
    border-radius: var(--radius-full);
    color: var(--color-font-secondary);
    transition:
      color var(--duration-fast) var(--easing-default),
      background-color var(--duration-fast) var(--easing-default);
  }
  .platform-link:hover,
  .platform-link:focus-visible {
    background: var(--color-grey-25);
    color: var(--color-primary-start);
  }
  .platform-link:focus-visible {
    outline: 0.125rem solid var(--color-button-primary);
    outline-offset: 0.125rem;
  }
  .platform-icon {
    width: 1.25rem;
    height: 1.25rem;
    background-color: currentColor;
    mask-position: center;
    mask-repeat: no-repeat;
    mask-size: contain;
  }
  .platform-icon.icon-bluesky {
    mask-image: var(--icon-url-bluesky);
  }
  .platform-icon.icon-instagram {
    mask-image: var(--icon-url-instagram);
  }
  .platform-icon.icon-mastodon {
    mask-image: var(--icon-url-mastodon);
  }
  .more-posts {
    width: min(100%, var(--publication-content-max-width));
    margin-inline: auto;
    padding-top: var(--spacing-16);
    border-top: 1px solid var(--color-grey-30);
  }

  @media (max-width: 1000px) {
    .newsroom-shell {
      --publication-sidebar-width: 16rem;
    }
    .section-heading-with-actions {
      align-items: flex-start;
      flex-direction: column;
    }
    .section-actions {
      width: 100%;
      overflow-x: auto;
    }
  }

  @media (max-width: 730px) {
    .newsroom-shell {
      display: block;
      min-height: 100dvh;
    }
    .sidebar-layer {
      position: fixed;
      inset: 4rem 0 0;
      z-index: 1;
      width: 100%;
      height: calc(100dvh - 4rem);
      visibility: hidden;
      transform: translateX(-100%);
      transition: transform var(--duration-normal) var(--easing-default);
    }
    .sidebar-layer.open {
      visibility: visible;
      transform: translateX(0);
    }
    :global([dir="rtl"]) .sidebar-layer {
      transform: translateX(100%);
    }
    :global([dir="rtl"]) .sidebar-layer.open {
      transform: translateX(0);
    }
    .main-panel {
      position: relative;
      z-index: 0;
      min-height: 0;
      border-radius: 0;
    }
    .main-panel :global(header.publication) {
      z-index: 2;
    }
    .publication-scroll {
      min-height: 0;
    }
    .hero-frame {
      padding: 0 var(--spacing-8);
    }
    .content-column,
    .detail-column {
      width: min(
        calc(100% - 2 * var(--spacing-12)),
        var(--publication-content-max-width)
      );
    }
    .content-section {
      margin-top: var(--spacing-20);
    }
    .section-heading h2 {
      font-size: var(--font-size-h2-mobile);
    }
    .section-actions {
      gap: var(--spacing-6);
    }
    .section-actions .utility-action span:last-child,
    .search-control button span:last-child {
      display: none;
    }
    .search-field-row {
      justify-content: stretch;
      margin-top: calc(-1 * var(--spacing-5));
    }
    .search-field-row input {
      width: 100%;
    }
    .publication-grid {
      grid-template-columns: 1fr;
      gap: var(--spacing-12);
    }
    .social-rail {
      margin-inline: calc(-1 * var(--spacing-6));
      padding-inline: var(--spacing-6);
    }
    .follow-row {
      flex-wrap: wrap;
    }
    .slideshow {
      gap: var(--spacing-2);
    }
    .slideshow > button {
      width: 2.125rem;
    }
    .social-detail-page {
      width: 100%;
      padding: var(--spacing-32) var(--spacing-12) var(--spacing-12);
    }
    .social-detail-grid {
      grid-template-columns: 1fr;
      gap: var(--spacing-10);
    }
    .social-detail-media {
      width: min(100%, 18rem);
      margin: 0 auto;
    }
    .social-detail-copy h1 {
      font-size: var(--font-size-p);
    }
  }
</style>
