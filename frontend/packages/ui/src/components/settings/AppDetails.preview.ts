import { authStore } from '../../stores/authStore';
import { userProfile } from '../../stores/userProfile';
import { activeTeamContext } from '../../stores/teamStore';
import { webSocketService } from '../../services/websocketService';

export default {appId: 'code', section: 'settings_memories'};

export const variants = { settings: { appId: 'web', section: 'all', presentation: 'settings' }, authenticatedSettings: { appId: 'web', section: 'all', presentation: 'settings' } };

export const ready = (() => {
  if (typeof window === 'undefined' || new URLSearchParams(window.location.search).get('variant') !== 'authenticatedSettings') return;
  const connect = webSocketService.connect;
  webSocketService.connect = () => Promise.resolve();
  window.addEventListener('pagehide', () => { webSocketService.connect = connect; }, { once: true });
  authStore.set({ isAuthenticated: true, isInitialized: true });
  userProfile.update(profile => ({ ...profile, user_id: 'preview-settings-user' }));
  activeTeamContext.set({ team: null, teamId: null, epoch: 0 });
})();
