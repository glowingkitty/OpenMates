/** Consume the existing safe notification channel without loading private drafts. */
import { get } from 'svelte/store';
import { authStore } from '../stores/authStore';
import { userProfile } from '../stores/userProfile';
import { notificationStore } from '../stores/notificationStore';
import { text } from '../i18n/translations';
import { getApiEndpoint } from '../config/api';
import { getProject, getProjectContents } from './projectService';

export interface ProjectAuthoringReadyEvent {
  id: string; type: 'project.authoring_ready'; safe_body_key: 'notifications.project_authoring.ready';
  routing: { project_id: string; result_kind: 'focus' | 'workflow'; result_id: string; embed_id?: string; team_id?: string | null; job_id: string };
}
const delivered = new Set<string>();
let started = false;
let stream: EventSource | undefined;
let streamOwner: string | undefined;
let generation = 0;

function currentOwner(): string | undefined {
  return get(authStore).isAuthenticated ? get(userProfile).user_id ?? undefined : undefined;
}
export function projectAuthoringResultHref(event: ProjectAuthoringReadyEvent): string {
  const route = event.routing;
  return route.result_kind === 'workflow'
    ? `/#workflow-id=${encodeURIComponent(route.result_id)}&workflow-tab=details`
    : `/#project-id=${encodeURIComponent(route.project_id)}`;
}
export function handleProjectAuthoringReady(value: unknown, expectedOwner = currentOwner()): void {
  if (!expectedOwner || currentOwner() !== expectedOwner || !value || typeof value !== 'object') return;
  const event = value as ProjectAuthoringReadyEvent;
  const route = event.routing;
  if (event.type !== 'project.authoring_ready' || event.safe_body_key !== 'notifications.project_authoring.ready'
    || typeof event.id !== 'string' || !event.id || !route || typeof route.project_id !== 'string'
    || typeof route.result_id !== 'string' || typeof route.job_id !== 'string'
    || !['focus', 'workflow'].includes(route.result_kind) || delivered.has(event.id)) return;
  delivered.add(event.id);
  if (delivered.size > 100) delivered.delete(delivered.values().next().value!);
  notificationStore.addNotificationWithOptions('success', {
    message: get(text)('notifications.project_authoring.ready'), duration: 12_000,
    dismissible: true, dedupeKey: event.id, actionLabel: get(text)('notifications.project_authoring.view'),
    onAction: () => { void openResult(event, expectedOwner); },
  });
}
async function openResult(event: ProjectAuthoringReadyEvent, expectedOwner: string): Promise<void> {
  try {
    if (currentOwner() !== expectedOwner) return;
    const context = { teamId: event.routing.team_id };
    const project = await getProject(event.routing.project_id, context);
    const contents = await getProjectContents(project, context);
    const route = event.routing;
    const reachable = contents.items.some(item => route.result_kind === 'workflow'
      ? item.item_type === 'workflow' && item.target_id === route.result_id
      : item.project_item_id === route.result_id && (!route.embed_id || item.target_id === route.embed_id));
    if (currentOwner() !== expectedOwner) return;
    if (!reachable) throw new Error('project_authoring_result_unavailable');
    const { setActiveTeamContext } = await import('../stores/teamStore');
    if (route.result_kind === 'focus' && route.team_id) {
      const { listTeams } = await import('./teamService');
      const team = (await listTeams()).find(candidate => candidate.team_id === route.team_id && candidate.status === 'active');
      if (!team) throw new Error('project_authoring_result_unavailable');
      if (currentOwner() !== expectedOwner) return;
      setActiveTeamContext(team);
    } else {
      // Workflow updates reuse the personal-owner engine, including a personal
      // definition linked into a Team Project; its existing detail route is personal.
      if (currentOwner() !== expectedOwner) return;
      setActiveTeamContext(null);
    }
    window.location.assign(projectAuthoringResultHref(event));
  } catch {
    if (currentOwner() === expectedOwner) notificationStore.addNotificationWithOptions('info', {
      message: get(text)('notifications.project_authoring.unavailable'), duration: 7_000, dismissible: true,
    });
  }
}
/** Register once during chat sync initialization; authentication owns stream lifetime. */
export function startProjectAuthoringNotifications(): void {
  if (started || typeof window === 'undefined' || typeof EventSource === 'undefined') return;
  started = true;
  const refresh = () => {
    const owner = currentOwner();
    if (owner === streamOwner) return;
    generation += 1;
    const epoch = generation;
    stream?.close();
    stream = undefined;
    streamOwner = owner;
    delivered.clear();
    if (!owner) return;
    stream = new EventSource(getApiEndpoint('/v1/notifications/stream'), { withCredentials: true });
    stream.addEventListener('notification', (message) => {
      if (generation !== epoch) return;
      try { handleProjectAuthoringReady(JSON.parse((message as MessageEvent).data), owner); } catch { /* Reject malformed events. */ }
    });
    // Recent safe events recover notifications that finished while disconnected.
    const recover = () => { void fetch(getApiEndpoint('/v1/notifications'), { credentials: 'include' }).then(async response => {
      if (!response.ok) return;
      const data = await response.json();
      if (generation !== epoch || !Array.isArray(data.events)) return;
      for (const event of data.events) handleProjectAuthoringReady(event, owner);
    }).catch(() => {}); };
    stream.addEventListener('open', recover);
  };
  authStore.subscribe(refresh);
  userProfile.subscribe(refresh);
}
