import { authStore } from '../../../stores/authStore';
import { userProfile } from '../../../stores/userProfile';
import { activeTeamContext } from '../../../stores/teamStore';
import { webSocketService } from '../../../services/websocketService';
import {
  installConnectedAccountFixture,
  previewFigma,
  previewGoogleBoth,
  previewGoogleCalendar,
  previewLegacyExpiredGoogle,
  type PreviewConnectedAccount
} from '../connectedAccountPreviewFixture';

export default {};

export const variants = {
  googleCalendarAndFigma: {},
  twoGoogleOneFigma: {},
  empty: {},
  detail: { initialAccountId: 'preview-google-account' }
};

const nowSeconds = () => Math.floor(Date.now() / 1000);

const fixtureAccounts: Record<string, () => PreviewConnectedAccount[]> = {
  googleCalendarAndFigma: () => [previewGoogleCalendar('Google Calendar'), previewFigma],
  twoGoogleOneFigma: () => [previewGoogleBoth('test.user@example.org', nowSeconds() - 3600), previewLegacyExpiredGoogle, previewFigma],
  empty: () => [],
  detail: () => [previewGoogleBoth('test.user@example.org', nowSeconds() - 3600), previewFigma]
};

export const ready = (async () => {
  if (typeof window === 'undefined') return;
  const variant = new URLSearchParams(window.location.search).get('variant') ?? 'googleCalendarAndFigma';
  // The preview has no backend: keep the authenticated state from opening a socket.
  const connect = webSocketService.connect;
  webSocketService.connect = () => Promise.resolve();
  window.addEventListener('pagehide', () => { webSocketService.connect = connect; }, { once: true });
  authStore.set({ isAuthenticated: true, isInitialized: true });
  userProfile.update(profile => ({ ...profile, user_id: 'preview-settings-user' }));
  activeTeamContext.set({ team: null, teamId: null, epoch: 0 });
  await installConnectedAccountFixture((fixtureAccounts[variant] ?? fixtureAccounts.googleCalendarAndFigma)());
})();
