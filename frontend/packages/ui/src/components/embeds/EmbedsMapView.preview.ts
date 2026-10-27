// frontend/packages/ui/src/components/embeds/EmbedsMapView.preview.ts
// Static preview data for the virtual in-chat results-view renderer.
// The fixture seeds local cleartext embeds only; it does not call app skills,
// providers, chat APIs, or enrichment endpoints. Playwright uses this preview to
// verify deployed browser rendering without private share URLs or auth state.
// Spec: docs/specs/embeds-map-view/spec.yml

import type { ComponentProps } from 'svelte';
import type EmbedsMapView from './EmbedsMapView.svelte';
import { listing as homeListing } from './home/HomeListingEmbedFullscreen.preview';
import { embedStore } from '../../services/embedStore';
import { flightsBerlinBangkokChat } from '../../demo_chats/data/example_chats/flights-berlin-to-bangkok';

const sourceEmbed = flightsBerlinBangkokChat.embeds.find((embed) => embed.type === 'app_skill_use');
if (!sourceEmbed) throw new Error('Flights preview requires its travel search parent embed');
const SOURCE_REF = 'berlin-bangkok-flight-search-preview';
const CHILD_IDS = sourceEmbed.embed_ids ?? [];

function seedPreviewEmbeds(): void {
	embedStore.clearEmbedRefIndex();
	embedStore.registerEmbedRef(SOURCE_REF, sourceEmbed.embed_id, 'travel');
	for (const embed of flightsBerlinBangkokChat.embeds) {
		if (embed.type !== 'app_skill_use' && embed.type !== 'connection') continue;
		embedStore.registerStaticEmbed({
			embedId: embed.embed_id,
			type: embed.type,
			appId: 'travel',
			skillId: 'search_connections',
			embedIds: embed.embed_ids ?? undefined,
			content: embed.content
		});
	}
}

seedPreviewEmbeds();
// Eligibility fixtures contain no remote content or provider requests.
for (const [embedId, content] of Object.entries({
  'preview-date-only': { title: 'Date-only event', date: '2026-09-20' },
  'preview-invalid-entry': { title: 'Invalid entry', date: '2026-02-30', lat: 100, lon: 200 },
})) {
  embedStore.registerStaticEmbed({ embedId, type: 'event', appId: 'events', content: JSON.stringify(content) });
}

const HOME_REFS = ['preview-home-district', 'preview-home-description', 'preview-home-exact', 'preview-home-legacy'];
for (const [index, embedId] of HOME_REFS.entries()) {
  const content = index === 0 ? {...homeListing, title: 'District home', price: 1200}
    : index === 1 ? {...homeListing, title: 'Description home', price: 1400, location: {area: {...homeListing.location.area, radius_m: 650, basis: 'description'}}}
    : index === 2 ? {...homeListing, title: 'Published exact home', provider: 'ExampleHousingA', price: 1600, address: 'Example Street 12, Berlin', location: {exact_address: true}, location_precision: 'building', location_approximate: false}
    : {...homeListing, title: 'Legacy approximate center', location: {}};
  embedStore.registerStaticEmbed({embedId, type: 'home-listing', appId: 'home', content: JSON.stringify(content)});
}


const previewProps = {
	id: 'preview-map-view',
	title: 'Berlin to Bangkok flight options',
	embedRefs: [],
	sourceRefs: [SOURCE_REF],
	highlightRefs: CHILD_IDS.slice(0, 1)
} satisfies ComponentProps<typeof EmbedsMapView>;

export default previewProps;

// Separate searches return new child IDs for the same event. Over one batch of
// copies also verifies that duplicates cannot hide later unique results.
const DUPLICATE_EVENT_IDS = Array.from({ length: 42 }, (_, index) => `preview-repeat-event-${index}`);
const duplicateEvent = {
  app_id: 'events', provider: 'Gathering', title: 'Community AI evening',
  description: 'Meet local builders and share what you are working on.',
  url: 'https://events.example.org/ai-evening', date_start: '2026-10-22T17:00:00Z',
  venue: { name: 'Community space', city: 'Berlin', lat: 52.52, lon: 13.405 },
};
for (const embedId of DUPLICATE_EVENT_IDS) {
  embedStore.registerStaticEmbed({ embedId, type: 'event', appId: 'events', content: JSON.stringify(duplicateEvent) });
}
const UNIQUE_EVENT_IDS = ['preview-builders-lunch', 'preview-next-evening'];
for (const [index, embedId] of UNIQUE_EVENT_IDS.entries()) {
  const content = index === 0
    ? { ...duplicateEvent, title: 'Builder lunch', url: 'https://events.example.org/builders-lunch', date_start: '2026-10-23T11:00:00Z', venue: { ...duplicateEvent.venue, lat: 52.515, lon: 13.41 } }
    : { ...duplicateEvent, title: 'Community AI evening (next day)', date_start: '2026-10-23T17:00:00Z' };
  embedStore.registerStaticEmbed({ embedId, type: 'event', appId: 'events', content: JSON.stringify(content) });
}
for (const [embedId, children] of [
  ['preview-events-source-one', DUPLICATE_EVENT_IDS.slice(0, 41)],
  ['preview-events-source-two', [...DUPLICATE_EVENT_IDS.slice(41), ...UNIQUE_EVENT_IDS]],
] as const) {
  embedStore.registerStaticEmbed({ embedId, type: 'app_skill_use', appId: 'events', skillId: 'search', embedIds: [...children], content: JSON.stringify({ app_id: 'events', skill_id: 'search', embed_ids: children, status: 'finished' }) });
}
embedStore.registerEmbedRef('community-ai-evening-Ab1', DUPLICATE_EVENT_IDS[0], 'events');

export const variants = { duplicateEvents: { ...previewProps, id: 'preview-duplicate-events', title: 'Community events', embedRefs: ['community-ai-evening-Ab1'], sourceRefs: ['preview-events-source-one', 'preview-events-source-two'], highlightRefs: [DUPLICATE_EVENT_IDS[41]], interactionMode: 'select' }, homes: {...previewProps, id: 'preview-home-map-view', title: 'Homes with truthful location geometry', embedRefs: HOME_REFS, sourceRefs: [], highlightRefs: [], interactionMode: 'select'}, fullscreen: { ...previewProps, highlightRefs: [], fullscreen: true }, fullscreenCalendar: { ...previewProps, highlightRefs: [], fullscreen: true, initialVisualTab: 'calendar' } };
