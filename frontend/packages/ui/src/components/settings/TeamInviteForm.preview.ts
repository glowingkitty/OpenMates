const props = {
  email: 'mira@example.com',
  onAccept: () => window.dispatchEvent(new CustomEvent('team-invite-preview-action', { detail: 'accept' })),
  onDecline: () => window.dispatchEvent(new CustomEvent('team-invite-preview-action', { detail: 'decline' })),
};
export default props;
export const variants = {
  missing: { ...props, status: 'missing-key' },
  pending: { ...props, status: 'pending' },
  joined: { ...props, status: 'joined' },
  error: { ...props, status: 'error', error: 'Use the verified email address this invitation was sent to.' },
};
