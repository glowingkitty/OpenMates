// Event search: a per-unit web search price charged next to Mercury 3 tokens, plus the typical-cost note.
import { appSkillsStore, resetFeatureAvailability, userAvailableSkillsStore } from '../../stores/appSkillsStore';
import type { AppMetadata } from '../../types/apps';

export default { appId: 'events', skillId: 'search' };

export const variants = {
  'events-search': { appId: 'events', skillId: 'search' },
};

// events.search ships default_enabled: false, so static build metadata omits it and the server
// admits it at runtime (backend_config.yml feature_overrides). This mirrors that runtime entry as
// /v1/apps/metadata returns it (backend/core/api/app/routes/apps.py _skill_pricing over
// backend/apps/events/app.yml; backend/tests/test_events_search_billing.py pins the same values).
const runtimeEvents = {
  id: 'events',
  name: 'Events',
  description: 'Find events and conferences.',
  icon_image: 'events.svg',
  category: 'lifestyle',
  skills: [{
    id: 'search',
    name: 'Search',
    description: 'Find upcoming events and conferences.',
    icon_image: 'search.svg',
    pricing: {
      per_unit: { credits: 10, unit_name: 'web search' },
      tokens: { input: { per_credit_unit: 3335 }, output: { per_credit_unit: 955 } },
      tokens_model: 'inception/mercury-3',
    },
    providers: ['Brave', 'Inception'],
  }],
} as unknown as AppMetadata;

export const ready = (() => {
  if (typeof window === 'undefined') return;
  resetFeatureAvailability();
  const apps: Record<string, AppMetadata> = { ...appSkillsStore.getState().apps, events: runtimeEvents };
  userAvailableSkillsStore.set({
    initialized: true, loading: false, appsById: apps,
    skillsByApp: Object.fromEntries(Object.entries(apps).map(([id, app]) => [id, (app.skills ?? []).map(skill => skill.id)])),
  });
})();
