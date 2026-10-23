export interface AppsRequestContext {
  skill_id?: string;
  input?: Record<string, unknown>;
  embed_id?: string;
  chat_id?: string;
  result?: Record<string, unknown>;
}
/** A selected, existing embed; transport/encryption data stays in the embed store. */
export interface AppsHandoffEmbedReference { embedId: string; type: string; appId?: string; skillId?: string; }
export interface AppsRequestHandoff { text: string; context?: AppsRequestContext; attachments?: File[]; reason?: string; embedReference?: AppsHandoffEmbedReference; }
export const APPS_RESULTS_SAVE_CONTEXT = Symbol('apps-results-save');
export interface AppsResultsSaveContext { readonly state: 'saving' | 'saved' | 'error' | undefined; retry: () => Promise<void>; }
export const APPS_RESULTS_ACTIONS_CONTEXT = Symbol('apps-results-actions');
export interface AppsResultsActionsContext {
  onSubmit: (text: string, attachments: File[], context: AppsRequestContext) => Promise<void | boolean>;
  isSearchSaved?: (context: AppsRequestContext) => boolean;
  onSaveSearch?: (context: AppsRequestContext) => Promise<boolean | void>;
  onCreateWorkflow?: (context: AppsRequestContext) => Promise<void>;
}

