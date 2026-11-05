/** Closed transport configuration only. Rust owns all credential admission. */
export interface ProductionBootstrap {
  version: 1; operation: 'bootstrap_existing_key'; artifact: string;
  apiUrl: string; appOrigin: string; sessionId: string; expectedPrincipal: string;
}
export function validProductionBootstrap(value: unknown, actualOrigin: string, artifact: string | null): value is ProductionBootstrap {
  if (!artifact || typeof value !== 'object' || value === null || Object.getPrototypeOf(value) !== Object.prototype) return false;
  const data = value as Record<string, unknown>;
  const names = ['version','operation','artifact','apiUrl','appOrigin','sessionId','expectedPrincipal'];
  if (Reflect.ownKeys(data).length !== names.length || !names.every(name => Object.hasOwn(data,name))
    || Object.values(Object.getOwnPropertyDescriptors(data)).some(field => !('value' in field))
    || data.version !== 1 || data.operation !== 'bootstrap_existing_key' || data.artifact !== artifact
    || !/^[a-f0-9]{64}$/.test(artifact) || data.appOrigin !== actualOrigin
    || typeof data.apiUrl !== 'string' || data.apiUrl.length > 256
    || ![data.sessionId,data.expectedPrincipal].every(id => typeof id === 'string' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(id))) return false;
  try {
    for (const text of [actualOrigin,data.apiUrl]) {
      const url = new URL(text);
      if (url.username || url.password || url.search || url.hash || url.pathname !== '/'
        || ![url.origin,url.origin+'/'].includes(text)
        || !(url.protocol === 'https:' || url.protocol === 'http:' && ['localhost','127.0.0.1'].includes(url.hostname))) return false;
    }
    return true;
  } catch { return false; }
}
