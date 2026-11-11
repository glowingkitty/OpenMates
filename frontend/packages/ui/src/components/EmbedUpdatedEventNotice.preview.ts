/** Preview fixtures for the chat-history "embed updated" system event row. */
const noop = () => {};
const group = {
  embed_id: 'embed-preview-1', embed_ref: 'sunset-1', embed_kind: 'image' as const,
  latest_version: 3, change_count: 1, latest_action: 'enhance' as const,
  latest_created_at: 1_790_000_000, message_ids: ['embed-updated-embed-preview-1-v3'], surface: 'chat' as const,
};
export default { group, onOpen: noop };
export const variants = {
  edit: { group: { ...group, embed_kind: 'document' as const, latest_action: 'edit' as const, latest_version: 2 }, onOpen: noop },
  restore: { group: { ...group, embed_kind: 'sheet' as const, latest_action: 'restore' as const, latest_version: 5, restored_from: 2 }, onOpen: noop },
  crop: { group: { ...group, latest_action: 'crop' as const, latest_version: 4 }, onOpen: noop },
  collapsedEdits: { group: { ...group, embed_kind: 'slides' as const, latest_action: 'edit' as const, latest_version: 7, change_count: 4 }, onOpen: noop },
  collapsedMixed: { group: { ...group, latest_version: 6, change_count: 3 }, onOpen: noop },
  readOnly: { group, onOpen: undefined },
};
