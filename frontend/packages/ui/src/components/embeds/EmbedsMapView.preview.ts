// frontend/packages/ui/src/components/embeds/EmbedsMapView.preview.ts
// Static preview data for the virtual in-chat results-view renderer.
// The fixture seeds local cleartext embeds only; it does not call app skills,
// providers, chat APIs, or enrichment endpoints. Playwright uses this preview to
// verify deployed browser rendering without private share URLs or auth state.
// Spec: docs/specs/embeds-map-view/spec.yml

import type { ComponentProps } from 'svelte';
import type EmbedsMapView from './EmbedsMapView.svelte';
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

const previewProps = {
	id: 'preview-map-view',
	title: 'Berlin to Bangkok flight options',
	embedRefs: [],
	sourceRefs: [SOURCE_REF],
	highlightRefs: CHILD_IDS.slice(0, 1)
} satisfies ComponentProps<typeof EmbedsMapView>;

export default previewProps;
