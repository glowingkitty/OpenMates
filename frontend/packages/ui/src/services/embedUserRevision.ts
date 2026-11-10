/**
 * frontend/packages/ui/src/services/embedUserRevision.ts
 *
 * Client-authored revision of an allowlisted chat embed (HTML diagram, slide
 * deck, sheet): one atomic, client-encrypted server commit with a
 * compare-and-swap on the head revision and content hash. Wire name
 * `commit_chat_diagram_revision` predates the allowlist; the server
 * (Directus `embed-version-transaction` extension) refuses other embed types.
 *
 * Order: version check against server history, encryption of head + history
 * rows (v1 snapshot when the head has none, checkpoint every 32 versions),
 * commit with a durable receipt, and only then the local IndexedDB head and
 * history rows. A conflict or rejection leaves local state untouched and
 * queues nothing, so a retry starts from the same base.
 */
import { encode } from '@toon-format/toon';
import { embedStore } from './embedStore';
import { chatDB } from './db';
import { buildUnifiedDiff, fetchEmbedVersions, storeEmbedDiff } from './embedDiffStore';
import { encryptWithEmbedKey } from './encryption/MetadataEncryptor';
import { withCanonicalEmbedWrite } from './canonicalEmbedWriteCoordinator';
import { webSocketService } from './websocketService';
import { chatSyncService } from './chatSyncService';
import { computeSHA256 } from '../message_parsing/utils';
import { reconcileCommittedRevision, requiresInitialSnapshot } from './embedUserRevisionHistory';

/** Versions between full encrypted checkpoints in the history chain. */
const CHECKPOINT_INTERVAL = 32;
const COMMIT_TIMEOUT_MS = 30_000;

/** Why a revision was not saved; `conflict` means the head moved under the edit. */
export type EmbedUserRevisionFailure = 'conflict' | 'readonly' | 'key_unavailable' | 'encryption_failed' | 'rejected' | 'transport';

export class EmbedUserRevisionError extends Error {
  readonly failure: EmbedUserRevisionFailure;
  constructor(failure: EmbedUserRevisionFailure, message: string) {
    super(message);
    this.name = 'EmbedUserRevisionError';
    this.failure = failure;
  }
}

export interface EmbedUserRevisionInput {
  embedId: string;
  chatId: string;
  /** Decoded content of the current head (the version the edit was made on). */
  current: Record<string, unknown>;
  /** Content field that holds the editable source, e.g. `html_source`, `slides_markup`. */
  sourceField: string;
  originalSource: string;
  editedSource: string;
  /** Lower-case noun used in user-facing errors, e.g. `diagram`, `deck`. */
  noun: string;
  /**
   * Base hash for the compare-and-swap. `source`: SHA-256 of `originalSource`.
   * `stored-head`: the head `content_hash` held in the local cache, which is the
   * value the server stored; SHA-256 of `originalSource` only when the cache has none.
   */
  expectedHash: 'source' | 'stored-head';
  /** Next head content; default replaces `sourceField` on `current`. */
  buildContent?: (editedSource: string, version: number) => Record<string, unknown>;
}

export interface EmbedUserRevisionResult { version: number; cacheSynchronized: boolean }

function capitalize(noun: string): string {
  return noun.charAt(0).toUpperCase() + noun.slice(1);
}

export async function commitEmbedUserRevision(input: EmbedUserRevisionInput): Promise<EmbedUserRevisionResult> {
  return withCanonicalEmbedWrite(input.embedId, async () => {
    const noun = input.noun;
    const Noun = capitalize(noun);
    const conflictMessage = `The ${noun} changed on another device. Reload before editing.`;
    if (input.originalSource === input.editedSource) {
      return { version: Number(input.current.version_number) || 1, cacheSynchronized: true };
    }
    const chat = await chatDB.getChat(input.chatId);
    const teamId = chat?.team_id || null;
    const versions = await fetchEmbedVersions(input.embedId, { chatId: input.chatId, teamId });
    if (versions.readonly) throw new EmbedUserRevisionError('readonly', `This ${noun} is read-only`);
    const currentVersion = Number(input.current.version_number) || 1;
    const raw = await embedStore.getRawEntry(`embed:${input.embedId}`);
    if (!raw || raw.version_number !== currentVersion || versions.current_version !== currentVersion) {
      throw new EmbedUserRevisionError('conflict', conflictMessage);
    }
    const key = await embedStore.getEmbedKey(input.embedId, raw.hashed_chat_id);
    if (!key) throw new EmbedUserRevisionError('key_unavailable', `${Noun} encryption key is unavailable`);
    const nextVersion = currentVersion + 1;
    const storedHash = typeof raw.content_hash === 'string' && /^[0-9a-f]{64}$/.test(raw.content_hash) ? raw.content_hash : null;
    const oldHash = input.expectedHash === 'stored-head' && storedHash ? storedHash : await computeSHA256(input.originalSource);
    const newHash = await computeSHA256(input.editedSource);
    const built = input.buildContent
      ? input.buildContent(input.editedSource, nextVersion)
      : { ...input.current, [input.sourceField]: input.editedSource };
    const next = { ...built, version_number: nextVersion, status: 'finished' };
    const encryptedContent = await encryptWithEmbedKey(encode(next), key);
    const patch = buildUnifiedDiff(input.originalSource, input.editedSource, currentVersion, nextVersion);
    const encryptedPatch = await encryptWithEmbedKey(patch, key);
    const needsInitial = requiresInitialSnapshot(currentVersion, versions.versions);
    const initialSnapshot = needsInitial ? await encryptWithEmbedKey(input.originalSource, key) : null;
    const needsCheckpoint = nextVersion % CHECKPOINT_INTERVAL === 0;
    const checkpoint = needsCheckpoint ? await encryptWithEmbedKey(input.editedSource, key) : null;
    if (!encryptedContent || !encryptedPatch || (needsInitial && !initialSnapshot) || (needsCheckpoint && !checkpoint)) {
      throw new EmbedUserRevisionError('encryption_failed', `Could not encrypt ${noun} edit`);
    }
    const createdAt = Math.floor(Date.now() / 1000);
    const payload = {
      operation_id: crypto.randomUUID(),
      embed_id: input.embedId,
      chat_id: input.chatId,
      ...(teamId ? { team_id: teamId } : {}),
      expected_revision: currentVersion,
      expected_content_hash: oldHash,
      head: { encrypted_content: encryptedContent, content_hash: newHash, status: 'finished', updated_at: createdAt },
      history_rows: [
        ...(initialSnapshot ? [{ version_number: 1, encrypted_snapshot: initialSnapshot, created_at: createdAt }] : []),
        { version_number: nextVersion, encrypted_patch: encryptedPatch, ...(checkpoint ? { encrypted_snapshot: checkpoint } : {}), created_at: createdAt }
      ]
    };
    const result = await commitWithReceipt(payload, Noun, noun);
    if (result.status === 'conflict') throw new EmbedUserRevisionError('conflict', conflictMessage);
    if (result.status !== 'committed' || result.current_revision !== nextVersion || result.current_content_hash !== newHash) {
      throw new EmbedUserRevisionError('rejected', typeof result.code === 'string' ? result.code : `${Noun} save was rejected`);
    }
    const cacheSynchronized = await reconcileCommittedRevision(async () => {
      const update = await embedStore.prepareVersionRestoreUpdate(input.embedId, encode(next), nextVersion, newHash);
      if (!update.updated) throw new Error(`Local ${noun} cache needs refresh`);
      if (initialSnapshot) await storeEmbedDiff({ id: `${input.embedId}_v1`, embed_id: input.embedId, version_number: 1, encrypted_snapshot: initialSnapshot, created_at: createdAt });
      await storeEmbedDiff({ id: `${input.embedId}_v${nextVersion}`, embed_id: input.embedId, version_number: nextVersion, encrypted_patch: encryptedPatch, ...(checkpoint ? { encrypted_snapshot: checkpoint } : {}), created_at: createdAt });
    });
    if (cacheSynchronized) chatSyncService.dispatchEvent(new CustomEvent('embedUpdated', { detail: { embed_id: input.embedId, chat_id: input.chatId, status: 'finished' } }));
    return { version: nextVersion, cacheSynchronized };
  });
}

type CommitResult = { request_id?: string; status?: string; current_revision?: number; current_content_hash?: string; code?: string };

/** One request id per save; a lost reply is re-sent once with the same operation id (idempotent receipt). */
async function commitWithReceipt(payload: Record<string, unknown>, Noun: string, noun: string): Promise<CommitResult> {
  const requestId = crypto.randomUUID();
  const request = { ...payload, request_id: requestId };
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      return await new Promise<CommitResult>((resolve, reject) => {
        const timer = setTimeout(() => { cleanup(); reject(new EmbedUserRevisionError('transport', `${Noun} save confirmation timed out`)); }, COMMIT_TIMEOUT_MS);
        const onResult = (raw: unknown) => {
          const result = raw as CommitResult;
          if (result?.request_id !== requestId) return;
          cleanup(); resolve(result);
        };
        const onClose = () => { cleanup(); reject(new EmbedUserRevisionError('transport', `Connection closed during ${noun} save`)); };
        const cleanup = () => {
          clearTimeout(timer);
          webSocketService.off('commit_chat_diagram_revision_result', onResult);
          webSocketService.removeEventListener('close', onClose);
        };
        webSocketService.on('commit_chat_diagram_revision_result', onResult);
        webSocketService.addEventListener('close', onClose);
        void webSocketService.sendMessage('commit_chat_diagram_revision', request).catch((error) => { cleanup(); reject(error); });
      });
    } catch (error) {
      if (attempt === 1) throw error;
    }
  }
  throw new EmbedUserRevisionError('transport', `${Noun} save confirmation failed`);
}
