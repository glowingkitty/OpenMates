/**
 * Fictional suspended-account screen with a category-level reason and the two actions.
 * Callbacks are inert; the appeal form opens from the Appeal button.
 * The pending-review default and a temporary variant differ only in the reason text.
 */
const base = {
  message: 'This is strike 3 of 3. Your account is suspended until an admin has reviewed it. You can appeal this decision.',
  flaggedRequests: ['Example flagged request text'],
  onappeal: () => {},
  ondownload: () => {},
};
export default base;
export const variants = {
  temporary: { state: 'temporary', until: '2030-01-08T00:00:00Z', message: 'Your account is suspended until 2030-01-08.' },
  sent: { sent: true },
};
