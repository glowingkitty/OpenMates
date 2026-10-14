import { describe, expect, it } from 'vitest';
import { CATEGORY_GRADIENTS, isValidLucideIcon } from '../../../utils/categoryUtils';
import { workflowGraphReady } from '../workflowBuilder';
import { workflowTemplates, workflowTemplateGraph, websiteChangesGraph } from '../workflowTemplates';

describe('workflow browse templates', () => {
  // contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.owned-library-and-templates,workflows.schedule.recurrence
  it('exposes independent V2 graphs with a schedulable message effect', () => {
    expect(workflowTemplates.map((template) => template.id)).toEqual([
      'berlin-ai-events',
      'munich-apartments',
      'morning-weather',
      'weekly-dinner-inspiration',
      'website-changes',
    ]);
    for (const template of workflowTemplates) {
      const graph = workflowTemplateGraph(template.id)!;
      expect(workflowGraphReady(graph, { requireSchedule: true })).toBe(true);
      expect(CATEGORY_GRADIENTS[template.category]).toBeDefined();
      expect(isValidLucideIcon(template.icon)).toBe(true);
      expect(graph.nodes[0].type).toBe('schedule_trigger');
      expect(graph.nodes.at(-1)?.type).toBe('send_chat_message');
      expect(graph.nodes.some(node => node.type === 'app_skill_action')).toBe(true);
      graph.nodes[1].title = 'Edited copy';
      expect(workflowTemplateGraph(template.id)!.nodes[1].title).not.toBe('Edited copy');
    }
  });

  // contract-test: supporting surface=gui.web assertions=workflows.schedule.recurrence,workflows.control.typed-data
  it('keeps Berlin events weekly and Munich listings daily with current search inputs', () => {
    const events = workflowTemplateGraph('berlin-ai-events')!;
    expect(events.nodes[0].config?.schedule).toMatchObject({ type: 'weekly', weekdays: ['monday'], timezone: 'Europe/Berlin' });
    expect(events.nodes[1].config).toMatchObject({ app_id: 'events', skill_id: 'search', input: { requests: [{
      query: 'AI', location: 'Berlin, Germany', event_type: 'PHYSICAL',
      start_date: { $date: 'next_seven_days_start', format: 'datetime' },
      end_date: { $date: 'next_seven_days_end', format: 'datetime' },
    }] } });
    const apartments = workflowTemplateGraph('munich-apartments')!;
    expect(apartments.nodes[0].config?.schedule).toMatchObject({ type: 'daily', timezone: 'Europe/Berlin' });
    expect(apartments.nodes[1].config).toMatchObject({ app_id: 'home', skill_id: 'search', input: { requests: [{
      query: 'Munich', listing_type: 'rent', property_type: 'apartment', sort: 'newest',
    }] } });
    for (const graph of [events, apartments]) {
      expect(graph.nodes.at(-1)?.config?.blocks).toMatchObject([{ source: '$nodes.search.output.results' }]);
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
