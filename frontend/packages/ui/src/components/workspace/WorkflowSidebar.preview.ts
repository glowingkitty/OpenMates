import type { WorkflowSummary } from '../../stores/workflowWorkspaceStore';

const workflows: WorkflowSummary[] = [
  { id: 'weekly-events', title: 'Weekly AI events', icon: 'calendar-days', category: 'business_development', status: 'active', enabled: true, trigger_summary: 'Weekly at 09:00', current_version_id: 'v1' },
  { id: 'drawing-classes', title: 'Berlin Drawing Classes Digest', icon: 'palette', category: 'design', status: 'draft', enabled: false, trigger_summary: 'Weekly at 10:00', current_version_id: 'v1' },
  { id: 'morning-weather', title: 'Morning weather and news', icon: 'cloud-rain', category: 'science', status: 'draft', enabled: false, trigger_summary: 'Daily at 09:00', current_version_id: 'v1' },
];

export default {
  onSelect: (_workflow: WorkflowSummary) => {},
  onClose: () => {},
  previewWorkflows: workflows,
  previewSelectedId: 'weekly-events',
};

export const variants = {
  empty: {
    onSelect: (_workflow: WorkflowSummary) => {},
    onClose: () => {},
    previewWorkflows: [],
    previewSelectedId: null,
  },
};
