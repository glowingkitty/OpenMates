import { authStore } from '../../stores/authStore';
import { userProfile } from '../../stores/userProfile';
import { activeTeamContext } from '../../stores/teamStore';
import type { TeamViewModel } from '../../services/teamService';
import { get } from 'svelte/store';
import { webSocketService } from '../../services/websocketService';

const onNavigate = (hash: string) => window.dispatchEvent(new CustomEvent('apps-preview-navigate', { detail: hash }));
const onSignup = () => window.dispatchEvent(new Event('apps-preview-signup'));
const onSettings = (path: string) => window.dispatchEvent(new CustomEvent('apps-preview-settings', { detail: path }));

export default { hash: '#apps', onNavigate, onSignup, onSettings };
export const layout = 'fill';
export const variants = {
  allApps: { hash: '#apps/all', onNavigate, onSignup, onSettings },
  allFocusApps: { hash: '#apps/all&filter=focus_modes', onNavigate, onSignup, onSettings },
  app: { hash: '#apps/health', onNavigate, onSignup, onSettings },
  appCode: { hash: '#apps/code', onNavigate, onSignup, onSettings },
  appFocus: { hash: '#apps/health&tab=focus_modes', onNavigate, onSignup, onSettings },
  appMemory: { hash: '#apps/books&tab=settings_memories', onNavigate, onSignup, onSettings },
  skill: { hash: '#apps/web/search', onNavigate, onSignup, onSettings },
  teamLibrary: { hash: '#apps/web&tab=workflows', onNavigate, onSignup, onSettings },
};

// The bare preview has no account session. Only this explicit variant supplies
// local store context so the real workspace account-switch effect can be tested.
export const ready = (async () => {
  if (typeof window === 'undefined' || new URLSearchParams(window.location.search).get('variant') !== 'teamLibrary') return;
  // This preview has no real session. The WebSocket singleton normally reacts
  // to authStore and forces a session check when it has no token, which would
  // clear the synthetic account before the library can render.
  const connectWebSocket = webSocketService.connect;
  webSocketService.connect = () => Promise.resolve();
  window.addEventListener('pagehide', () => { webSocketService.connect = connectWebSocket; }, { once: true });
  authStore.set({ isAuthenticated: true, isInitialized: true });
  userProfile.update(profile => ({ ...profile, user_id: 'preview-user' }));
  activeTeamContext.set({ team: null, teamId: null, epoch: 0 });
  // Expose only the fake preview account state so the component test can
  // distinguish a missing fixture from a workspace library invalidation.
  (window as Window & { appsPreviewAccountSnapshot?: () => {
    isAuthenticated: boolean;
    userId: string | null;
    teamId: string | null;
  } }).appsPreviewAccountSnapshot = () => ({
    isAuthenticated: get(authStore).isAuthenticated,
    userId: get(userProfile).user_id ?? null,
    teamId: get(activeTeamContext).teamId,
  });
  const studio: TeamViewModel = {
    team_id: 'preview-studio', name: 'Preview Studio', description: '', role: 'member',
    status: 'active', profileImageMetadata: {}, zeroBalance: 0, createdAt: 0, updatedAt: 0,
    encrypted: {},
  };
  window.addEventListener('apps-preview-set-team', event => {
    const teamId = (event as CustomEvent<string | null>).detail;
    activeTeamContext.update(current => ({
      team: teamId === studio.team_id ? studio : null,
      teamId: teamId === studio.team_id ? studio.team_id : null,
      epoch: current.epoch + 1,
    }));
  });
})();
