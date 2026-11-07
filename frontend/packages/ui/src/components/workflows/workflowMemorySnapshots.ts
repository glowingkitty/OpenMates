/**
 * Explicit Memory snapshots for unattended Ask AI steps.
 *
 * A snapshot exists only for a memory the author mentioned (`{{memory.<id>}}`) in that step's
 * instruction. Save and reconnect both go through `syncMemorySnapshots`, which re-reads the canonical
 * memory document client-side, so the server never gains access to any other memory.
 */
import { parseRuleDocument } from '../../utils/ruleDocuments';

export const MEMORY_TOKEN_PATTERN = /\{\{\s*memory\.([A-Za-z0-9_-]{1,128})\s*\}\}/g;
export const MAX_SNAPSHOTS_PER_STEP = 8;

export interface MemorySnapshot {
  title: string;
  body: string;
  revision: string;
  valid_until?: string;
  taken_at: string;
}
export type MemoryAttentionReason = 'deleted' | 'expired';
/** The canonical memory as read by the client; null when it no longer exists. */
export interface MemoryReadResult { document: string; revision: string }
export type MemoryReader = (memoryId: string) => Promise<MemoryReadResult | null>;

export interface AskAiMemoryState {
  memory_snapshots?: Record<string, MemorySnapshot>;
  memory_attention?: Record<string, MemoryAttentionReason>;
}

export function mentionedMemoryIds(prompt: string): string[] {
  return [...new Set([...prompt.matchAll(MEMORY_TOKEN_PATTERN)].map(match => match[1]))].slice(0, MAX_SNAPSHOTS_PER_STEP);
}

function isExpired(validUntil: string | undefined, now: number): boolean {
  return !!validUntil && now > Date.parse(validUntil);
}

/** Snapshot exactly the canonical title, body, revision and expiry; references stay unresolved. */
export function takeSnapshot(read: MemoryReadResult, now: number): MemorySnapshot {
  const fields = parseRuleDocument(read.document);
  return { title: fields.title, body: fields.body, revision: read.revision, taken_at: new Date(now).toISOString(),
    ...(fields.valid_until ? { valid_until: fields.valid_until } : {}) };
}

/**
 * Bring one step's snapshots in line with its instruction and the current memories.
 * Unchanged revisions keep their snapshot; changed ones are re-taken; deleted or expired memories drop
 * their snapshot and mark the step as needing attention. Unmentioned memories are never read.
 */
export async function syncMemorySnapshots(prompt: string, state: AskAiMemoryState, read: MemoryReader, now = Date.now()): Promise<AskAiMemoryState> {
  const snapshots: Record<string, MemorySnapshot> = {};
  const attention: Record<string, MemoryAttentionReason> = {};
  for (const id of mentionedMemoryIds(prompt)) {
    const current = await read(id);
    if (!current) { attention[id] = 'deleted'; continue; }
    const fresh = state.memory_snapshots?.[id]?.revision === current.revision ? state.memory_snapshots[id] : takeSnapshot(current, now);
    if (isExpired(fresh.valid_until, now)) { attention[id] = 'expired'; continue; }
    snapshots[id] = fresh;
  }
  return { ...(Object.keys(snapshots).length ? { memory_snapshots: snapshots } : {}),
    ...(Object.keys(attention).length ? { memory_attention: attention } : {}) };
}

interface GraphNodeLike { config?: Record<string, unknown> }
const isAskAiNode = (node: GraphNodeLike): boolean => node.config?.app_id === 'ai' && node.config?.skill_id === 'ask';

/** Returns the graph with refreshed Ask AI memory state, or null when nothing changed. */
export async function syncGraphMemorySnapshots<T extends { nodes: GraphNodeLike[] }>(graph: T, read: MemoryReader, now = Date.now()): Promise<T | null> {
  let changed = false;
  const nodes: GraphNodeLike[] = [];
  for (const node of graph.nodes) {
    const input = node.config?.input as (Record<string, unknown> & AskAiMemoryState) | undefined;
    if (!isAskAiNode(node) || !input || typeof input.prompt !== 'string' || (!mentionedMemoryIds(input.prompt).length && !input.memory_snapshots && !input.memory_attention)) { nodes.push(node); continue; }
    const next = await syncMemorySnapshots(input.prompt, input, read, now);
    const { memory_snapshots: _s, memory_attention: _a, ...rest } = input;
    if (JSON.stringify({ memory_snapshots: input.memory_snapshots, memory_attention: input.memory_attention }) !== JSON.stringify(next)) changed = true;
    nodes.push({ ...node, config: { ...node.config, input: { ...rest, ...next } } });
  }
  return changed ? { ...graph, nodes } : null;
}

/** Steps that need the author's attention, for the workflow UI. */
export function stepsNeedingMemoryAttention(graph: { nodes: (GraphNodeLike & { id?: string })[] }): Map<string, string[]> {
  const result = new Map<string, string[]>();
  for (const node of graph.nodes) {
    const attention = (node.config?.input as AskAiMemoryState | undefined)?.memory_attention;
    if (isAskAiNode(node) && attention && Object.keys(attention).length && node.id) result.set(node.id, Object.keys(attention));
  }
  return result;
}
