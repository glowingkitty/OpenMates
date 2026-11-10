/** Atomic, client-encrypted manual diagram edits with server revision and source-hash CAS. */
import { commitEmbedUserRevision } from '../../../services/embedUserRevision';
import { validateDiagramHtml } from './diagramHtmlContent';

interface SaveInput {
  embedId: string;
  chatId: string;
  current: Record<string, unknown>;
  originalSource: string;
  editedSource: string;
}

export interface DiagramSaveResult { version: number; cacheSynchronized: boolean }

/** Saves the edited HTML source as the next diagram version through the shared user revision commit. */
export async function saveDiagramHtmlRevision(input: SaveInput): Promise<DiagramSaveResult> {
  validateDiagramHtml(input.editedSource);
  return commitEmbedUserRevision({
    ...input,
    sourceField: 'html_source',
    noun: 'diagram',
    expectedHash: 'source',
  });
}
