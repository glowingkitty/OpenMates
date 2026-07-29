// frontend/packages/ui/src/components/embeds/EmbedsMapView.preview.ts
// Static preview data for the virtual in-chat map/list renderer.
// The fixture seeds local cleartext embeds only; it does not call app skills,
// providers, chat APIs, or enrichment endpoints. Playwright uses this preview to
// verify deployed browser rendering without private share URLs or auth state.
// Spec: docs/specs/embeds-map-view/spec.yml

import type { ComponentProps } from 'svelte';
import type EmbedsMapView from './EmbedsMapView.svelte';
import { embedStore } from '../../services/embedStore';

const SOURCE_REF = 'events-search-preview-abc123';
const EVENT_REF = 'ai-founders-meetup-111111';
const PLACE_REF = 'factory-berlin-222222';
const ROUTE_REF = 'berlin-leipzig-route-333333';

const SOURCE_ID = '00000000-0000-4000-8000-000000000001';
const EVENT_ID = '00000000-0000-4000-8000-000000000002';
const PLACE_ID = '00000000-0000-4000-8000-000000000003';
const ROUTE_ID = '00000000-0000-4000-8000-000000000004';

const CHILD_REFS = [EVENT_REF, PLACE_REF, ROUTE_REF];

function seedPreviewEmbeds(): void {
	embedStore.clearEmbedRefIndex();
	embedStore.registerEmbedRef(SOURCE_REF, SOURCE_ID, 'events');
	embedStore.registerEmbedRef(EVENT_REF, EVENT_ID, 'events');
	embedStore.registerEmbedRef(PLACE_REF, PLACE_ID, 'maps');
	embedStore.registerEmbedRef(ROUTE_REF, ROUTE_ID, 'travel');

	embedStore.registerStaticEmbed({
		embedId: SOURCE_ID,
		type: 'app_skill_use',
		appId: 'events',
		skillId: 'search',
		embedIds: CHILD_REFS,
		content: JSON.stringify({
			app_id: 'events',
			skill_id: 'search',
			embed_ids: CHILD_REFS
		})
	});
	embedStore.registerStaticEmbed({
		embedId: EVENT_ID,
		type: 'events-event',
		appId: 'events',
		skillId: 'event',
		content: JSON.stringify({
			app_id: 'events',
			skill_id: 'event',
			title: 'AI Founders Meetup',
			date_start: '2026-08-01T18:00:00Z',
			venue: {
				name: 'w3hub',
				address: 'Moeckernstrasse 120, Berlin',
				lat: 52.4987,
				lon: 13.3818
			}
		})
	});
	embedStore.registerStaticEmbed({
		embedId: PLACE_ID,
		type: 'maps-place',
		appId: 'maps',
		skillId: 'place',
		content: JSON.stringify({
			app_id: 'maps',
			skill_id: 'place',
			displayName: 'Factory Berlin',
			formattedAddress: 'Lohmuehlenstrasse 65, Berlin',
			lat: 52.4982,
			lon: 13.4462
		})
	});
	embedStore.registerStaticEmbed({
		embedId: ROUTE_ID,
		type: 'travel-connection',
		appId: 'travel',
		skillId: 'search_connections',
		content: JSON.stringify({
			app_id: 'travel',
			skill_id: 'search_connections',
			origin_name: 'Berlin Hbf',
			destination_name: 'Leipzig Hbf',
			departure: '2026-08-01T19:00:00Z',
			provider: 'Deutsche Bahn',
			origin: { lat: 52.5251, lon: 13.3694 },
			destination: { lat: 51.3452, lon: 12.3822 }
		})
	});
}

seedPreviewEmbeds();

const previewProps = {
	id: 'preview-map-view',
	title: 'Berlin AI events and routes',
	embedRefs: [],
	sourceRefs: [SOURCE_REF],
	highlightRefs: [PLACE_REF]
} satisfies ComponentProps<typeof EmbedsMapView>;

export default previewProps;
