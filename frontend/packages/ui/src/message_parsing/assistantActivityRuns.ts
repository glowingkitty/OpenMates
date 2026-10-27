// Split assistant activity at its source positions; authored prose and results stay put.
export type AssistantDocument = { type: 'doc'; content: Array<Record<string, unknown>> };
export type AssistantActivityRun = {
  id: string;
  kind: 'content' | 'skills';
  document: AssistantDocument;
  appIds: string[];
  skillIds: string[];
};

export function assistantActivityItems(document: AssistantDocument | undefined): Array<Record<string, unknown>> {
  return (document?.content ?? []).flatMap((node) => activityItems(node) ?? []);
}

function activityItems(node: Record<string, unknown>): Array<Record<string, unknown>> | null {
  if (node.type !== 'paragraph' || !Array.isArray(node.content) || node.content.length !== 1) return null;
  const embed = node.content[0] as Record<string, unknown>;
  if (embed.type !== 'embed') return null;
  const attrs = embed.attrs as Record<string, unknown> | undefined;
  if (attrs?.type === 'app-skill-use' || attrs?.type === 'focus-mode-activation' || attrs?.type === 'sub-chat-batch') return [attrs];
  if (attrs?.type === 'app-skill-use-group' && Array.isArray(attrs.groupedItems)) {
    return attrs.groupedItems as Array<Record<string, unknown>>;
  }
  return null;
}

export function splitAssistantActivityRuns(value: unknown): AssistantActivityRun[] | null {
  if (!value || typeof value !== 'object') return null;
  const doc = value as AssistantDocument;
  if (doc.type !== 'doc' || !Array.isArray(doc.content)) return null;
  const runs: AssistantActivityRun[] = [];
  const runKeys = new Set<string>();
  const seenSkills = new Set<string>();
  let nodes: Array<Record<string, unknown>> = [];
  let currentKind: 'content' | 'skills' | null = null;
  const flush = () => {
    if (!nodes.length || !currentKind) return;
    const document: AssistantDocument = { type: 'doc', content: nodes };
    const items = assistantActivityItems(document);
    const skills = items.filter((item) => item.type !== 'focus-mode-activation' && item.type !== 'sub-chat-batch');
    const baseKey = currentKind === 'skills' ? `skills:${items[0]?.id ?? runs.length}` : `content:${runs.length}`;
    let key = baseKey;
    // Focus and sub-chat anchors can legitimately repeat independently of skills.
    for (let occurrence = 1; runKeys.has(key); occurrence++) key = `${baseKey}:occurrence:${occurrence}`;
    runKeys.add(key);
    runs.push({
      id: key,
      kind: currentKind, document,
      appIds: [...new Set(skills.flatMap((item) => typeof item.app_id === 'string' ? [item.app_id] : []))],
      skillIds: skills.flatMap((item) => typeof item.skill_id === 'string' ? [item.skill_id] : []),
    });
    nodes = [];
  };
  for (const original of doc.content) {
    let node = original;
    const items = activityItems(node);
    if (items) {
      const unique = items.filter((item) => {
        // Identity belongs to the invocation, not its source position. The
        // same long-running call can be echoed as a result-parent reference.
        if (item.type === 'focus-mode-activation' || item.type === 'sub-chat-batch') return true;
        const id = item.id ?? item.contentRef;
        if (typeof id !== 'string' || !id) return true;
        if (seenSkills.has(id)) return false;
        seenSkills.add(id);
        return true;
      });
      if (!unique.length) continue;
      if (unique.length !== items.length) {
        const embed = (node.content as Array<Record<string, unknown>>)[0];
        node = { ...node, content: [{ ...embed, attrs: { ...(embed.attrs as Record<string, unknown>),
          groupedItems: unique, groupCount: unique.length } }] };
      }
    }
    const kind = activityItems(node) ? 'skills' : 'content';
    if (kind !== currentKind) { flush(); currentKind = kind; }
    nodes.push(node);
  }
  flush();
  return runs;
}
