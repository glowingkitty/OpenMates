/** Structural fields are capabilities/identities, never text for PII detection. */
const opaqueFields = new Set([
  'id', 'appid', 'skillid', 'embedid', 'chatid', 'requestid', 'parentembedid', 'embedids',
  'uploadid', 'uploadref', 'assetref', 's3key', 's3baseurl', 'aeskey', 'aesnonce',
  'vaultwrappedaeskey', 'vaultkeyid', 'apikey', 'key', 'token', 'accesstoken',
  'refreshtoken', 'authorization', 'credential', 'credentials', 'signedurl', 'presignedurl',
  'contenthash', 'expectedbase', 'proposalcommitment',
]);
const mappingFields = new Set(['piimapping', 'piimappings', 'encryptedpiimappings', 'restorationmappings', 'embedpii']);
const normalized = (key: string): string => key.split('_').join('').toLowerCase();
export function isAppsRequestMappingField(key: string): boolean { return mappingFields.has(normalized(key)); }
export function isAppsRequestOpaqueField(key: string): boolean {
  const name = normalized(key);
  return opaqueFields.has(name) || name.startsWith('encrypted');
}

/** Signed transport URLs are capabilities even when stored under a generic url/link field. */
export function isAppsRequestOpaqueValue(value: unknown): boolean {
  if (typeof value !== 'string') return false;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && Array.from(url.searchParams.keys()).some(key =>
      ['x-amz-signature', 'x-goog-signature', 'signature', 'sig', 'token'].includes(key.toLowerCase()));
  } catch { return false; }
}

/** Copy JSON content while visiting free text only; mapping blobs never leave the client. */
export function mapAppsRequestText<T>(value: T, transform: (text: string) => string): T {
  const visit = (item: unknown): unknown => {
    if (typeof item === 'string') return isAppsRequestOpaqueValue(item) ? item : transform(item);
    if (Array.isArray(item)) return item.map(visit);
    if (item && typeof item === 'object') return Object.fromEntries(Object.entries(item)
      .filter(([key]) => !isAppsRequestMappingField(key))
      .map(([key, child]) => [key, isAppsRequestOpaqueField(key) ? child : visit(child)]));
    return item;
  };
  return visit(value) as T;
}
