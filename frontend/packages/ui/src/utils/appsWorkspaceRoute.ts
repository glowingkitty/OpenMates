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
export function buildAppsWorkspaceHash(path = '', tab?: AppsWorkspaceTab): string {
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
  const encodedParams = params.toString();
  return `#apps${suffix ? `/${suffix}` : ''}${encodedParams ? `&${encodedParams}` : ''}`;
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
