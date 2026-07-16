/**
 * Settings hash utilities.
 *
 * Keeps settings deep links in the URL fragment so paths stay client-only and
 * are not sent to the server. The helpers intentionally preserve unrelated
 * hash state such as chat and embed identifiers when settings opens or closes.
 */

const SETTINGS_HASH_PREFIX = '#settings';
const SETTINGS_HASH_PARAM = 'settings';

const SETTINGS_PATH_ALIASES: Record<string, string> = {
  'privacy/pii': 'privacy/hide-personal-data',
  'privacy/hide_personal_data': 'privacy/hide-personal-data',
  'privacy/connected_accounts': 'privacy/connected-accounts',
  'billing/referral_code': 'billing/referral-code',
};

type HashParamValue = string | null | undefined;

function stripHashPrefix(hash: string): string {
  if (!hash) return '';
  return hash.startsWith('#/') ? hash.slice(2) : hash.replace(/^#/, '');
}

function encodeHashValue(value: string): string {
  return encodeURIComponent(value)
    .replace(/%2F/g, '/')
    .replace(/%3A/g, ':');
}

function parseHashParams(hash: string): URLSearchParams {
  const fragment = stripHashPrefix(hash);
  if (!fragment || fragment === 'settings' || fragment.startsWith('settings/')) {
    return new URLSearchParams();
  }
  return new URLSearchParams(fragment);
}

function serializeHashParams(params: URLSearchParams): string {
  const pairs: string[] = [];
  params.forEach((value, key) => {
    pairs.push(`${encodeURIComponent(key)}=${encodeHashValue(value)}`);
  });
  return pairs.length > 0 ? `#${pairs.join('&')}` : '';
}

function splitSettingsRouteAndSuffix(path: string): { route: string; suffix: string } {
  const ampIndex = path.indexOf('&');
  if (ampIndex === -1) {
    return { route: path, suffix: '' };
  }
  return {
    route: path.slice(0, ampIndex),
    suffix: path.slice(ampIndex),
  };
}

export function normalizeSettingsPath(rawPath: string): string {
  let path = rawPath.trim();
  if (path.startsWith(SETTINGS_HASH_PREFIX)) {
    path = path.slice(SETTINGS_HASH_PREFIX.length);
  }
  if (path.startsWith('/')) {
    path = path.slice(1);
  }
  if (path === 'settings') {
    return 'main';
  }

  const { route, suffix } = splitSettingsRouteAndSuffix(path);
  const normalizedRoute = SETTINGS_PATH_ALIASES[route] ?? route;
  return normalizedRoute ? `${normalizedRoute}${suffix}` : 'main';
}

export function getSettingsPathFromHash(hash: string): string | null {
  if (!hash || !hash.startsWith('#')) return null;

  const normalizedHash = hash.startsWith('#/') ? `#${hash.slice(2)}` : hash;
  if (normalizedHash === SETTINGS_HASH_PREFIX || normalizedHash.startsWith(`${SETTINGS_HASH_PREFIX}/`)) {
    return normalizeSettingsPath(normalizedHash.slice(SETTINGS_HASH_PREFIX.length));
  }

  const params = parseHashParams(normalizedHash);
  const settingsPath = params.get(SETTINGS_HASH_PARAM);
  return settingsPath ? normalizeSettingsPath(settingsPath) : null;
}

export function buildSettingsHash(settingsPath: string): string {
  const normalizedPath = normalizeSettingsPath(settingsPath);
  return normalizedPath === 'main' ? SETTINGS_HASH_PREFIX : `${SETTINGS_HASH_PREFIX}/${normalizedPath}`;
}

export function updateHashParams(
  hash: string,
  updates: Record<string, HashParamValue>,
): string {
  const params = parseHashParams(hash);
  const existingSettingsPath = getSettingsPathFromHash(hash);
  if (existingSettingsPath) {
    params.set(SETTINGS_HASH_PARAM, existingSettingsPath);
  }

  for (const [key, value] of Object.entries(updates)) {
    if (value === null || value === undefined || value === '') {
      params.delete(key);
    } else {
      params.set(key, value);
    }
  }

  const keys = Array.from(params.keys());
  if (keys.length === 1 && keys[0] === SETTINGS_HASH_PARAM) {
    return buildSettingsHash(params.get(SETTINGS_HASH_PARAM) ?? 'main');
  }

  return serializeHashParams(params);
}

export function setSettingsPathInHash(hash: string, settingsPath: string): string {
  const normalizedPath = normalizeSettingsPath(settingsPath);
  const params = parseHashParams(hash);
  params.delete(SETTINGS_HASH_PARAM);

  if (Array.from(params.keys()).length === 0) {
    return buildSettingsHash(normalizedPath);
  }

  params.set(SETTINGS_HASH_PARAM, normalizedPath);
  return serializeHashParams(params);
}

export function clearSettingsPathFromHash(hash: string): string {
  const params = parseHashParams(hash);
  params.delete(SETTINGS_HASH_PARAM);
  return serializeHashParams(params);
}
