const base = { work: { kind: 'assumption' as const, label: 'The announcement channel is available' }, onBack: () => {} };

export default base;
export const variants = {
  task: { ...base, work: { kind: 'task' as const, label: 'Review the release checklist' } },
};
