import { describe, expect, it, vi } from 'vitest';
import type { Component } from 'svelte';

// Selection contract only: stable mocked module identities isolate routing from
// auth and DOM runtime. The all-kind component browser matrix proves rendering.
const renderers = vi.hoisted(() => ({
  components: new Map<string, Component>(),
  fullscreenShell: vi.fn(),
  previewShell: () => {},
  get(path: string): Component {
    if (!this.components.has(path)) this.components.set(path, () => {});
    return this.components.get(path)!;
  },
}));
vi.mock('../../components/embeds/ResolvedEmbedPreview.svelte', () => ({ default: renderers.previewShell }));
vi.mock('../../components/embeds/ResolvedEmbedFullscreen.svelte', () => ({ default: renderers.fullscreenShell }));
vi.mock('../../components/embeds/business/BusinessCompanyFinancialResultEmbedFullscreen.svelte', () => ({ default: renderers.get('business/BusinessCompanyFinancialResultEmbedFullscreen') }));
vi.mock('../../components/embeds/business/BusinessCompanyFinancialResultEmbedPreview.svelte', () => ({ default: renderers.get('business/BusinessCompanyFinancialResultEmbedPreview') }));
vi.mock('../../components/embeds/business/BusinessCompanyFinancialsEmbedFullscreen.svelte', () => ({ default: renderers.get('business/BusinessCompanyFinancialsEmbedFullscreen') }));
vi.mock('../../components/embeds/code/CodeRepoEmbedFullscreen.svelte', () => ({ default: renderers.get('code/CodeRepoEmbedFullscreen') }));
vi.mock('../../components/embeds/code/CodeRepoEmbedPreview.svelte', () => ({ default: renderers.get('code/CodeRepoEmbedPreview') }));
vi.mock('../../components/embeds/design/DesignIconResultEmbedFullscreen.svelte', () => ({ default: renderers.get('design/DesignIconResultEmbedFullscreen') }));
vi.mock('../../components/embeds/design/DesignIconResultEmbedPreview.svelte', () => ({ default: renderers.get('design/DesignIconResultEmbedPreview') }));
vi.mock('../../components/embeds/electronics/ElectronicsComponentEmbedFullscreen.svelte', () => ({ default: renderers.get('electronics/ElectronicsComponentEmbedFullscreen') }));
vi.mock('../../components/embeds/electronics/ElectronicsComponentEmbedPreview.svelte', () => ({ default: renderers.get('electronics/ElectronicsComponentEmbedPreview') }));
vi.mock('../../components/embeds/events/EventEmbedFullscreen.svelte', () => ({ default: renderers.get('events/EventEmbedFullscreen') }));
vi.mock('../../components/embeds/events/EventEmbedPreview.svelte', () => ({ default: renderers.get('events/EventEmbedPreview') }));
vi.mock('../../components/embeds/fitness/FitnessResultEmbedFullscreen.svelte', () => ({ default: renderers.get('fitness/FitnessResultEmbedFullscreen') }));
vi.mock('../../components/embeds/fitness/FitnessResultEmbedPreview.svelte', () => ({ default: renderers.get('fitness/FitnessResultEmbedPreview') }));
vi.mock('../../components/embeds/health/HealthAppointmentEmbedFullscreen.svelte', () => ({ default: renderers.get('health/HealthAppointmentEmbedFullscreen') }));
vi.mock('../../components/embeds/health/HealthAppointmentEmbedPreview.svelte', () => ({ default: renderers.get('health/HealthAppointmentEmbedPreview') }));
vi.mock('../../components/embeds/home/HomeListingEmbedFullscreen.svelte', () => ({ default: renderers.get('home/HomeListingEmbedFullscreen') }));
vi.mock('../../components/embeds/home/HomeListingEmbedPreview.svelte', () => ({ default: renderers.get('home/HomeListingEmbedPreview') }));
vi.mock('../../components/embeds/hosting/HostingDomainEmbedFullscreen.svelte', () => ({ default: renderers.get('hosting/HostingDomainEmbedFullscreen') }));
vi.mock('../../components/embeds/hosting/HostingDomainEmbedPreview.svelte', () => ({ default: renderers.get('hosting/HostingDomainEmbedPreview') }));
vi.mock('../../components/embeds/images/ImageResultEmbedFullscreen.svelte', () => ({ default: renderers.get('images/ImageResultEmbedFullscreen') }));
vi.mock('../../components/embeds/images/ImageResultEmbedPreview.svelte', () => ({ default: renderers.get('images/ImageResultEmbedPreview') }));
vi.mock('../../components/embeds/jobs/JobsResultEmbedFullscreen.svelte', () => ({ default: renderers.get('jobs/JobsResultEmbedFullscreen') }));
vi.mock('../../components/embeds/jobs/JobsResultEmbedPreview.svelte', () => ({ default: renderers.get('jobs/JobsResultEmbedPreview') }));
vi.mock('../../components/embeds/maps/MapLocationEmbedFullscreen.svelte', () => ({ default: renderers.get('maps/MapLocationEmbedFullscreen') }));
vi.mock('../../components/embeds/maps/MapLocationEmbedPreview.svelte', () => ({ default: renderers.get('maps/MapLocationEmbedPreview') }));
vi.mock('../../components/embeds/models3d/Model3DResultEmbedFullscreen.svelte', () => ({ default: renderers.get('models3d/Model3DResultEmbedFullscreen') }));
vi.mock('../../components/embeds/models3d/Model3DResultEmbedPreview.svelte', () => ({ default: renderers.get('models3d/Model3DResultEmbedPreview') }));
vi.mock('../../components/embeds/news/NewsArticleEmbedFullscreen.svelte', () => ({ default: renderers.get('news/NewsArticleEmbedFullscreen') }));
vi.mock('../../components/embeds/news/NewsEmbedPreview.svelte', () => ({ default: renderers.get('news/NewsEmbedPreview') }));
vi.mock('../../components/embeds/nutrition/NutritionRecipeEmbedFullscreen.svelte', () => ({ default: renderers.get('nutrition/NutritionRecipeEmbedFullscreen') }));
vi.mock('../../components/embeds/nutrition/NutritionRecipeEmbedPreview.svelte', () => ({ default: renderers.get('nutrition/NutritionRecipeEmbedPreview') }));
vi.mock('../../components/embeds/shopping/ShoppingResultEmbedFullscreen.svelte', () => ({ default: renderers.get('shopping/ShoppingResultEmbedFullscreen') }));
vi.mock('../../components/embeds/shopping/ShoppingResultEmbedPreview.svelte', () => ({ default: renderers.get('shopping/ShoppingResultEmbedPreview') }));
vi.mock('../../components/embeds/social_media/SocialMediaPostEmbedFullscreen.svelte', () => ({ default: renderers.get('social_media/SocialMediaPostEmbedFullscreen') }));
vi.mock('../../components/embeds/social_media/SocialMediaPostEmbedPreview.svelte', () => ({ default: renderers.get('social_media/SocialMediaPostEmbedPreview') }));
vi.mock('../../components/embeds/travel/TravelConnectionEmbedFullscreen.svelte', () => ({ default: renderers.get('travel/TravelConnectionEmbedFullscreen') }));
vi.mock('../../components/embeds/travel/TravelConnectionEmbedPreview.svelte', () => ({ default: renderers.get('travel/TravelConnectionEmbedPreview') }));
vi.mock('../../components/embeds/travel/TravelStayEmbedFullscreen.svelte', () => ({ default: renderers.get('travel/TravelStayEmbedFullscreen') }));
vi.mock('../../components/embeds/travel/TravelStayEmbedPreview.svelte', () => ({ default: renderers.get('travel/TravelStayEmbedPreview') }));
vi.mock('../../components/embeds/videos/VideoEmbedFullscreen.svelte', () => ({ default: renderers.get('videos/VideoEmbedFullscreen') }));
vi.mock('../../components/embeds/videos/VideoEmbedPreview.svelte', () => ({ default: renderers.get('videos/VideoEmbedPreview') }));
vi.mock('../../components/embeds/weather/WeatherDayEmbedFullscreen.svelte', () => ({ default: renderers.get('weather/WeatherDayEmbedFullscreen') }));
vi.mock('../../components/embeds/weather/WeatherDayEmbedPreview.svelte', () => ({ default: renderers.get('weather/WeatherDayEmbedPreview') }));
vi.mock('../../components/embeds/web/WebsiteEmbedFullscreen.svelte', () => ({ default: renderers.get('web/WebsiteEmbedFullscreen') }));
vi.mock('../../components/embeds/web/WebsiteEmbedPreview.svelte', () => ({ default: renderers.get('web/WebsiteEmbedPreview') }));

import fixture from '../../components/embeds/AuthoredResultsPreviewFixture.preview';
import { embedPreviewRegistry } from '../embedPreviewRegistry';
import { loadFullscreenComponent, resolveRegistryKey } from '../embedFullscreenResolver';

// Explicit pre-existing component paths, independent of generated registry maps.
// Both fitness kinds intentionally share one renderer; News has its article viewer.
const canonicalRenderers = [
  ['events.event', 'events/EventEmbedPreview', 'events/EventEmbedFullscreen'],
  ['home.listing', 'home/HomeListingEmbedPreview', 'home/HomeListingEmbedFullscreen'],
  ['health.appointment', 'health/HealthAppointmentEmbedPreview', 'health/HealthAppointmentEmbedFullscreen'],
  ['travel.connection', 'travel/TravelConnectionEmbedPreview', 'travel/TravelConnectionEmbedFullscreen'],
  ['travel.stay', 'travel/TravelStayEmbedPreview', 'travel/TravelStayEmbedFullscreen'],
  ['maps.place', 'maps/MapLocationEmbedPreview', 'maps/MapLocationEmbedFullscreen'],
  ['fitness.location', 'fitness/FitnessResultEmbedPreview', 'fitness/FitnessResultEmbedFullscreen'],
  ['fitness.class', 'fitness/FitnessResultEmbedPreview', 'fitness/FitnessResultEmbedFullscreen'],
  ['shopping.product', 'shopping/ShoppingResultEmbedPreview', 'shopping/ShoppingResultEmbedFullscreen'],
  ['jobs.job_result', 'jobs/JobsResultEmbedPreview', 'jobs/JobsResultEmbedFullscreen'],
  ['nutrition.recipe', 'nutrition/NutritionRecipeEmbedPreview', 'nutrition/NutritionRecipeEmbedFullscreen'],
  ['code.repo', 'code/CodeRepoEmbedPreview', 'code/CodeRepoEmbedFullscreen'],
  ['web.website', 'web/WebsiteEmbedPreview', 'web/WebsiteEmbedFullscreen'],
  ['news.website', 'news/NewsEmbedPreview', 'news/NewsArticleEmbedFullscreen'],
  ['electronics.component', 'electronics/ElectronicsComponentEmbedPreview', 'electronics/ElectronicsComponentEmbedFullscreen'],
  ['business.company_financial_result', 'business/BusinessCompanyFinancialResultEmbedPreview', 'business/BusinessCompanyFinancialResultEmbedFullscreen'],
  ['weather.weather_day', 'weather/WeatherDayEmbedPreview', 'weather/WeatherDayEmbedFullscreen'],
  ['hosting.hosting_domain', 'hosting/HostingDomainEmbedPreview', 'hosting/HostingDomainEmbedFullscreen'],
  ['social_media.social_post', 'social_media/SocialMediaPostEmbedPreview', 'social_media/SocialMediaPostEmbedFullscreen'],
  ['design.icon_result', 'design/DesignIconResultEmbedPreview', 'design/DesignIconResultEmbedFullscreen'],
  ['images.image_result', 'images/ImageResultEmbedPreview', 'images/ImageResultEmbedFullscreen'],
  ['videos.video', 'videos/VideoEmbedPreview', 'videos/VideoEmbedFullscreen'],
  ['models3d.model_result', 'models3d/Model3DResultEmbedPreview', 'models3d/Model3DResultEmbedFullscreen'],
] as const;

describe('authored results reuse canonical existing renderers', () => {
  // contract-test: supporting surface=gui.web assertions=authored-results.eligibility.all-suitable-results,authored-results.surfaces.shared-semantics
  it('covers all 23 existing kinds, with the two new TV kinds verified separately', () => {
    expect(fixture.children).toHaveLength(25);
    expect(canonicalRenderers).toHaveLength(23);
    expect(new Set(canonicalRenderers.map(([kind]) => kind))).toEqual(new Set(
      fixture.children.map(child => child.content.authoring.kind).filter(kind => !kind.startsWith('tv.')),
    ));
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.eligibility.all-suitable-results,authored-results.surfaces.shared-semantics
  it.each(canonicalRenderers)('%s keeps the same canonical preview and fullscreen with and without authoring', async (kind, previewPath, fullscreenPath) => {
    const child = fixture.children.find(value => value.content.authoring.kind === kind)!;
    const { authoring, ...legacyContent } = child.content;
    const previews: unknown[] = [];
    const fullscreens: unknown[] = [];
    for (const content of [legacyContent, { ...legacyContent, authoring }]) {
      const preview = await embedPreviewRegistry.resolve({
        embedId: child.embed_id, embedData: content, decodedContent: content, onFullscreen: () => {},
      });
      expect(preview).not.toBeNull();
      expect(preview!.component).toBe(renderers.previewShell);
      expect(preview!.props.__previewComponent).toBe(renderers.get(previewPath));
      previews.push(preview!.props.__previewComponent);

      const key = resolveRegistryKey(content.type, content);
      expect(key).not.toBeNull();
      const fullscreen = await loadFullscreenComponent(key!);
      expect(fullscreen).not.toBeNull();
      renderers.fullscreenShell.mockClear();
      const props = { content, embedId: child.embed_id };
      fullscreen!({} as Parameters<Component>[0], props);
      expect(renderers.fullscreenShell).toHaveBeenCalledOnce();
      const forwarded = renderers.fullscreenShell.mock.calls[0][1];
      expect(forwarded.__fullscreenComponent).toBe(renderers.get(fullscreenPath));
      expect(forwarded.content).toBe(content);
      expect(forwarded.embedId).toBe(child.embed_id);
      fullscreens.push(forwarded.__fullscreenComponent);
    }
    expect(previews[0]).toBe(previews[1]);
    expect(fullscreens[0]).toBe(fullscreens[1]);
  });
});
