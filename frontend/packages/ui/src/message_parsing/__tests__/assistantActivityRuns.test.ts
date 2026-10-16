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
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,app-skills.media.visible-assistant-results
  it('shows one activity for repeated invocation refs while preserving distinct calls and results', () => {
    const invocation = embed({ type: 'app-skill-use', id: 'saved-generation', app_id: 'images', skill_id: 'generate' });
    const prose = { type: 'paragraph', content: [{ type: 'text', text: 'The generated result follows.' }] };
    const result = { type: 'embedPreviewLarge', attrs: { embedId: 'generated-child' } };
    const second = { id: 'second-generation', app_id: 'images', skill_id: 'generate' };
    const group = embed({ type: 'app-skill-use-group', id: 'mixed', groupedItems: [
      { id: 'saved-generation', app_id: 'images', skill_id: 'generate' }, second, second,
    ], groupCount: 3 });
    const source = { type: 'doc', content: [invocation, prose, invocation, result, group] };
    const runs = splitAssistantActivityRuns(source)!;
    expect(runs.map(run => run.kind)).toEqual(['skills', 'content', 'skills']);
    expect(runs.filter(run => run.kind === 'skills').map(run => run.skillIds)).toEqual([['generate'], ['generate']]);
    expect(runs[1].document.content).toEqual([prose, result]);
    expect(runs[2].document.content[0]).toMatchObject({ content: [{ attrs: { groupedItems: [second], groupCount: 1 } }] });
    expect((group.content[0].attrs as any).groupCount).toBe(3);
    expect(splitAssistantActivityRuns(source)?.map(run => run.id)).toEqual(runs.map(run => run.id));
  });
});
