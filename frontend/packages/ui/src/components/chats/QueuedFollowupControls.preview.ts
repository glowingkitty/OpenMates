/**
 * Bare preview fixture for the queued follow-up row controls.
 * No account, chat storage, or AI request is needed.
 * The action event lets the component spec verify both controls.
 * Variants cover active steering, busy state, and a revision error.
 */
const emit = (action: 'edit' | 'steer') => () => {
  window.dispatchEvent(new CustomEvent('queuedFollowupPreviewAction', { detail: { action } }));
};

export default {
  mode: 'follow_up',
  busy: false,
  error: null,
  onEdit: emit('edit'),
  onSteer: emit('steer'),
};

export const variants = {
  steering: { mode: 'steer' },
  updating: { busy: true },
  conflict: { error: 'This queued message changed on another device. Reopen it to edit the latest version.' },
};
