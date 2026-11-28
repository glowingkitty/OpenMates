import { authStore } from '../../stores/authStore';
import { userProfile } from '../../stores/userProfile';
import { activeTeamContext } from '../../stores/teamStore';
import { webSocketService } from '../../services/websocketService';
import { installConnectedAccountFixture, previewGoogleCalendar, previewGmail, previewFigma, type PreviewConnectedAccount } from './connectedAccountPreviewFixture';

export default {appId: 'code', section: 'settings_memories'};

const mail = { appId: 'mail', section: 'all', presentation: 'settings' };
const design = { appId: 'design', section: 'all', presentation: 'settings' };
const calendar = { appId: 'calendar', section: 'all', presentation: 'settings' };
export const variants = {
  settings: { appId: 'web', section: 'all', presentation: 'settings' },
  authenticatedSettings: { appId: 'web', section: 'all', presentation: 'settings' },
  calendarNotConnected: calendar,
  calendarConnectedGenericLabel: calendar,
  calendarConnectedEmailLabel: calendar,
  calendarNeedsReconnect: calendar,
  designNotConnected: design,
  designConnected: design,
  mailNotConnected: mail,
  mailConnectedEmailLabel: mail
};

const fixtureAccounts: Record<string, PreviewConnectedAccount[]> = {
  calendarNotConnected: [],
  calendarConnectedGenericLabel: [previewGoogleCalendar('Google Calendar')],
  calendarConnectedEmailLabel: [previewGoogleCalendar('test.user@example.org')],
  calendarNeedsReconnect: [{ ...previewGoogleCalendar('test.user@example.org'), connectorStatus: 'reconnect_required' }],
  designNotConnected: [],
  designConnected: [previewFigma],
  mailNotConnected: [],
  mailConnectedEmailLabel: [previewGmail('test.user@example.org')]
};

export const ready = (async () => {
  if (typeof window === 'undefined') return;
  const variant = new URLSearchParams(window.location.search).get('variant') ?? '';
  if (variant !== 'authenticatedSettings' && !(variant in fixtureAccounts)) return;
  const connect = webSocketService.connect;
  webSocketService.connect = () => Promise.resolve();
  window.addEventListener('pagehide', () => { webSocketService.connect = connect; }, { once: true });
  authStore.set({ isAuthenticated: true, isInitialized: true });
  userProfile.update(profile => ({ ...profile, user_id: 'preview-settings-user' }));
  activeTeamContext.set({ team: null, teamId: null, epoch: 0 });
  if (variant in fixtureAccounts) await installConnectedAccountFixture(fixtureAccounts[variant]);
})();
