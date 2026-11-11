/** /dev/preview/settings/MemoryList: several memories (long title, with/without app, expired, untimed). */
import { serializeRuleDocument, type RuleDocumentFields } from '../../utils/ruleDocuments';
import { memoryListEntries } from '../../utils/memoryListEntries';

const doc = (id: string, fields: Partial<RuleDocumentFields> & { title: string }) => ({
  id, source: 'personal' as const,
  document: serializeRuleDocument({ when_to_use: '', body: `${fields.title}.`, load_mode: 'auto_include', ...fields }),
});

const documents = [
  doc('personal:untimed', { title: 'Writing tone' }),
  doc('personal:trip', { title: 'Window seat on long flights', app_id: 'travel', created_at: 1_760_000_000, updated_at: 1_762_000_000 }),
  doc('personal:long', {
    title: 'Kitchen renovation: keep the original oak floor, prefer matte black fittings and leave room for a second oven later',
    created_at: 1_761_000_000,
  }),
  doc('personal:code', { title: 'Svelte component habits', app_id: 'code', created_at: 1_755_000_000, updated_at: 1_755_000_000 }),
  doc('personal:expired', { title: 'Summer train pass', valid_until: '2020-01-01T23:59:59.000Z', created_at: 1_700_000_000 }),
];
const known = new Set(['travel', 'code']);

function props(extra: Record<string, unknown> = {}) {
  return {
    entries: memoryListEntries(documents),
    loading: false, saving: false, notice: '', sourceLabel: 'Private',
    usedChars: documents.reduce((sum, item) => sum + item.document.length, 0),
    appIcon: (appId: string | undefined) => (appId && known.has(appId) ? `app-${appId}` : null),
    onCreate: () => window.dispatchEvent(new CustomEvent('memory-preview-create')),
    onOpen: (entry: { document: { id: string } }) => window.dispatchEvent(new CustomEvent('memory-preview-open', { detail: entry.document.id })),
    onRenew: (entry: { document: { id: string } }) => window.dispatchEvent(new CustomEvent('memory-preview-renew', { detail: entry.document.id })),
    ...extra,
  };
}

export default props();
export const variants = {
  empty: props({ entries: [], usedChars: 0 }),
  loading: props({ loading: true }),
  saved: props({ notice: 'Memory saved.' }),
};
