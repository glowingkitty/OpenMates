// Synthetic recipient UI states. No encryption keys, owner state or API writes.
export default { state: 'loading' };
export const variants = {
  password: { state: 'password' },
  invalidPassword: { state: 'password', invalidPassword: true },
  error: { state: 'error' },
  ready: { state: 'ready' },
};
