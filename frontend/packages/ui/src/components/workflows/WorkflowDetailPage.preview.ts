// Preview states for the workflow detail header:
// /dev/preview/workflows/WorkflowDetailPage?chrome=0[&variant=runs|blank|provisional|previewOnly|draft]
const defaultProps = {
  state: 'saved' as const,
  title: 'Weekly AI events',
  description: 'Find useful AI events every week.',
  category: 'technology',
  icon: 'calendar-days',
  createdAt: Date.now() / 1000 - 3600,
  nextRunAt: Date.now() / 1000 + 86400,
  enabled: true,
  canEnable: true,
  canRun: true,
  activeTab: 'template' as const,
  saving: false,
  onTabChange: (_tab: 'template' | 'runs') => {},
  onToggleEnabled: () => {},
  onRunWorkflow: () => {},
  onDeleteWorkflow: () => {},
  onOpenHome: () => {},
  onOpenShare: () => {},
  onExport: () => window.dispatchEvent(new CustomEvent('workflow-preview-export')),
  onOpenRuns: () => {},
  runsHref: '#runs',
  onUpdateIdentity: async (_title: string, _description: string) => {},
  onDraftIdentity: (_title: string, _description: string) => {},
};

export default defaultProps;
export const variants = {
  runs: { ...defaultProps, activeTab: 'runs' as const },
  blank: { ...defaultProps, canRun: false, enabled: false },
  provisional: {
    state: 'provisional' as const,
    title: 'Processing…', description: '', category: 'technology', icon: 'calendar-days',
    onOpenHome: () => window.dispatchEvent(new CustomEvent('workflow-preview-close')),
  },
  previewOnly: {
    state: 'provisional' as const,
    title: 'Daily planning reminder', description: 'A morning message to choose your priorities for the day',
    category: 'technology', icon: 'calendar-days',
    onOpenHome: () => window.dispatchEvent(new CustomEvent('workflow-preview-close')),
  },
  draft: {
    state: 'draft' as const,
    title: 'Weekly AI events', description: 'Find useful AI events every week.', category: 'technology', icon: 'calendar-days',
    saving: false, canSave: true,
    onDraftIdentity: (title: string, description: string) =>
      window.dispatchEvent(new CustomEvent('workflow-preview-draft-identity', { detail: { title, description } })),
    onSaveDraft: () => { window.dispatchEvent(new CustomEvent('workflow-preview-save-draft')); },
    onOpenHome: () => window.dispatchEvent(new CustomEvent('workflow-preview-close')),
  },
};
