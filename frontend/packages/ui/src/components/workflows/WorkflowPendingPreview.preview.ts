import type { WorkflowDetail } from '../../stores/workflowWorkspaceStore';

const workflow = {
  id: 'pending-preview',
  title: 'Weekly school weather brief',
  description: 'Summarize Monday weather before school.',
  enabled: false,
  graph: {
    version: 2,
    trigger_node_id: 'schedule',
    nodes: [
      { id: 'schedule', type: 'schedule_trigger', title: 'Monday at 09:00', config: { schedule: { type: 'weekly', weekdays: ['monday'], time: '09:00', timezone: 'Europe/Berlin' } } },
      { id: 'weather', type: 'app_skill_action', title: 'Get weather', config: { app_id: 'weather', skill_id: 'forecast', input: {} } },
      { id: 'message', type: 'send_chat_message', title: 'Send summary', config: { title: 'Weather', message: 'Weather summary' } },
    ],
    edges: [{ from: 'schedule', to: 'weather' }, { from: 'weather', to: 'message' }],
  },
} as WorkflowDetail;

export default { workflow, mode: 'landing' as const };
export const variants = { editor: { workflow, mode: 'editor' as const } };
