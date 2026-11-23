/**
 * Project context for a turn whose @Project mention activates the Project only at send time.
 *
 * The private context of such a send is collected before the activation and so sees no Project.
 * After activation the send adds the Project's own Focus catalog, the Focus bodies selected for
 * this request and its reference documents, so a stored Project Focus can layer on this first turn
 * (feature.focus-modes, focus-modes.project-layering). A failed read leaves that field out and is
 * logged; it never blocks the send.
 */
import {
  collectPrivateFocusForRequest,
  collectProjectFocusCatalog,
  collectProjectReferenceDocuments,
} from "./agenticProjectContextService";

export interface ProjectFocusContextPayload {
  project_focus_catalog?: Array<Record<string, unknown>>;
  project_focus_documents?: Array<Record<string, unknown>>;
  project_context_documents?: Array<Record<string, unknown>>;
}

/** Adds the just-activated Project's Focus catalog, selected Focus bodies and reference documents. */
export async function addProjectFocusContextAfterActivation(
  chatId: string,
  text: string,
  payload: ProjectFocusContextPayload,
): Promise<void> {
  const [catalog, focusDocuments, referenceDocuments] = await Promise.allSettled([
    collectProjectFocusCatalog({ chatId }),
    collectPrivateFocusForRequest({ chatId, text }),
    collectProjectReferenceDocuments({ chatId, text }),
  ]);
  if (catalog.status === "fulfilled" && catalog.value.length) {
    payload.project_focus_catalog = catalog.value.slice(0, 20) as unknown as Array<Record<string, unknown>>;
  }
  if (focusDocuments.status === "fulfilled" && focusDocuments.value.length) {
    payload.project_focus_documents = focusDocuments.value.slice(0, 8) as unknown as Array<Record<string, unknown>>;
  }
  if (referenceDocuments.status === "fulfilled" && referenceDocuments.value.length) {
    payload.project_context_documents = referenceDocuments.value.slice(0, 20) as unknown as Array<Record<string, unknown>>;
  }
  const outcomes = [["Focus catalog", catalog], ["Focus documents", focusDocuments],
    ["reference documents", referenceDocuments]] as const;
  for (const [name, result] of outcomes) {
    if (result.status === "rejected") {
      console.warn(`[ChatSyncService:Senders] Project ${name} unavailable after focus activation`, result.reason);
    }
  }
}
