/** /dev/preview/settings/MemoryEntryPage: create page, edit page with app, and an unsaved suggestion diff. */
const stored = {
  title: 'Window seat on long flights', when_to_use: 'Booking flights.', body: '- Window seat\n- Aisle on short hops',
  load_mode: 'ask_first' as const, app_id: 'travel', created_at: 1_760_000_000, updated_at: 1_762_000_000,
};
const appOptions = [{ value: '', label: 'None' }, { value: 'code', label: 'Code' }, { value: 'travel', label: 'Travel' }];
const emit = (name: string, detail?: unknown) => window.dispatchEvent(new CustomEvent(name, { detail }));

function props(extra: Record<string, unknown> = {}) {
  return {
    initial: { title: '', when_to_use: '', body: '', load_mode: 'auto_include' },
    original: null, isDraft: false, isNew: true, saving: false, error: '', canDelete: true, appOptions,
    onSave: (fields: unknown) => {
      emit('memory-preview-save', fields);
      document.documentElement.dataset.memoryPreviewSaved = JSON.stringify(fields);
    },
    onCancel: () => emit('memory-preview-cancel'),
    onDelete: () => emit('memory-preview-delete'),
    onError: (message: string) => emit('memory-preview-error', message),
    ...extra,
  };
}

export default props();
export const variants = {
  edit: props({ initial: stored, isNew: false }),
  suggestion: props({
    initial: { ...stored, title: 'Seat preferences', body: '- Window seat on flights over three hours' },
    original: stored, isDraft: true, isNew: false,
  }),
  error: props({ initial: stored, isNew: false, error: 'Could not load or save the Memories. Please try again.' }),
};
