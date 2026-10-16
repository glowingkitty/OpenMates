export default { surface: 'tasks', outcome: 'success' };

export const variants = {
  workflows: { surface: 'workflows', outcome: 'success' },
  editor: { surface: 'editor', outcome: 'success' },
  rejected: { surface: 'tasks', outcome: 'reject' },
  declined: { surface: 'tasks', outcome: 'false' },
  pendingSuccess: { surface: 'tasks', outcome: 'pending-success' },
  pendingFailure: { surface: 'tasks', outcome: 'pending-false' },
};
