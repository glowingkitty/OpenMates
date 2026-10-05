/** Canonical portable saves through the existing authorized Project write executor. */
import { buildWorkflowFile, workflowFileName, type WorkflowFileSource, type WorkflowFileDocument } from './workflowFile';
import { validateProjectFileMutation, type ProjectFileMutation } from './ui/src/utils/projectFileMutationProtocol';

export interface WorkflowRemoteFileBinding {
  project_id: string;
  source_id: string;
  folder_path: string;
  file_path?: string;
  base_hash?: string;
  saved_content?: string;
  workflow_version_id?: string;
}

export interface WorkflowRemoteFileSaveResult {
  status: 'saved' | 'pending' | 'conflict' | 'failed';
  binding: WorkflowRemoteFileBinding;
  error?: string;
}

/** Binding belongs in encrypted Project metadata, including its prior file bytes. */
export async function persistWorkflowRemoteFile(options: {
  workflow: WorkflowFileSource & { current_version_id: string };
  binding: WorkflowRemoteFileBinding;
  expectedVersionId: string;
  operationId: string;
  currentVersion: () => Promise<string>;
  serialize: (document: WorkflowFileDocument) => string;
  execute: (mutation: ProjectFileMutation) => Promise<Record<string, unknown>>;
}): Promise<WorkflowRemoteFileSaveResult> {
  const { binding } = options;
  const folder = relativePath(binding.folder_path, true);
  const path = binding.file_path ?? (folder ? folder + '/' : '') + workflowFileName(options.workflow.title);
  if (relativePath(path, false) !== path || !path.endsWith('.workflow.yml')
    || (path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '') !== folder) throw new Error('workflow_file_path_outside_selected_folder');
  if (options.workflow.current_version_id !== options.expectedVersionId
    || await options.currentVersion() !== options.expectedVersionId) return { status: 'conflict', binding, error: 'workflow_version_changed' };
  const content = options.serialize(buildWorkflowFile(options.workflow));
  let mutation: ProjectFileMutation;
  if (binding.base_hash === undefined) {
    if (binding.saved_content !== undefined) throw new Error('workflow_file_binding_incomplete');
    mutation = { operation: 'create_file', operation_id: options.operationId, path, expected_base: null, content };
  } else {
    if (binding.saved_content === undefined || await hash(binding.saved_content) !== binding.base_hash) throw new Error('workflow_file_binding_hash_mismatch');
    mutation = { operation: 'update_file', operation_id: options.operationId, path,
      expected_base: binding.base_hash, patch: replacementPatch(path, binding.saved_content, content) };
  }
  validateProjectFileMutation(mutation);
  try {
    const result = await options.execute(mutation);
    // The source executor returns the applied operation/path/hash; queued jobs do not.
    const contentHash = await hash(content);
    const applied = result.status === 'completed' || (result.path === path && result.operation === mutation.operation
      && result.operation_id === mutation.operation_id && result.after_hash === contentHash);
    if (!applied) return { status: result.status === 'conflict' ? 'conflict' : result.status === 'failed' ? 'failed' : 'pending', binding,
      error: typeof result.error === 'string' ? result.error : undefined };
    const confirmed = { ...binding, file_path: path, base_hash: contentHash, saved_content: content, workflow_version_id: options.expectedVersionId };
    if (await options.currentVersion() !== options.expectedVersionId) return { status: 'conflict', binding: confirmed, error: 'workflow_version_changed' };
    return { status: 'saved', binding: confirmed };
  } catch (error) {
    const code = typeof (error as { code?: unknown }).code === 'string' ? (error as { code: string }).code : 'workflow_file_write_failed';
    return { status: code.includes('conflict') || ['file_changed', 'file_exists'].includes(code) ? 'conflict' : ['source_offline', 'protocol_timeout'].includes(code) ? 'pending' : 'failed', binding, error: code };
  }
}

function relativePath(value: string, folder: boolean): string {
  if (folder && ['', '.', '/'].includes(value)) return '';
  if (!value || value.length > 2048 || value.startsWith('/') || value.includes('\\')
    || [...value].some(c => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127)
    || value.split('/').some(p => ['', '.', '..'].includes(p))) throw new Error('invalid_workflow_folder');
  return value;
}

async function hash(content: string): Promise<string> {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(content));
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
}

function replacementPatch(path: string, old: string, next: string): string {
  const lines = (value: string) => value ? value.match(/[^\n]*\n|[^\n]+$/g)! : [];
  const rows = (value: string, prefix: string) => lines(value).flatMap(line => line.endsWith('\n')
    ? [prefix + line.slice(0, -1)] : [prefix + line, '\\ No newline at end of file']);
  return [`--- a/${path}`, `+++ b/${path}`, `@@ -${old ? 1 : 0},${lines(old).length} +${next ? 1 : 0},${lines(next).length} @@`,
    ...rows(old, '-'), ...rows(next, '+'), ''].join('\n');
}
