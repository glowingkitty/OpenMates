import { DirectChatError } from '../../services/directChatService';

/** Default: ready to open a two-person Team conversation. */
export default { onMessage: async () => {} };

export const variants = {
  pending: { onMessage: async () => { throw new DirectChatError('pending', 'Recipient has not enrolled'); } },
  unavailable: { onMessage: async () => { throw new DirectChatError('unavailable', 'Network unavailable'); } },
  loading: { onMessage: () => new Promise<void>(() => {}) },
};
