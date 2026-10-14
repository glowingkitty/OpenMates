/** Canonical public Apps hash routes and legacy Settings path forwarding. */

export type AppsWorkspaceTab = 'overview' | 'focus_modes' | 'settings_memories' | 'embeds' | 'workflows';

export interface AppsWorkspaceRoute {
  appId: string | null;
  /** Canonical URL slug; resolve it against catalog IDs before API dispatch. */
  skillId: string | null;
  /** Remaining focus, memory, content, model or provider detail path. */
  settingsPath: string | null;
  tab: AppsWorkspaceTab;
  showAll: boolean;
  embedId: string | null;
  /** Parent graph used when opening a child from the inline result grid. */
  rootEmbedId: string | null;
}

function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

function canonicalSegment(segment: string): string {
  return decodeSegment(segment).replace(/_/g, '-');
}

function normalizedParts(path: string): string[] {
  const withoutHash = path.replace(/^#\/?/, '').replace(/^\/+/, '');
  const withoutRoot = withoutHash.replace(/^apps(?:\/|$)/, '');
  const parts = withoutRoot.split('/').filter(Boolean).map(decodeSegment);
  if (parts.length === 0) return [];
  if (parts[0] === 'all') return ['all'];

  const [rawApp, second, ...rest] = parts;
  const app = canonicalSegment(rawApp);
  if (!second) return [app];
  if (second === 'skill') {
    const [rawSkill, ...suffix] = rest;
    return rawSkill ? [app, canonicalSegment(rawSkill), ...suffix] : [app];
  }
  if (second === 'settings_memories') return [app, 'memory', ...rest];
  if (['focus', 'memory', 'content', 'entry'].includes(second)) return [app, second, ...rest];
  return [app, canonicalSegment(second), ...rest];
}

function canonicalPath(path: string): string {
  return normalizedParts(path).map(encodeURIComponent).join('/');
}

/** Build a shareable root hash from an Apps path or old `apps/...` Settings path. */
export function buildAppsWorkspaceHash(path = '', tab?: AppsWorkspaceTab, origin?: string): string {
  const normalized = path.replace(/^#\/?/, '');
  const separator = normalized.indexOf('&');
  const pathOnly = separator < 0 ? normalized : normalized.slice(0, separator);
  const query = separator < 0 ? '' : normalized.slice(separator + 1);
  const suffix = canonicalPath(pathOnly);
  const params = new URLSearchParams(query);
  const legacyAll = pathOnly.replace(/^\/?apps\//, '').match(/^all\/(settings_memories|memories|focus_modes|focus-modes|skills)$/);
  if (legacyAll) {
    const filter = legacyAll[1] === 'memories' ? 'settings_memories' : legacyAll[1].replace(/-/g, '_');
    params.set('filter', filter);
  }
  if (tab) params.set('tab', tab);
  if (origin) setOriginParam(params, origin);
  const encodedParams = params.toString();
  return `#apps${suffix ? `/${suffix}` : ''}${encodedParams ? `&${encodedParams}` : ''}`;
}

const originStoragePrefix = 'openmates:apps-origin:';
const sensitiveFragmentParam = /(?:^#|[&?])(?:key|token|auth|access_token|refresh_token|password|code|state)=/i;

function isWorkspaceOrigin(hash: string): boolean {
  if (/[\r\n]/.test(hash) || sensitiveFragmentParam.test(hash) || /&origin(?:-ref)?=/.test(hash)) return false;
  if (/^#\/?settings\/apps(?:\/|&|$)/.test(hash)) return false;
  return /^#\/?(?:apps|workflows|projects|plans|tasks)(?:\/|&|$)/.test(hash)
    || /^#\/?(?:chat-id|chat_id|project-id|task-id|workflow-id|plan-id|new-message)=/.test(hash)
    || /^#\/?settings(?:\/|&|$)/.test(hash);
}

function firstPartyPath(source: string): string | null {
  if (typeof window === 'undefined' || !source || source.startsWith('//')) return null;
  try {
    const url = new URL(source, window.location.origin);
    if (url.origin !== window.location.origin || !/^https?:$/.test(url.protocol)) return null;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch { return null; }
}

function setOriginParam(params: URLSearchParams, source: string): void {
  const path = source.startsWith('#') ? `/${source}` : firstPartyPath(source);
  if (!path) return;
  if (path.startsWith('/#') && isWorkspaceOrigin(path.slice(1))) {
    params.set('origin', path.slice(1));
    return;
  }
  // Root pseudo routes have no useful destination. A non-root first-party page
  // may carry a decryption fragment, which must never be copied into an Apps URL.
  if (path.startsWith('/#')) return;
  if (typeof sessionStorage === 'undefined') return;
  try {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    const token = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    sessionStorage.setItem(`${originStoragePrefix}${token}`, path);
    params.set('origin-ref', token);
  } catch { /* A blocked tab store leaves the normal Apps close fallback. */ }
}

/** Resolve the originating route; opaque path references survive reload in this tab. */
export function readAppsWorkspaceOrigin(hash: string): string | null {
  if (!readAppsWorkspaceRoute(hash)) return null;
  const params = new URLSearchParams(hash.split('&').slice(1).join('&'));
  const origin = params.get('origin');
  if (origin && isWorkspaceOrigin(origin) && origin !== hash) return origin;
  const token = params.get('origin-ref');
  if (!token || !/^[a-f0-9]{32}$/.test(token) || typeof sessionStorage === 'undefined') return null;
  try {
    const path = sessionStorage.getItem(`${originStoragePrefix}${token}`);
    return path && path.startsWith('/') && firstPartyPath(path) === path
      && (!path.startsWith('/#') || isWorkspaceOrigin(path.slice(1))) ? path : null;
  } catch { return null; }
}

/** Keep the first origin while browsing Apps; capture a new one on entry. */
export function withAppsWorkspaceOrigin(target: string, source: string): string {
  const targetRoute = readAppsWorkspaceRoute(target);
  if (!targetRoute) return target;
  if (readAppsWorkspaceOrigin(target)) return target;
  const sourceHash = source.startsWith('/#') ? source.slice(1) : source;
  const sourceRoute = readAppsWorkspaceRoute(sourceHash);
  const origin = sourceRoute ? readAppsWorkspaceOrigin(sourceHash) ?? (targetRoute.appId && !sourceRoute.appId ? sourceHash : null) : source;
  if (!origin || origin === target) return target;
  const params = new URLSearchParams();
  if (sourceRoute) {
    const sourceParams = new URLSearchParams(sourceHash.split('&').slice(1).join('&'));
    if (sourceParams.has('origin-ref') && readAppsWorkspaceOrigin(sourceHash)) {
      params.set('origin-ref', sourceParams.get('origin-ref')!);
    } else setOriginParam(params, origin);
  } else setOriginParam(params, origin);
  return params.toString() ? `${target}&${params}` : target;
}

/** Parse only Apps hashes; all other workspace hashes return null. */
export function readAppsWorkspaceRoute(hash: string): AppsWorkspaceRoute | null {
  if (!/^#\/?apps(?:\/|&|$)/.test(hash)) return null;
  const fragment = hash.replace(/^#\/?/, '');
  const separator = fragment.indexOf('&');
  const path = separator < 0 ? fragment : fragment.slice(0, separator);
  const params = new URLSearchParams(separator < 0 ? '' : fragment.slice(separator + 1));
  const parts = normalizedParts(path);
  const appId = parts[0] && parts[0] !== 'all' ? parts[0] : null;
  const subview = parts[1];
  const isNamedDetail = ['focus', 'memory', 'content', 'entry'].includes(subview);
  const skillId = appId && subview && !isNamedDetail ? subview : null;
  const remainder = appId
    ? isNamedDetail ? parts.slice(1) : parts.slice(2)
    : [];
  const requestedTab = params.get('tab');
  const tab: AppsWorkspaceTab = requestedTab === 'embeds' || requestedTab === 'workflows' || requestedTab === 'focus_modes' || requestedTab === 'settings_memories'
    ? requestedTab : 'overview';
  return {
    appId,
    skillId,
    settingsPath: remainder.length ? remainder.join('/') : null,
    tab,
    showAll: parts[0] === 'all',
    embedId: params.get('embed-id') || null,
    rootEmbedId: params.get('root-id') || null,
  };
}

/** Map a shareable slug back to the exact backend skill ID in the live catalog. */
export function resolveAppsSkillId(slug: string, availableIds: Iterable<string>): string | null {
  for (const id of Array.from(availableIds)) {
    if (id === slug || id.replace(/_/g, '-') === slug) return id;
  }
  return null;
}

/** Resolve app keys such as `social_media` from their public `social-media` slug. */
export function resolveAppsAppId(slug: string, availableIds: Iterable<string>): string | null {
  return resolveAppsSkillId(slug, availableIds);
}
