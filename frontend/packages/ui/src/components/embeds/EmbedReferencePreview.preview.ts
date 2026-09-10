// Synthetic event-reference fixture for the normal preview renderer.
// Uses the stored event_result content type from historical event children.
// No account, share fragment, provider request, or private chat is needed.
// The missing variant verifies that bounded loading reaches a terminal state.
// Architecture: docs/architecture/embeds.md

import { embedStore } from '../../services/embedStore';

const EVENT_ID = 'preview-reference-event';
const EVENT_REF = 'community-workshop-A1b';
const event = {
  type: 'event_result',
  app_id: 'events',
  skill_id: 'search',
  embed_ref: EVENT_REF,
  title: 'Community workshop',
  description: 'A synthetic event for testing shared event previews.',
  provider: 'meetup',
  date_start: '2026-10-15T18:00:00Z',
  event_type: 'ONLINE',
  url: 'https://example.com/workshop',
};

embedStore.registerStaticEmbed({
  embedId: EVENT_ID,
  type: 'event_result',
  appId: 'events',
  skillId: 'search',
  content: JSON.stringify(event),
});
embedStore.registerEmbedRef(EVENT_REF, EVENT_ID, 'events', 'event_result', 'event_result');

export default { embedRef: EVENT_REF };
export const variants = {
  missing: { embedRef: 'missing-event-Z9z' },
};
