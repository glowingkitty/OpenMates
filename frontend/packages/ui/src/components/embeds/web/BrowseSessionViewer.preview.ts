import type { BrowseClient, BrowseSession } from '../../../services/webBrowseService';

function fixture(status: BrowseSession['status'] = 'ai', needsConsent = false) {
  const session: BrowseSession = {
    session_id: '11111111-1111-4111-8111-111111111111', chat_id: '22222222-2222-4222-8222-222222222222',
    status, task: 'Read the public example page', url: 'https://example.com/', sign_in_notice: '', sign_in_origins: [],
    max_credits: 100, accrued_credits: 8, charged_credits: 8, accounting_pending: false, expires_at: 1793200000,
  };
  let consent = !needsConsent;
  const client: BrowseClient = {
    async state() { return { ...session }; },
    async frame() {
      // A local synthetic document is sufficient for component geometry proof;
      // route-level tests separately prove authenticated JPEG transport.
      return new Blob(['<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800"><rect width="1280" height="800" fill="#f8fafc"/><text x="70" y="120" fill="#111827" font-size="48">Example Domain</text><text x="70" y="190" fill="#111827" font-size="28">Public browsing fixture</text></svg>'], { type: 'image/svg+xml' });
    },
    async control(_id, command) {
      if (command.operation === 'input' && command.action) {
        document.documentElement.dataset.browseInputKind = command.action.kind;
        if (command.action.kind === 'click') document.documentElement.dataset.browseCoordinates = JSON.stringify([command.action.x, command.action.y]);
      }
      if (command.operation === 'input' && !consent) return { ...session, needs_sign_in_consent: true, sign_in_origin: 'https://example.com' };
      if (command.operation === 'sign_in') consent = true;
      if (command.operation === 'take_control') session.status = 'user';
      if (command.operation === 'resume') session.status = 'ai';
      if (command.operation === 'stop') session.status = 'paused';
      if (command.operation === 'close') session.status = 'closed';
      return { ...session };
    },
  };
  return { sessionId: session.session_id, client, onContinue: async (next: BrowseSession) => {
    document.documentElement.dataset.browseContinued = next.session_id;
  } };
}
export default fixture();
export const variants = { manual: fixture('user'), signIn: fixture('user', true), paused: fixture('paused'), mobile: fixture(), expired: fixture('expired') };
