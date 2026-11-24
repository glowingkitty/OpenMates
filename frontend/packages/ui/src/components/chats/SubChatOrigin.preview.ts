const base = {
  parentTitle: 'Plan the product launch',
  work: { kind: 'assumption' as const, label: 'The announcement channel is available' },
  onOpenParent: () => { (window as unknown as { __openedParent?: boolean }).__openedParent = true; },
};

export default base;
export const variants = {
  task: { ...base, work: { kind: 'task' as const, label: 'Review the release checklist' } },
  plain: { ...base, work: null },
};
