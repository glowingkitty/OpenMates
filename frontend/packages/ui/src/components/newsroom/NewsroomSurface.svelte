<script lang="ts">
  import { onMount } from "svelte";
  import Header from "../Header.svelte";
  import NewsroomMedia from "./NewsroomMedia.svelte";
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
  let activeSlide = $state(0);
  let sidebarOpen = $state(true);

  const isBlogSurface = $derived(view === "blog" || view === "blog-post");
  const isIndex = $derived(view === "news" || view === "blog");
  const sidebarItems = $derived(
    isBlogSurface ? data.blogItems : data.newsItems,
  );
  const pageLabel = $derived(isBlogSurface ? data.blogLabel : data.newsLabel);
  const hero = $derived(isBlogSurface ? data.heroBlog : data.heroNews);
  const primaryItems = $derived(
    isBlogSurface ? data.blogItems : data.newsItems,
  );
  const selectedArticle = $derived(
    view === "blog-post" ? data.blogArticle : data.releaseArticle,
  );
  const latestLabel = $derived(
    isBlogSurface ? data.latestBlogLabel : data.latestNewsLabel,
  );

  const filteredPrimaryItems = $derived.by(() => {
    const query = searchTerm.trim().toLocaleLowerCase(locale);
    if (!query) return primaryItems;
    return primaryItems.filter((item) =>
      `${item.eyebrow} ${item.title} ${item.excerpt}`
        .toLocaleLowerCase(locale)
        .includes(query),
    );
  });

  onMount(() => {
    sidebarOpen = window.matchMedia("(min-width: 731px)").matches;
  });

  function act(type: NewsroomAction["type"], itemId?: string) {
    onAction({ type, itemId });
  }

  function openItem(item: NewsroomItem) {
    act(item.kind === "coverage" ? "open-social" : "open-item", item.id);
    if (window.matchMedia("(max-width: 730px)").matches) sidebarOpen = false;
  }

  function setSlide(next: number) {
    activeSlide = (next + 3) % 3;
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
      <span class="avatar" aria-hidden="true">OM</span>
      <span
        ><strong>{article.byline}</strong><small>{article.publishedLabel}</small
        ></span
      >
    </header>
    <p class="article-intro">{article.intro}</p>
    <p>{article.paragraphs[0]}</p>
    <div class="slideshow" data-testid="newsroom-slideshow">
      <button
        type="button"
        aria-label="Previous media"
        onclick={() => setSlide(activeSlide - 1)}>‹</button
      >
      <div class="slide-frame">
        <NewsroomMedia label={`Article media, slide ${activeSlide + 1}`} />
        <span>{activeSlide + 1} / 3</span>
      </div>
      <button
        type="button"
        aria-label="Next media"
        onclick={() => setSlide(activeSlide + 1)}>›</button
      >
    </div>
    <p>{article.paragraphs[1]}</p>
    <NewsroomMedia label="Article example media" />
    <p>{article.paragraphs[2]}</p>
    <aside class="prompt-card">
      <small>{article.promptTitle}</small>
      <blockquote>{article.promptBody}</blockquote>
      <button type="button">Copy</button>
    </aside>
    <p class="contact-line">
      {isRelease
        ? "For further questions, contact press@openmates.org"
        : "Questions or feedback? marco@openmates.org"}
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
    <Header
      context="webapp"
      isLoggedIn={false}
      publicationLabel={pageLabel}
      primaryCtaLabel={view === "release" ? data.tryItLabel : data.openAppLabel}
      onPrimaryCta={() => act(view === "release" ? "try-feature" : "open-app")}
      onToggleSidebar={() => (sidebarOpen = !sidebarOpen)}
      isSidebarOpen={sidebarOpen}
    />

    <div class="publication-scroll">
      {#if view === "social-post"}
        <main class="social-detail-page">
          <button
            type="button"
            class="detail-close"
            aria-label="Close social post"
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
                label="OpenMates social post media"
                shape="portrait"
                showPlay={false}
              />
            </div>
            <div class="social-detail-copy">
              <div class="author-row">
                <span class="avatar" aria-hidden="true">OM</span><strong
                  >OpenMates</strong
                >
              </div>
              <h1 id="social-post-title">{data.socialItems[0].title}</h1>
              <p>
                {data.socialItems[0].excerpt} This archived copy remains readable
                and searchable without loading media from a social platform.
              </p>
              <time>{data.socialItems[0].publishedLabel}</time>
              <button
                type="button"
                class="original-link"
                onclick={() => act("open-social", data.socialItems[0].id)}
                >{data.viewOriginalLabel} ↗</button
              >
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
                  isBlogSurface ? data.blogItems[0].id : "workflow-automation",
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
                    <div class:open={searchOpen} class="search-control">
                      {#if searchOpen}<input
                          data-testid="newsroom-search-input"
                          type="search"
                          placeholder={data.searchLabel}
                          bind:value={searchTerm}
                        />{/if}
                      <button
                        data-testid="newsroom-search-toggle"
                        type="button"
                        aria-label={data.searchLabel}
                        aria-expanded={searchOpen}
                        onclick={() => (searchOpen = !searchOpen)}
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

                {#if filteredPrimaryItems.length}
                  <div class="publication-grid">
                    {#each filteredPrimaryItems as item, index (item.id)}
                      <PublicationCard
                        {item}
                        variant={index === 0 ? "featured" : "standard"}
                        onOpen={openItem}
                      />
                    {/each}
                  </div>
                {:else}<p class="empty-state">No matching posts.</p>{/if}

                {#if !isBlogSurface}
                  <div class="center-actions">
                    {@render actionButton("grid", "Show all", "open-item")}
                    {@render actionButton(
                      "announcement",
                      data.subscribeLabel,
                      "subscribe-news",
                    )}
                  </div>
                {/if}
              </section>

              <section class="content-section">
                {@render sectionTitle(data.socialLabel)}
                {@render socialRail()}
                <div class="follow-row">
                  <span>{data.followLabel}:</span><strong>Instagram</strong
                  ><strong>Mastodon</strong><strong>LinkedIn</strong>
                </div>
              </section>

              {#if isBlogSurface}
                <section class="content-section">
                  {@render sectionTitle(data.latestNewsLabel)}
                  <div class="publication-grid compact-grid">
                    {#each data.newsItems.slice(0, 3) as item, index (item.id)}<PublicationCard
                        {item}
                        variant={index === 0 ? "featured" : "compact"}
                        onOpen={openItem}
                      />{/each}
                  </div>
                </section>
              {:else}
                <section class="content-section">
                  {@render sectionTitle(data.coverageLabel)}
                  <div class="publication-grid compact-grid">
                    {#each data.coverageItems as item (item.id)}<PublicationCard
                        {item}
                        variant="compact"
                        onOpen={openItem}
                      />{/each}
                  </div>
                </section>
                <section class="content-section">
                  {@render sectionTitle(data.latestBlogLabel)}
                  <div class="publication-grid compact-grid">
                    {#each data.blogItems.slice(0, 2) as item (item.id)}<PublicationCard
                        {item}
                        variant="compact"
                        onOpen={openItem}
                      />{/each}
                  </div>
                </section>
              {/if}
            </div>
          {:else}
            <div class="detail-column">
              {#if view === "release"}
                <section class="release-summary">
                  <button type="button">▶ Speak announcement</button>
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
              <section class="content-section related-section">
                {@render sectionTitle(
                  view === "release" ? data.latestNewsLabel : data.relatedLabel,
                )}
                <div class="publication-grid compact-grid">
                  {#each view === "release" ? data.newsItems.slice(1, 3) : data.blogItems.slice(1, 3) as item (item.id)}<PublicationCard
                      {item}
                      variant="compact"
                      onOpen={openItem}
                    />{/each}
                </div>
              </section>
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
    --publication-social-card-width: 15rem;
    --publication-social-card-ratio: 3 / 4.7;
    box-sizing: border-box;
    display: grid;
    width: 100%;
    min-height: max(56rem, 100dvh);
    grid-template-columns: var(--publication-sidebar-width) minmax(0, 1fr);
    gap: var(--publication-shell-gap);
    overflow: hidden;
    background: var(--color-grey-20);
    color: var(--color-font-primary);
  }

  .sidebar-layer {
    min-width: 0;
    height: 100dvh;
    position: sticky;
    top: 0;
  }
  .main-panel {
    min-width: 0;
    overflow: hidden;
    border-radius: var(--radius-5) 0 0 var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-sm);
  }
  .publication-scroll {
    height: calc(100dvh - 4.35rem);
    overflow: auto;
    background: var(--color-grey-10);
  }
  main {
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
    margin-top: var(--spacing-20);
  }
  .section-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--spacing-8);
  }
  .section-heading h2 {
    margin: 0;
    font-size: var(--font-size-h2);
    line-height: 1.15;
  }
  .section-heading-with-actions {
    gap: var(--spacing-8);
  }
  .section-actions {
    display: flex;
    align-items: center;
    gap: var(--spacing-7);
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
  .search-control input {
    box-sizing: border-box;
    width: 12rem;
    min-height: 2.5rem;
    margin-right: var(--spacing-3);
    padding: 0 var(--spacing-5);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-full);
    background: var(--color-grey-0);
    font: inherit;
  }
  .publication-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--spacing-10);
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
    gap: var(--spacing-7);
    padding: var(--spacing-8);
    color: var(--color-font-secondary);
    font-size: var(--font-size-tiny);
  }

  .release-summary,
  .article-body {
    box-sizing: border-box;
    width: min(100%, 44rem);
    margin: var(--spacing-16) auto 0;
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-sm);
  }
  .release-summary {
    display: grid;
    gap: var(--spacing-6);
    padding: var(--spacing-10);
  }
  .release-summary > button {
    all: unset;
    cursor: pointer;
    font-weight: 700;
  }
  .release-summary p {
    margin: 0;
    line-height: 1.65;
  }
  .summary-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-8);
  }
  .article-body {
    display: grid;
    gap: var(--spacing-10);
    padding: var(--spacing-12);
  }
  .article-body p {
    margin: 0;
    line-height: 1.75;
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
  .avatar {
    display: grid;
    width: 2.75rem;
    aspect-ratio: 1;
    place-items: center;
    border-radius: 50%;
    background: var(--color-primary);
    color: #fff;
    font-size: var(--font-size-tiny);
    font-weight: 800;
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
    background: var(--color-grey-10);
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
    width: min(calc(100% - var(--spacing-10)), 72rem);
    margin: 0 auto;
    padding: var(--spacing-14) var(--spacing-12);
    background: var(--color-grey-10);
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
    width: min(100%, 52rem);
    grid-template-columns: minmax(15rem, 0.8fr) minmax(18rem, 1.2fr);
    align-items: center;
    gap: var(--spacing-16);
    margin: 0 auto var(--spacing-20);
  }
  .social-detail-media {
    width: min(100%, 19rem);
  }
  .social-detail-media :global(.newsroom-media) {
    box-shadow: var(--shadow-lg);
  }
  .social-detail-copy {
    display: grid;
    gap: var(--spacing-7);
  }
  .social-detail-copy h1 {
    margin: 0;
    font-size: var(--font-size-h2);
    line-height: 1.15;
  }
  .social-detail-copy p {
    margin: 0;
    line-height: 1.65;
  }
  .social-detail-copy time {
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }
  .original-link {
    all: unset;
    justify-self: start;
    cursor: pointer;
    color: var(--color-primary-start);
    font-weight: 700;
  }
  .more-posts {
    padding-top: var(--spacing-14);
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
      inset: 0;
      z-index: 10002;
      width: 100%;
      height: 100dvh;
      transform: translateX(-100%);
      transition: transform var(--duration-normal) var(--easing-default);
    }
    .sidebar-layer.open {
      transform: translateX(0);
    }
    :global([dir="rtl"]) .sidebar-layer {
      transform: translateX(100%);
    }
    :global([dir="rtl"]) .sidebar-layer.open {
      transform: translateX(0);
    }
    .main-panel {
      min-height: 100dvh;
      border-radius: 0;
    }
    .publication-scroll {
      height: calc(100dvh - 4.35rem);
    }
    .hero-frame {
      padding: 0;
    }
    .content-column,
    .detail-column {
      width: min(
        calc(100% - 2 * var(--spacing-6)),
        var(--publication-content-max-width)
      );
    }
    .content-section {
      margin-top: var(--spacing-14);
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
    .search-control input {
      width: min(56vw, 13rem);
    }
    .publication-grid {
      grid-template-columns: 1fr;
      gap: var(--spacing-8);
    }
    .social-rail {
      margin-inline: calc(-1 * var(--spacing-6));
      padding-inline: var(--spacing-6);
    }
    .follow-row {
      flex-wrap: wrap;
    }
    .article-body,
    .release-summary {
      padding: var(--spacing-8);
    }
    .slideshow {
      gap: var(--spacing-2);
    }
    .slideshow > button {
      width: 2.125rem;
    }
    .social-detail-page {
      width: 100%;
      padding: var(--spacing-12) var(--spacing-6);
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
      font-size: var(--font-size-h2-mobile);
    }
  }
</style>
