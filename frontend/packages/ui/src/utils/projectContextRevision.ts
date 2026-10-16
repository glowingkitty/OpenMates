import { computeSHA256 } from '../message_parsing/utils';

/** Matches server project_item_revision, including Python's false/zero fallback. */
export function projectRecordRevision(record: Record<string, unknown>): Promise<string> {
  return computeSHA256([
    record.updated_at, record.encrypted_metadata, record.encrypted_note,
    record.target_id_hash, record.deleted_target_state,
  ].map((value) => value ? String(value) : '').join('\0'));
}
