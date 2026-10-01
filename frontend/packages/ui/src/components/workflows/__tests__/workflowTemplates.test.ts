import { describe, expect, it } from 'vitest';
import { workflowGraphReady } from '../workflowBuilder';
import { workflowTemplates, workflowTemplateGraph } from '../workflowTemplates';

describe('workflow browse templates', () => {
  // contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.owned-library-and-templates,workflows.schedule.recurrence
  it('exposes independent V2 graphs with a schedulable message effect', () => {
    expect(workflowTemplates.map((template) => template.id)).toEqual([
      'daily-planning-reminder',
      'weekly-review-reminder',
    ]);
    for (const template of workflowTemplates) {
      const graph = workflowTemplateGraph(template.id)!;
      expect(workflowGraphReady(graph, { requireSchedule: true })).toBe(true);
      expect(graph.nodes.map((node) => node.type)).toEqual(['schedule_trigger', 'send_chat_message']);
      graph.nodes[1].title = 'Edited copy';
      expect(workflowTemplateGraph(template.id)!.nodes[1].title).not.toBe('Edited copy');
    }
  });
});
