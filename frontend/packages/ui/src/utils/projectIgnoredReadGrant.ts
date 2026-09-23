/** Client-signed permission for one exact ignored-file read through the opaque relay.
 * This is created only after explicit user consent, never from tool arguments.
 * It does not authorize private files, writes, directory listings, or searches.
 */
export interface ProjectIgnoredReadScope {
  projectId: string;
  sourceId: string;
  requestId: string;
  chatId: string;
  operationId: string;
  path: string;
}

export interface ProjectIgnoredReadGrant extends ProjectIgnoredReadScope {
  version: 1;
  expiresAt: number;
  signature: string;
}

const GRANT_LIFETIME_MS = 5 * 60 * 1000;
const encoder = new TextEncoder();

function validScope(scope: ProjectIgnoredReadScope): boolean {
  return [scope.projectId, scope.sourceId, scope.requestId, scope.chatId, scope.operationId]
    .every(value => typeof value === "string" && value.length > 0 && value.length <= 128)
    && typeof scope.path === "string" && scope.path.length > 0 && scope.path.length <= 4096
    && !scope.path.includes("\\") && !scope.path.startsWith("/")
    && !/^[a-z]:/i.test(scope.path)
    && !Array.from(scope.path).some(value => value.charCodeAt(0) < 32 || value.charCodeAt(0) === 127)
    && scope.path.split("/").every(part => part && part !== "." && part !== "..");
}

function material(grant: Omit<ProjectIgnoredReadGrant, "signature">): Uint8Array {
  return encoder.encode(JSON.stringify([
    "openmates-ignored-read-v1", grant.projectId, grant.sourceId, grant.requestId,
    grant.chatId, grant.operationId, grant.path, grant.expiresAt,
  ]));
}

async function signingKey(projectKey: Uint8Array): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", new Uint8Array(projectKey).buffer,
    { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

export async function createProjectIgnoredReadGrant(
  projectKey: Uint8Array, scope: ProjectIgnoredReadScope, now = Date.now(),
): Promise<ProjectIgnoredReadGrant> {
  if (!validScope(scope)) throw new Error("invalid_ignored_read_scope");
  const grant = { ...scope, version: 1 as const, expiresAt: now + GRANT_LIFETIME_MS };
  const signature = await crypto.subtle.sign("HMAC", await signingKey(projectKey), material(grant));
  return { ...grant, signature: Array.from(new Uint8Array(signature), byte => byte.toString(16).padStart(2, "0")).join("") };
}

export async function verifyProjectIgnoredReadGrant(
  projectKey: Uint8Array,
  value: unknown,
  expected: ProjectIgnoredReadScope,
  now = Date.now(),
): Promise<boolean> {
  if (!value || typeof value !== "object" || Array.isArray(value) || !validScope(expected)) return false;
  const grant = value as ProjectIgnoredReadGrant;
  if (grant.version !== 1 || !validScope(grant) || !Number.isSafeInteger(grant.expiresAt)
      || grant.expiresAt <= now || grant.expiresAt > now + GRANT_LIFETIME_MS
      || typeof grant.signature !== "string" || !/^[a-f0-9]{64}$/.test(grant.signature)
      || Object.entries(expected).some(([key, expectedValue]) => grant[key as keyof ProjectIgnoredReadScope] !== expectedValue)) return false;
  try {
    return await crypto.subtle.verify("HMAC", await signingKey(projectKey),
      Uint8Array.from(grant.signature.match(/../g)!, hex => parseInt(hex, 16)), material(grant));
  } catch { return false; }
}
