import { describe, expect, it } from 'vitest';
import { workflowGraphReady } from '../workflowBuilder';
import { workflowTemplates, workflowTemplateGraph, websiteChangesGraph } from '../workflowTemplates';

describe('workflow browse templates', () => {
  // contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.owned-library-and-templates,workflows.schedule.recurrence
  it('exposes independent V2 graphs with a schedulable message effect', () => {
    expect(workflowTemplates.map((template) => template.id)).toEqual([
      'daily-planning-reminder',
      'weekly-review-reminder',
      'website-changes',
    ]);
    for (const template of workflowTemplates) {
      const graph = workflowTemplateGraph(template.id)!;
      expect(workflowGraphReady(graph, { requireSchedule: true })).toBe(true);
      if (template.id !== 'website-changes') {
        expect(graph.nodes.map((node) => node.type)).toEqual(['schedule_trigger', 'send_chat_message']);
      }
      graph.nodes[1].title = 'Edited copy';
      expect(workflowTemplateGraph(template.id)!.nodes[1].title).not.toBe('Edited copy');
    }
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.website-change.composition,workflows.website-change.diff-inputs
  it('clones the website template and localizes only its editable instructions', () => {
    const original = workflowTemplateGraph('website-changes')!;
    const graph = websiteChangesGraph({ question: 'Localized question {{steps.read.changes}}', summaryPrompt: 'Localized summary {{steps.read.changes}} {{steps.read.source_url}}', messageTitle: 'Localized updates' });
    expect(graph.nodes.map(node => node.type)).toEqual(['schedule_trigger', 'app_skill_action', 'check', 'app_skill_action', 'send_chat_message']);
    expect(graph.nodes.find(node => node.id === 'read')?.config?.input).toEqual({ requests: [{ url: 'https://events.ccc.de/', only_main_content: true, max_age: 0 }] });
    expect(graph.nodes.find(node => node.id === 'check')?.config).toMatchObject({ mode: 'ai', selected_inputs: ['$nodes.read.output.changes'], question: 'Localized question {{steps.read.changes}}' });
    expect(graph.nodes.find(node => node.id === 'summary')?.config?.input).toEqual({ model: 'auto', prompt: 'Localized summary {{steps.read.changes}} {{steps.read.source_url}}' });
    expect(graph.nodes.find(node => node.id === 'message')?.config).toMatchObject({ title: 'Localized updates', message: '{{steps.summary.answer}}\n\n{{steps.read.source_url}}' });
    expect(graph.edges.filter(edge => edge.from === 'check')).toEqual([{ from: 'check', to: 'summary', branch: 'true' }]);
    expect(workflowTemplateGraph('website-changes')).toEqual(original);
  });
});
