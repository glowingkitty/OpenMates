import { describe, expect, it } from 'vitest';
import { splitAssistantActivityRuns } from '../assistantActivityRuns';
const embed = (attrs: Record<string, unknown>) => ({ type: 'paragraph', content: [{ type: 'embed', attrs }] });
describe('mixed assistant activity source positions', () => {
  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary,chats.rendering.assistant-document-convergence
  it('combines adjacent focus, skills and child batches without claiming the focus app was used', () => {
    const nodes = [
      embed({ type: 'focus-mode-activation', id: 'focus', app_id: 'jobs', focus_id: 'jobs-career_insights' }),
      embed({ type: 'app-skill-use-group', id: 'group', groupedItems: [
        { id: 'first', app_id: 'web', skill_id: 'search' }, { id: 'second', app_id: 'web', skill_id: 'read' },
      ] }),
      embed({ type: 'sub-chat-batch', id: 'children', status: 'finished' }),
      { type: 'paragraph', content: [{ type: 'text', text: 'The answer stays here.' }] },
      embed({ type: 'app-skill-use', id: 'code', app_id: 'code', skill_id: 'execute' }),
    ];
    const runs = splitAssistantActivityRuns({ type: 'doc', content: nodes })!;
    expect(runs.map((run) => run.kind)).toEqual(['skills', 'content', 'skills']);
    expect(runs[0].appIds).toEqual(['web']);
    expect(runs[0].skillIds).toEqual(['search', 'read']);
    expect(runs[0].document.content).toEqual(nodes.slice(0, 3));
    expect(runs[1].document.content).toEqual([nodes[3]]);
    expect(runs[2].appIds).toEqual(['code']);
    expect(runs[0].id).toBe('skills:focus');
  });
});
