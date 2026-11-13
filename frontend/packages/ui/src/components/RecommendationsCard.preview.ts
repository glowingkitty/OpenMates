// Preview states for the chat Recommendations card:
// /dev/preview/RecommendationsCard?chrome=0 (3 items), &variant=single (1), &variant=six (6),
// &variant=busy, &variant=up_to_date, &variant=no_category (primary color); any item list via &props={"items":[...]}.
import type { ChatRecommendation } from '../types/recommendations';

const catalogue: ChatRecommendation[] = [
  { id: 'preview-rec-1', kind: 'memory', action: 'create', target_id: null, title: 'Conference day pacing', summary: 'Plan conference days with a balance of talks, hallway conversations and rest breaks.' },
  { id: 'preview-rec-2', kind: 'workflow', action: 'create', target_id: null, title: 'Weekly open source conference digest', summary: 'Every Monday, summarize upcoming open source conferences and their talk submission deadlines.' },
  { id: 'preview-rec-3', kind: 'memory', action: 'update', target_id: 'personal:preview-memory', title: 'Preferred conference topics', summary: 'Add developer tooling and privacy to the topics you prioritize.' },
  { id: 'preview-rec-4', kind: 'workflow', action: 'update', target_id: 'preview-workflow', title: 'Monthly travel budget check', summary: 'Also include conference tickets in the monthly budget summary.' },
  { id: 'preview-rec-5', kind: 'memory', action: 'create', target_id: null, title: 'Talk note format', summary: 'Keep talk notes as three key takeaways plus one follow-up question.' },
  { id: 'preview-rec-6', kind: 'workflow', action: 'create', target_id: null, title: 'Speaker follow-up reminders', summary: 'Two days after each conference, remind me to contact the speakers I noted.' },
];

const props = {
  items: catalogue.slice(0, 3),
  category: 'software_development' as string | null,
  busyId: null as string | null,
  statusText: null as string | null,
  // Records the last opened recommendation so the component spec can prove that the
  // embed preview and the Create/Update button trigger the same action.
  onAction: (item: ChatRecommendation) => {
    if (typeof document !== 'undefined') document.body.dataset.recommendationOpened = `${item.id}:${Date.now()}`;
  },
};

export default props;
export const variants = {
  single: { ...props, items: catalogue.slice(0, 1) },
  six: { ...props, items: catalogue },
  busy: { ...props, busyId: 'preview-rec-1' },
  no_category: { ...props, category: null },
  up_to_date: { ...props, items: [catalogue[2]], statusText: 'This memory is already up to date.' },
};
