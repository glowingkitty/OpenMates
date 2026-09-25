const defaultProps = {
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
  onOpenRuns: () => {},
  runsHref: '#runs',
  onUpdateIdentity: async (_title: string, _description: string) => {},
};

export default defaultProps;
export const variants = {
  runs: { ...defaultProps, activeTab: 'runs' as const },
};
