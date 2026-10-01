import { parseDocument, stringify } from 'yaml';
import {
  buildWorkflowFile,
  validateWorkflowFile,
  workflowFileName,
  WORKFLOW_FILE_MAX_BYTES,
  type WorkflowFileDocument,
} from '../../../workflowFile';
import type { WorkflowDetail } from '../stores/workflowWorkspaceStore';

export function isWorkflowFileName(name: string): boolean {
  return name.toLowerCase().endsWith('.workflow.yml');
}

/** Returns null for an ordinary project file, and throws for a malformed workflow file. */
export async function readWorkflowFile(file: File): Promise<WorkflowFileDocument | null> {
  const dedicatedName = isWorkflowFileName(file.name);
  const hasMarker = (content: string) => /^format:\s*['"]?openmates-workflow['"]?\s*(?:#.*)?$/m.test(content);
  if (file.size > WORKFLOW_FILE_MAX_BYTES) {
    if (dedicatedName || hasMarker(await file.slice(0, WORKFLOW_FILE_MAX_BYTES).text())) {
      throw new Error('Workflow file is too large (maximum 1 MB).');
    }
    return null;
  }
  const content = await file.text();
  // A marker may identify an imported workflow even when the filename is generic.
  // Parse once with YAML's alias limit and duplicate-key checks before sending data.
  let value: unknown;
  try {
    const parsed = parseDocument(content, { uniqueKeys: true });
    if (parsed.errors.length) throw parsed.errors[0];
    value = parsed.toJS({ maxAliasCount: 20 });
  } catch (error) {
    if (dedicatedName || hasMarker(content)) throw new Error(`Invalid workflow YAML: ${error instanceof Error ? error.message : String(error)}`);
    return null;
  }
  const marked = !!value && typeof value === 'object' && (value as Record<string, unknown>).format === 'openmates-workflow';
  if (!dedicatedName && !marked) return null;
  return validateWorkflowFile(value);
}

export function downloadWorkflowFile(workflow: WorkflowDetail): void {
  const workflowDocument = buildWorkflowFile(workflow);
  const content = stringify(workflowDocument);
  if (new TextEncoder().encode(content).byteLength > WORKFLOW_FILE_MAX_BYTES) {
    throw new Error('Workflow file is too large (maximum 1 MB).');
  }
  const blob = new Blob([content], { type: 'application/yaml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = workflowFileName(workflow.title);
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
