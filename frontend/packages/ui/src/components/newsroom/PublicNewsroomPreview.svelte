<script lang="ts">
  import PublicSiteHeader from '@repo/public-site/components/landing/PublicSiteHeader.svelte';
  import NewsroomSurface from '@repo/public-site/components/newsroom/NewsroomSurface.svelte';
  import { newsroomFixtures } from '@repo/public-site/components/newsroom/fixtures';
  import type { NewsroomAction, NewsroomView, NewsroomSurfaceData } from '@repo/public-site/components/newsroom/types';

  interface Props {
    view?: NewsroomView;
    data?: NewsroomSurfaceData;
    locale?: 'en' | 'de';
    appBaseUrl?: string;
    websiteBaseUrl?: string;
  }

  let {
    view = 'news',
    data,
    locale = 'en',
    appBaseUrl = 'https://app.dev.openmates.org',
    websiteBaseUrl = 'https://landing.dev.openmates.org',
  }: Props = $props();

  let currentView = $state<NewsroomView>('news');
  let currentLocale = $state<'en' | 'de'>('en');
  $effect(() => { currentView = view; });
  $effect(() => { currentLocale = locale; });
  const currentData = $derived(data ?? newsroomFixtures[currentLocale]);
  const indexHref = $derived(
    `${websiteBaseUrl}${currentLocale === 'de' ? '/de' : ''}/${currentView === 'blog' || currentView === 'blog-post' ? 'blog' : 'news'}`,
  );

  function handleAction(action: NewsroomAction): void {
    if (action.type !== 'open-item') return;
    if (!action.itemId) {
      currentView = currentView === 'blog-post' ? 'blog' : 'news';
    } else if (currentData.blogItems.some((item) => item.id === action.itemId)) {
      currentView = 'blog-post';
    } else if (currentData.socialItems.some((item) => item.id === action.itemId)) {
      currentView = 'social-post';
    } else {
      currentView = 'release';
    }
  }
</script>

{#snippet publicHeader()}
  <PublicSiteHeader
    {appBaseUrl}
    {websiteBaseUrl}
    language={currentLocale}
    availableLanguages={['en', 'de']}
    publication={currentView === 'blog' || currentView === 'blog-post' ? 'blog' : 'news'}
    onLanguageChange={(code) => { currentLocale = code === 'de' ? 'de' : 'en'; }}
  />
{/snippet}

<div class="public-newsroom-preview">
  <NewsroomSurface
    view={currentView}
    locale={currentLocale}
    {indexHref}
    navigationKey={`${currentLocale}:${currentView}`}
    data={currentData}
    onAction={handleAction}
    {publicHeader}
  />
</div>

<style>
  .public-newsroom-preview { width: 100%; height: 100dvh; }
</style>
