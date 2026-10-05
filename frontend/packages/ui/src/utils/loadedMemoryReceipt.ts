/** Source-scoped applied context, separate from private-memory permission decisions. */
export interface AppliedMemory {
  id: string; title: string; source: 'app' | 'project'; app_id?: string | null;
  project_id?: string | null; revision: string; body: string;
}
export interface MemoriesLoadedEvent {
  type: 'memories_loaded'; count: number; set_key: string; memories: AppliedMemory[];
}
const digest = /^[a-f0-9]{64}$/;
const text = (value: unknown, max: number): value is string => typeof value === 'string' && !!value.trim() && value.length <= max;
export function parseMemoriesLoadedEvent(value: unknown): MemoriesLoadedEvent | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const event = value as Record<string, unknown>;
  if (event.type !== 'memories_loaded' || typeof event.set_key !== 'string' || !digest.test(event.set_key)
    || !Array.isArray(event.memories) || !event.memories.length || event.memories.length > 24
    || event.count !== event.memories.length) return null;
  const ids = new Set<string>(); let size = 0;
  for (const entry of event.memories) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null;
    const m = entry as Record<string, unknown>;
    if (!text(m.id, 240) || ids.has(m.id) || !text(m.title, 180) || !text(m.body, 20_000)
      || typeof m.revision !== 'string' || !digest.test(m.revision)) return null;
    if (m.source === 'app') {
      if (!text(m.app_id, 64) || !/^[a-z][a-z0-9_]*$/.test(m.app_id)
        || !m.id.startsWith(`app:${m.app_id}:`) || m.project_id != null) return null;
    } else if (m.source === 'project') {
      if (!text(m.project_id, 240) || m.app_id != null) return null;
    } else return null;
    ids.add(m.id); size += m.body.length;
    if (size > 32_000) return null;
  }
  return event as unknown as MemoriesLoadedEvent;
}
