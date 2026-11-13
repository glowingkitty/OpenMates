/**
 * Shape of a folded run of `embed_updated` chat events as produced by the
 * client core's `group_embed_updated_events` (Rust `EmbedUpdatedGroup`, snake_case
 * JSON). Presentation only: the core owns the grouping and the payload codec.
 */
export type EmbedUpdatedKind = 'image' | 'diagram' | 'slides' | 'sheet' | 'document';
export type EmbedUpdatedAction = 'edit' | 'enhance' | 'restore' | 'crop';

export interface EmbedUpdatedGroup {
  embed_id: string;
  embed_ref: string;
  embed_kind: EmbedUpdatedKind;
  /** Newest version of the run. */
  latest_version: number;
  /** Number of events in the run; 1 when nothing was collapsed. */
  change_count: number;
  /** Action of the newest event. */
  latest_action: EmbedUpdatedAction;
  latest_created_at: number;
  message_ids: string[];
  /** Version that was restored; present only when the newest event is a restore. */
  restored_from?: number;
  /** Where the newest change was made. */
  surface: 'chat' | 'project';
}
