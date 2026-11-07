import { describe, expect, it } from 'vitest';
import { stringify } from 'yaml';
import { templateToDocument, documentToTemplate } from '../workflowMessageTokens';
import { mentionedMemoryIds, syncGraphMemorySnapshots, syncMemorySnapshots, stepsNeedingMemoryAttention } from '../workflowMemorySnapshots';

const doc = (title: string, body: string, valid_until?: string) => `---\n${stringify({ title, ...(valid_until ? { valid_until } : {}) })}---\n${body}\n`;
const NOW = Date.parse('2026-11-07T10:00:00Z');

describe('workflow memory snapshots', () => {
  // contract-test: direct surface=gui.web assertions=app-memories.workflows.explicit-snapshots
  it('reads and snapshots only memories explicitly mentioned', async () => {
    const reads: string[] = [];
    const read = async (id: string) => { reads.push(id); return { document: doc(`T-${id}`, `body ${id}`), revision: 'r1' }; };
    const result = await syncMemorySnapshots('Use {{memory.m1}} please', {}, read, NOW);
    expect(reads).toEqual(['m1']);
    expect(Object.keys(result.memory_snapshots!)).toEqual(['m1']);
    expect(result.memory_snapshots!.m1).toMatchObject({ title: 'T-m1', body: 'body m1', revision: 'r1' });
    expect(mentionedMemoryIds('no mention')).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=app-memories.workflows.explicit-snapshots
  it('re-snapshots on a changed revision and keeps unchanged ones', async () => {
    const first = await syncMemorySnapshots('{{memory.m1}}', {}, async () => ({ document: doc('A', 'one'), revision: 'r1' }), NOW);
    const same = await syncMemorySnapshots('{{memory.m1}}', first, async () => ({ document: doc('A', 'different'), revision: 'r1' }), NOW + 1000);
    expect(same.memory_snapshots!.m1.body).toBe('one');
    const changed = await syncMemorySnapshots('{{memory.m1}}', first, async () => ({ document: doc('A', 'two'), revision: 'r2' }), NOW + 1000);
    expect(changed.memory_snapshots!.m1).toMatchObject({ body: 'two', revision: 'r2' });
  });

  // contract-test: direct surface=gui.web assertions=app-memories.workflows.explicit-snapshots
  it('removes the snapshot and flags the step when the memory is deleted or expired', async () => {
    const graph = { nodes: [{ id: 'ask', config: { app_id: 'ai', skill_id: 'ask', input: { prompt: '{{memory.m1}}', memory_snapshots: { m1: { title: 'A', body: 'x', revision: 'r1', taken_at: 'x' } } } } }] };
    const deleted = await syncGraphMemorySnapshots(graph, async () => null, NOW);
    expect((deleted!.nodes[0].config!.input as Record<string, unknown>).memory_snapshots).toBeUndefined();
    expect(stepsNeedingMemoryAttention(deleted as typeof graph).get('ask')).toEqual(['m1']);
    const expired = await syncMemorySnapshots('{{memory.m1}}', {}, async () => ({ document: doc('A', 'x', '2026-11-01T00:00:00Z'), revision: 'r1' }), NOW);
    expect(expired.memory_attention).toEqual({ m1: 'expired' });
    expect(expired.memory_snapshots).toBeUndefined();
  });

  // contract-test: direct surface=gui.web assertions=app-memories.workflows.explicit-snapshots
  it('renders a memory mention as a titled chip and round-trips the stored syntax', () => {
    const document = templateToDocument('Write in {{memory.m1}} voice', [], { m1: 'Writing style' });
    const chip = document.content![0].content!.find(node => node.type !== 'text')!;
    expect(chip.attrs).toMatchObject({ mentionType: 'workflow_memory', displayName: 'Writing style' });
    expect(documentToTemplate(document)).toBe('Write in {{memory.m1}} voice');
  });
});
