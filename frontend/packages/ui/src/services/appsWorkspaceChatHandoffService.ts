import { get, readonly, writable } from 'svelte/store';
import { authStore } from '../stores/authState';
import { userProfile } from '../stores/userProfile';
import { activeTeamContext } from '../stores/teamStore';
// Root startup needs identity only; the full facade imports the chat sync graph.
import { getAnonymousClientId } from './anonymousChatIdentity';
import type { AppsRequestHandoff } from './appsWorkspaceRequestService';

/** Bounded, payload-free lifecycle evidence for failed browser handoffs. */
type AppsHandoffPhase = 'identity-fenced' | 'queued' | 'navigation-taken' | 'delivered' | 'delivery-stale'
  | 'editor-claimed' | 'document-set' | 'send-started' | 'send-finished' | 'editor-owner-changed'
  | 'editor-error' | 'surface-stale' | 'surface-ready' | 'surface-prepared' | 'prepared-surface-stale' | 'surface-error';
export function recordAppsWorkspaceHandoffPhase(phase: AppsHandoffPhase): void {
  if (typeof window === 'undefined') return;
  const diagnosticWindow = window as Window & { __openmatesAppsHandoffDebug?: string[] };
  diagnosticWindow.__openmatesAppsHandoffDebug = [
    ...(diagnosticWindow.__openmatesAppsHandoffDebug ?? []), phase,
  ].slice(-24);
}

export const APPS_WORKSPACE_CHAT_HANDOFF_EVENT = 'appsWorkspaceChatHandoff';
export const APPS_WORKSPACE_WORKFLOW_HANDOFF_EVENT = 'appsWorkspaceWorkflowHandoff';
let pending: AppsRequestHandoff | null = null;
let pendingWorkflow: AppsRequestHandoff | null = null;
let generation = 0;
const owners = new WeakMap<AppsRequestHandoff, { generation: number; anonymousId: string | null }>();
interface ComposerDelivery { request: AppsRequestHandoff; chatId: string | null; }
const delivery = writable<ComposerDelivery | null>(null);
export const appsWorkspaceComposerHandoff = readonly(delivery);
let ignoredDraftUrls: { request: AppsRequestHandoff; chatId: string; document: string; urls: ReadonlySet<string> } | null = null;
/** Exact normal-detector matches from literal result data, except URLs the user requested. */
export function appsWorkspaceContextOnlyUrls(request: AppsRequestHandoff,
  detect: (text: string) => Array<{ url: string }>): ReadonlySet<string> {
  const explicit = new Set(detect(request.text).map(({ url }) => url));
  return new Set(detect(appsRequestContextText(request)).map(({ url }) => url).filter(url => !explicit.has(url)));
}
/** Keep rejection recovery in memory, fenced to this exact owner, destination and document. */
export function rememberAppsWorkspaceDraftUrls(request: AppsRequestHandoff, chatId: string,
  document: string, urls: ReadonlySet<string>): void {
  if (isAppsWorkspaceHandoffCurrent(request)) ignoredDraftUrls = { request, chatId, document, urls: new Set(urls) };
}
export function restoredAppsWorkspaceDraftUrls(chatId: string | undefined, document: string): ReadonlySet<string> {
  const draft = ignoredDraftUrls;
  return draft && draft.chatId === chatId && draft.document === document && isAppsWorkspaceHandoffCurrent(draft.request)
    ? new Set(draft.urls) : new Set<string>();
}
/** Acceptance may finish after a newer handoff in the same chat replaced this record. */
export function captureAppsWorkspaceDraftUrlCleanup(chatId: string | undefined, document: string): () => void {
  const captured = ignoredDraftUrls;
  const matches = captured?.chatId === chatId && captured?.document === document;
  return () => { if (matches && ignoredDraftUrls === captured) ignoredDraftUrls = null; };
}
export function forgetAppsWorkspaceDraftUrls(owner: AppsRequestHandoff | string | undefined): void {
  if (ignoredDraftUrls && (ignoredDraftUrls.request === owner || ignoredDraftUrls.chatId === owner)) ignoredDraftUrls = null;
}
function fence(): void { ignoredDraftUrls = null; recordAppsWorkspaceHandoffPhase('identity-fenced'); generation++; pending = null; pendingWorkflow = null; delivery.set(null); }
let lastAuth = get(authStore).isAuthenticated;
let lastUser = get(userProfile).user_id;
let lastTeam = get(activeTeamContext);
authStore.subscribe(state => { if (lastAuth !== state.isAuthenticated) fence(); lastAuth = state.isAuthenticated; });
userProfile.subscribe(profile => { if (lastUser !== profile.user_id) fence(); lastUser = profile.user_id; });
activeTeamContext.subscribe(team => { if (lastTeam.teamId !== team.teamId || lastTeam.epoch !== team.epoch) fence(); lastTeam = team; });
export function captureAppsWorkspaceHandoffGuard(): () => boolean {
  const expected = generation;
  const anonymousId = get(authStore).isAuthenticated ? null : getAnonymousClientId();
  return () => expected === generation && (anonymousId === null || anonymousId === getAnonymousClientId());
}
function own(request: AppsRequestHandoff): AppsRequestHandoff {
  owners.set(request, { generation, anonymousId: get(authStore).isAuthenticated ? null : getAnonymousClientId() });
  return request;
}
export function isAppsWorkspaceHandoffCurrent(request: AppsRequestHandoff): boolean {
  const owner = owners.get(request);
  return !!owner && owner.generation === generation && (owner.anonymousId === null || owner.anonymousId === getAnonymousClientId());
}
/** Private result context and File objects stay in memory and never enter URLs. */
export async function queueAppsWorkspaceChatHandoff(request: AppsRequestHandoff): Promise<void> {
  recordAppsWorkspaceHandoffPhase('queued'); pending = own(request); window.dispatchEvent(new Event(APPS_WORKSPACE_CHAT_HANDOFF_EVENT));
}
export function takeAppsWorkspaceChatHandoff(): AppsRequestHandoff | null {
  const request = pending; pending = null;
  if (request) recordAppsWorkspaceHandoffPhase('navigation-taken');
  return request && isAppsWorkspaceHandoffCurrent(request) ? request : null;
}
export async function queueAppsWorkspaceWorkflowHandoff(request: AppsRequestHandoff): Promise<void> {
  pendingWorkflow = own(request); window.dispatchEvent(new Event(APPS_WORKSPACE_WORKFLOW_HANDOFF_EVENT));
}
export function takeAppsWorkspaceWorkflowHandoff(): AppsRequestHandoff | null {
  const request = pendingWorkflow; pendingWorkflow = null;
  return request && isAppsWorkspaceHandoffCurrent(request) ? request : null;
}
export function deliverAppsWorkspaceChatHandoff(request: AppsRequestHandoff, chatId: string | null): void {
  if (isAppsWorkspaceHandoffCurrent(request)) {
    recordAppsWorkspaceHandoffPhase('delivered'); delivery.set({ request, chatId });
  } else recordAppsWorkspaceHandoffPhase('delivery-stale');
}
/** The ready editor claims once, only in the exact chat (or a clean new-chat context). */
export function takeAppsWorkspaceComposerHandoff(chatId: string | undefined, isNewChat: boolean): AppsRequestHandoff | null {
  const value = get(delivery);
  if (!value) return null;
  if (!isAppsWorkspaceHandoffCurrent(value.request)) { delivery.set(null); return null; }
  // A new-chat editor without its temporary ID is still awaiting a keyed
  // remount. Keep the request pending until a stable draft owner can claim it.
  if (value.chatId === null ? !isNewChat || !chatId : value.chatId !== chatId) return null;
  recordAppsWorkspaceHandoffPhase('editor-claimed');
  delivery.set(null); return value.request;
}
/** Auto-send must not acquire editing focus before a first-turn editor remount.
 * A rejected request still opens its exact surviving draft for correction/signup. */
export async function submitAppsWorkspaceHandoffDraft(options: {
  submit: () => Promise<boolean | void>;
  isCurrent: () => boolean;
  focusRejectedDraft: () => void;
}): Promise<void> {
  const accepted = await options.submit();
  if (accepted !== true && options.isCurrent()) options.focusRejectedDraft();
}

const contextSecretFields = new Set(['aeskey', 'aesnonce', 'vaultwrappedaeskey', 'encryptedembedkey', 'encryptedchatkey', 'accesstoken', 'refreshtoken', 'authorization', 'apikey', 'password']);
function contextJson(value: unknown): string {
  return JSON.stringify(value, (key, item) => contextSecretFields.has(key.replace(/_/g, '').toLowerCase()) ? undefined : item);
}

export function appsRequestContextText(request: AppsRequestHandoff): string {
  // Complete context stays available for chat; credentials never enter prose.
  const context = request.context ? contextJson(request.context) : '';
  return context ? `${request.text}\n\nResult context (data supplied by the user):\n${context}` : request.text;
}

/** Match WorkflowInputStartRequest.text's 20,000 character contract without
 * discarding the user's instruction. Authoring needs the selected skill/query
 * and representative results, not an entire retained search embed. Originals
 * remain in the in-memory handoff for identity checks and chat transfer. */
export function appsWorkflowInstruction(request: AppsRequestHandoff): string {
  if (!request.context) return request.text;
  const { skill_id, input, embed_id, chat_id, result } = request.context;
  const compact = (value: unknown, depth = 0): unknown => {
    if (typeof value === 'string') return value.length > 512 ? `${value.slice(0, 512)}…` : value;
    if (value === null || typeof value !== 'object') return value;
    if (depth >= 8) return '[Further result details omitted]';
    if (Array.isArray(value)) return value.slice(0, 5).map(item => compact(item, depth + 1));
    return Object.fromEntries(Object.entries(value).slice(0, 32).map(([key, item]) => [key, compact(item, depth + 1)]));
  };
  // Put the original query/options before result summaries even if the caller's
  // object insertion order differs. This keeps the recurring search actionable.
  const context = contextJson({ skill_id, input, embed_id, chat_id, result: compact(result) });
  const prefix = '\n\nResult context (data supplied by the user):\n';
  const omitted = '\n[Additional result context omitted]';
  const budget = 20_000 - request.text.length - prefix.length;
  if (budget <= omitted.length) return request.text;
  return request.text + prefix + (context.length <= budget ? context : context.slice(0, budget - omitted.length) + omitted);
}

export type { AppsRequestHandoff } from './appsWorkspaceRequestService';

/** TipTap JSON keeps arbitrary supplied context as literal text, including HTML. */
export function appsRequestContextDocument(request: AppsRequestHandoff) {
  return { type: 'doc', content: appsRequestContextText(request).split(/\r?\n/).map(line => ({
    type: 'paragraph', content: line ? [{ type: 'text', text: line }] : [],
  })) };
}
