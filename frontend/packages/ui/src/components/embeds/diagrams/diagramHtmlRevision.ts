/**
 * Manual diagram edits saved as the next diagram version. Builds with the Rust
 * core (VITE_OPENMATES_RUST_CORE) save a personal chat's edit through the core
 * (`embedContentEdit.ts`), which also writes the chat's "Diagram updated" event;
 * other builds and Team chats keep the atomic, client-encrypted chat revision
 * commit with server revision and source-hash CAS (`embedUserRevision.ts`).
 */
import { commitEmbedUserRevision } from '../../../services/embedUserRevision';
import { EMBED_EDITS_ENABLED } from '../../../services/rustCore/embeds/embedEditSession';
import { chatTeamOf, contentEditScope, saveContentEdit } from '../../../services/rustCore/embeds/embedContentEdit';
import { validateDiagramHtml } from './diagramHtmlContent';

interface SaveInput {
  embedId: string;
  chatId: string;
  current: Record<string, unknown>;
  originalSource: string;
  editedSource: string;
}

export interface DiagramSaveResult { version: number; cacheSynchronized: boolean }

/** Saves the edited HTML source as the next diagram version. Core refusals reject with their `code`. */
export async function saveDiagramHtmlRevision(input: SaveInput): Promise<DiagramSaveResult> {
  validateDiagramHtml(input.editedSource);
  if (EMBED_EDITS_ENABLED) {
    const scope = contentEditScope({ chatId: input.chatId, chatTeamId: await chatTeamOf(input.chatId) });
    if (scope) {
      const base = Number(input.current.version_number) || 1;
      const saved = await saveContentEdit(input.embedId, scope, base, (version) => ({
        ...input.current, html_source: input.editedSource, version_number: version, status: 'finished'
      }));
      return { version: saved.version, cacheSynchronized: true };
    }
  }
  return commitEmbedUserRevision({
    ...input,
    sourceField: 'html_source',
    noun: 'diagram',
    expectedHash: 'source',
  });
}
