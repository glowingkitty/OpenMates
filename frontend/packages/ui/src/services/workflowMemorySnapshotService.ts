/**
 * Client-side bridge between personal memories and Workflow Ask AI snapshots.
 * Reads the canonical personal memory documents; the revision is a content hash because personal
 * memories carry no separate revision counter.
 */
import { listPersonalRuleDocuments } from './ruleDocumentService';
import { parseRuleDocument } from '../utils/ruleDocuments';
import { syncGraphMemorySnapshots, type MemoryReader } from '../components/workflows/workflowMemorySnapshots';
import { workflowWorkspaceStore, type WorkflowGraph } from '../stores/workflowWorkspaceStore';

const PERSONAL_PREFIX = 'personal:';
const toMentionId = (documentId: string): string => documentId.replace(PERSONAL_PREFIX, '');

export interface MentionableMemory { id: string; title: string; /** Unix seconds of the latest save, when the document records it. */ updatedAt?: number }

/**
 * Display order for the mention picker: memories with a save time first (newest first), then the
 * rest in reverse stored order (newest stored first). Pure; does not mutate the input.
 */
export function sortMemoriesByRecency<T extends { updatedAt?: number }>(memories: readonly T[]): T[] {
  const dated = memories.map((memory, index) => ({ memory, index })).filter(entry => typeof entry.memory.updatedAt === 'number');
  const undated = memories.map((memory, index) => ({ memory, index })).filter(entry => typeof entry.memory.updatedAt !== 'number');
  dated.sort((a, b) => (b.memory.updatedAt as number) - (a.memory.updatedAt as number) || b.index - a.index);
  undated.sort((a, b) => b.index - a.index);
  return [...dated, ...undated].map(entry => entry.memory);
}

async function contentRevision(document: string): Promise<string> {
  const bytes = new TextEncoder().encode(document);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].slice(0, 12).map(byte => byte.toString(16).padStart(2, '0')).join('');
}

/** Reader over one consistent read of the personal memory catalog. */
export function createPersonalMemoryReader(): MemoryReader {
  let catalog: Promise<Map<string, string>> | null = null;
  const load = () => catalog ??= listPersonalRuleDocuments().then(documents => new Map(documents.map(item => [toMentionId(item.id), item.document])));
  return async (memoryId) => {
    const document = (await load()).get(memoryId);
    return document === undefined ? null : { document, revision: await contentRevision(document) };
  };
}

/** Personal memories the author can mention; expired ones are excluded. */
export async function listMentionableMemories(now = Date.now()): Promise<MentionableMemory[]> {
  const entries = (await listPersonalRuleDocuments()).flatMap((item): MentionableMemory[] => {
    const fields = parseRuleDocument(item.document);
    if (fields.valid_until && now > Date.parse(fields.valid_until)) return [];
    const updatedAt = typeof fields.updated_at === 'number' ? fields.updated_at : undefined;
    return [{ id: toMentionId(item.id), title: fields.title, ...(updatedAt === undefined ? {} : { updatedAt }) }];
  });
  return sortMemoriesByRecency(entries);
}

/** Save path: snapshot every mentioned memory into the graph before it is persisted to the Vault. */
export async function graphWithMemorySnapshots(graph: WorkflowGraph): Promise<WorkflowGraph> {
  return (await syncGraphMemorySnapshots(graph, createPersonalMemoryReader())) ?? graph;
}

let refreshedGeneration: number | null = null;

/** Once per client connect: refresh snapshots of workflows that carry them, persisting only changes. */
export async function refreshWorkflowMemorySnapshots(): Promise<number> {
  const generation = workflowWorkspaceStore.getGeneration();
  if (refreshedGeneration === generation) return 0;
  refreshedGeneration = generation;
  const reader = createPersonalMemoryReader();
  let persisted = 0;
  for (const summary of await workflowWorkspaceStore.loadWorkflows()) {
    const detail = await workflowWorkspaceStore.selectWorkflow(summary.id);
    const refreshed = await syncGraphMemorySnapshots(detail.graph, reader);
    if (!refreshed) continue;
    await workflowWorkspaceStore.patchWorkflow(detail.id, { graph: refreshed, version: detail.version });
    persisted += 1;
  }
  return persisted;
}
