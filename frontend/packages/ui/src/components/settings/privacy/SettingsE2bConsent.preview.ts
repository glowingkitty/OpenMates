/**
 * Fictional E2B consent settings fixtures (assertion code-run.e2b.upload-consent).
 * The in-memory read/write keep the preview free of any account or network.
 */
let current: 'allowed' | 'declined' | null = null;
const record = () => ({ decision: current, decidedAt: current ? 1 : null, version: 1 });
const defaults = {
  read: async () => record(),
  write: async (decision: 'allowed' | 'declined') => { current = decision; return record(); },
};
export default defaults;
export const variants = {};
