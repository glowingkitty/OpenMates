// frontend/packages/ui/src/message_parsing/assistantActivityRuns.ts
// Split a canonical assistant document into stable prose and adjacent skill runs.
// Each run keeps its first source embed as identity while later calls complete.
// Result previews, links and ordinary text stay in their original positions.
// No private content is logged or synthesized for display.

export type AssistantDocument = { type: 'doc'; content: Array<Record<string, unknown>> };
export type AssistantActivityRun = {
  id: string;
  kind: 'content' | 'skills';
  document: AssistantDocument;
  appIds: string[];
  skillIds: string[];
};

function skillItems(node: Record<string, unknown>): Array<Record<string, unknown>> | null {
  if (node.type !== 'paragraph') return null;
  const children = node.content;
  if (!Array.isArray(children) || children.length !== 1) return null;
  const embed = children[0] as Record<string, unknown>;
  if (embed.type !== 'embed') return null;
  const attrs = embed.attrs as Record<string, unknown> | undefined;
  if (attrs?.type === 'app-skill-use') return [attrs];
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
  let content: Array<Record<string, unknown>> = [];
  let skillNodes: Array<Record<string, unknown>> = [];
  let skillIds: string[] = [];
  let appIds: string[] = [];
  let calledSkillIds: string[] = [];
  const flushContent = () => {
    if (!content.length) return;
    runs.push({ id: `content:${runs.length}`, kind: 'content', document: { type: 'doc', content }, appIds: [], skillIds: [] });
    content = [];
  };
  const flushSkills = () => {
    if (!skillNodes.length) return;
    runs.push({
      id: `skills:${skillIds[0]}`,
      kind: 'skills',
      document: { type: 'doc', content: skillNodes },
      appIds: [...new Set(appIds)],
      skillIds: [...calledSkillIds],
    });
    skillNodes = [];
    skillIds = [];
    appIds = [];
    calledSkillIds = [];
  };
  for (const node of doc.content) {
    const items = skillItems(node);
    if (items) {
      flushContent();
      skillNodes.push(node);
      for (const item of items) {
        if (typeof item.id === 'string') skillIds.push(item.id);
        if (typeof item.app_id === 'string') appIds.push(item.app_id);
        if (typeof item.skill_id === 'string') calledSkillIds.push(item.skill_id);
      }
    } else {
      flushSkills();
      content.push(node);
    }
  }
  flushSkills();
  flushContent();
  return runs;
}
