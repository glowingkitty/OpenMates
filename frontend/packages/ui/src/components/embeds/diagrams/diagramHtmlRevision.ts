/** Atomic, client-encrypted manual diagram edits with server revision and source-hash CAS. */
import { encode } from '@toon-format/toon';
import { embedStore } from '../../../services/embedStore';
import { chatDB } from '../../../services/db';
import { buildUnifiedDiff, fetchEmbedVersions, storeEmbedDiff } from '../../../services/embedDiffStore';
import { encryptWithEmbedKey } from '../../../services/encryption/MetadataEncryptor';
import { withCanonicalEmbedWrite } from '../../../services/canonicalEmbedWriteCoordinator';
import { webSocketService } from '../../../services/websocketService';
import { chatSyncService } from '../../../services/chatSyncService';
import { computeSHA256 } from '../../../message_parsing/utils';
import { validateDiagramHtml } from './diagramHtmlContent';
import { requiresInitialDiagramSnapshot } from './diagramHtmlHistory';
import { reconcileCommittedDiagramRevision } from './diagramHtmlReceipt';

interface SaveInput {
  embedId: string;
  chatId: string;
  current: Record<string, unknown>;
  originalSource: string;
  editedSource: string;
}

export interface DiagramSaveResult { version: number; cacheSynchronized: boolean }

export async function saveDiagramHtmlRevision(input: SaveInput): Promise<DiagramSaveResult> {
  return withCanonicalEmbedWrite(input.embedId, async () => {
    validateDiagramHtml(input.editedSource);
    if (input.originalSource === input.editedSource) return { version: Number(input.current.version_number) || 1, cacheSynchronized: true };
    const chat = await chatDB.getChat(input.chatId);
    const teamId = chat?.team_id || null;
    const versions = await fetchEmbedVersions(input.embedId, { chatId: input.chatId, teamId });
    if (versions.readonly) throw new Error('This diagram is read-only');
    const currentVersion = Number(input.current.version_number) || 1;
    const raw = await embedStore.getRawEntry(`embed:${input.embedId}`);
    if (!raw || raw.version_number !== currentVersion || versions.current_version !== currentVersion) {
      throw new Error('The diagram changed on another device. Reload before editing.');
    }
    const key = await embedStore.getEmbedKey(input.embedId, raw.hashed_chat_id);
    if (!key) throw new Error('Diagram encryption key is unavailable');
    const nextVersion = currentVersion + 1;
    const oldHash = await computeSHA256(input.originalSource);
    const newHash = await computeSHA256(input.editedSource);
    const next = { ...input.current, html_source: input.editedSource, version_number: nextVersion, status: 'finished' };
    const encryptedContent = await encryptWithEmbedKey(encode(next), key);
    const patch = buildUnifiedDiff(input.originalSource, input.editedSource, currentVersion, nextVersion);
    const encryptedPatch = await encryptWithEmbedKey(patch, key);
    const initialSnapshot = requiresInitialDiagramSnapshot(currentVersion, versions.versions)
      ? await encryptWithEmbedKey(input.originalSource, key) : null;
    const checkpoint = nextVersion % 32 === 0 ? await encryptWithEmbedKey(input.editedSource, key) : null;
    if (!encryptedContent || !encryptedPatch || (requiresInitialDiagramSnapshot(currentVersion, versions.versions) && !initialSnapshot) || (nextVersion % 32 === 0 && !checkpoint)) {
      throw new Error('Could not encrypt diagram edit');
    }
    const createdAt = Math.floor(Date.now() / 1000);
    const operationId = crypto.randomUUID();
    const payload = {
      operation_id: operationId,
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
    const result = await commitWithReceipt(payload);
    if (result.status === 'conflict') throw new Error('The diagram changed on another device. Reload before editing.');
    if (result.status !== 'committed' || result.current_revision !== nextVersion || result.current_content_hash !== newHash) {
      throw new Error(typeof result.code === 'string' ? result.code : 'Diagram save was rejected');
    }
    // Update local state only after the durable atomic receipt. The canonical write
    // coordinator serializes this with any other local writer for the same embed.
    const cacheSynchronized = await reconcileCommittedDiagramRevision(async () => {
      const update = await embedStore.prepareVersionRestoreUpdate(input.embedId, encode(next), nextVersion, newHash);
      if (!update.updated) throw new Error('Local diagram cache needs refresh');
      if (initialSnapshot) await storeEmbedDiff({ id: `${input.embedId}_v1`, embed_id: input.embedId, version_number: 1, encrypted_snapshot: initialSnapshot, created_at: createdAt });
      await storeEmbedDiff({ id: `${input.embedId}_v${nextVersion}`, embed_id: input.embedId, version_number: nextVersion, encrypted_patch: encryptedPatch, ...(checkpoint ? { encrypted_snapshot: checkpoint } : {}), created_at: createdAt });
    });
    if (cacheSynchronized) chatSyncService.dispatchEvent(new CustomEvent('embedUpdated', { detail: { embed_id: input.embedId, chat_id: input.chatId, status: 'finished' } }));
    return { version: nextVersion, cacheSynchronized };
  });
}

type CommitResult = { request_id?: string; status?: string; current_revision?: number; current_content_hash?: string; code?: string };

async function commitWithReceipt(payload: Record<string, unknown>): Promise<CommitResult> {
  const requestId = crypto.randomUUID();
  const request = { ...payload, request_id: requestId };
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      return await new Promise<CommitResult>((resolve, reject) => {
        const timer = setTimeout(() => { cleanup(); reject(new Error('Diagram save confirmation timed out')); }, 30_000);
        const onResult = (raw: unknown) => {
          const result = raw as CommitResult;
          if (result?.request_id !== requestId) return;
          cleanup(); resolve(result);
        };
        const onClose = () => { cleanup(); reject(new Error('Connection closed during diagram save')); };
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
  throw new Error('Diagram save confirmation failed');
}
