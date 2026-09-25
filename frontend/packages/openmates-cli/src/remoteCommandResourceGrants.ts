/** Private local activation state for repository-defined remote command resources. */
import { createHash } from "node:crypto";
import { chmodSync, existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, renameSync, statSync, writeFileSync } from "node:fs";
import { isAbsolute, join, relative } from "node:path";

import type { LiveRemoteAccessBinding } from "./remoteAccess.js";
import type { RemoteCommandPermissions, RemoteCommandPolicy } from "./remoteCommandPermissions.js";
import { resolveStateDir } from "./storage.js";

const STORE_FILE = "remote-command-resource-grants.json";
const ID = /^[a-z][a-z0-9-]{0,63}$/;
const ENV = /^[A-Z_][A-Z0-9_]{0,127}$/;

type GrantKind = "writable" | "network" | "credential";

interface StoredGrant {
  project_id: string;
  source_id: string;
  kind: GrantKind;
  profile_id: string;
  definition_digest: string;
  host_path?: string;
  environment_sources?: Record<string, string>;
}

export interface RemoteCommandResourceGrantContext {
  binding: LiveRemoteAccessBinding;
  permissions: RemoteCommandPermissions | null;
  policy: Readonly<RemoteCommandPolicy>;
}

export interface ResolvedRemoteCommandResourceGrants {
  writable_targets: Array<{ profile_id: string; host_path: string }>;
  network_profiles: Array<{ profile_id: string; destinations: string[] }>;
  credential_profiles: Array<{ profile_id: string; environment: Record<string, string> }>;
}

export function listRemoteCommandResourceGrants(projectId?: string, sourceId?: string): Array<Omit<StoredGrant, "environment_sources"> & { environment_names?: string[] }> {
  return readStore()
    .filter((grant) => (!projectId || grant.project_id === projectId) && (!sourceId || grant.source_id === sourceId))
    .map(({ environment_sources, ...grant }) => ({
      ...grant,
      ...(environment_sources ? { environment_names: Object.keys(environment_sources).sort() } : {}),
    }));
}

export function enableRemoteCommandWritableGrant(input: {
  projectId: string; sourceId: string; projectRoot: string; permissions: RemoteCommandPermissions; profileId: string; hostPath: string;
}): void {
  const definition = input.permissions.resource_profiles.writable.find((item) => item.id === input.profileId);
  if (!definition) throw new Error(`Unknown writable profile: ${input.profileId}`);
  if (!isAbsolute(input.hostPath)) throw new Error("--host-path must be absolute");
  const root = realpathSync(input.projectRoot);
  const hostPath = realpathSync(input.hostPath);
  if (!statSync(hostPath).isDirectory()) throw new Error("Writable profile host path must be a directory");
  if (pathsOverlap(hostPath, root)) throw new Error("Writable profile cannot overlap the Project source");
  if (pathsOverlap(hostPath, privateStatePath())) throw new Error("Writable profile cannot overlap OpenMates private state");
  upsert({ project_id: input.projectId, source_id: input.sourceId, kind: "writable", profile_id: definition.id,
    definition_digest: definitionDigest("writable", definition), host_path: hostPath });
}

export function enableRemoteCommandNetworkGrant(input: {
  projectId: string; sourceId: string; permissions: RemoteCommandPermissions; profileId: string;
}): void {
  const definition = input.permissions.resource_profiles.network.find((item) => item.id === input.profileId);
  if (!definition) throw new Error(`Unknown network profile: ${input.profileId}`);
  upsert({ project_id: input.projectId, source_id: input.sourceId, kind: "network", profile_id: definition.id,
    definition_digest: definitionDigest("network", definition) });
}

export function enableRemoteCommandCredentialGrant(input: {
  projectId: string; sourceId: string; permissions: RemoteCommandPermissions; profileId: string; environmentSources: Record<string, string>;
}): void {
  const definition = input.permissions.resource_profiles.credentials.find((item) => item.id === input.profileId);
  if (!definition) throw new Error(`Unknown credential profile: ${input.profileId}`);
  const expected = [...definition.environment].sort();
  const supplied = Object.keys(input.environmentSources).sort();
  if (JSON.stringify(expected) !== JSON.stringify(supplied)) throw new Error(`Credential profile requires mappings for: ${expected.join(", ")}`);
  for (const [target, local] of Object.entries(input.environmentSources)) {
    if (!ENV.test(target) || !ENV.test(local)) throw new Error("Credential environment names must use uppercase shell variable syntax");
  }
  upsert({ project_id: input.projectId, source_id: input.sourceId, kind: "credential", profile_id: definition.id,
    definition_digest: definitionDigest("credential", definition), environment_sources: { ...input.environmentSources } });
}

export function disableRemoteCommandResourceGrant(projectId: string, sourceId: string, kind: GrantKind, profileId: string): void {
  validateIdentity(projectId, sourceId, profileId);
  if (!["writable", "network", "credential"].includes(kind)) throw new Error("Invalid resource grant kind");
  writeStore(readStore().filter((item) => !(item.project_id === projectId && item.source_id === sourceId && item.kind === kind && item.profile_id === profileId)));
}

export function resolveRemoteCommandResourceGrants(context: RemoteCommandResourceGrantContext): ResolvedRemoteCommandResourceGrants {
  const projectId = context.binding.source.projectId;
  if (!projectId || !context.permissions) return empty();
  const sourceId = context.binding.source.sourceId;
  const grants = readStore().filter((item) => item.project_id === projectId && item.source_id === sourceId);
  const writable_targets = context.policy.writable_profiles.flatMap((profileId) => {
    const definition = context.permissions?.resource_profiles.writable.find((item) => item.id === profileId);
    const grant = grants.find((item) => item.kind === "writable" && item.profile_id === profileId);
    return definition && grant?.host_path && safeStoredWritable(context.binding.source.rootPath, grant.host_path)
      && grant.definition_digest === definitionDigest("writable", definition)
      ? [{ profile_id: profileId, host_path: grant.host_path }] : [];
  });
  const network_profiles = context.policy.network_profile ? (() => {
    const definition = context.permissions?.resource_profiles.network.find((item) => item.id === context.policy.network_profile);
    const grant = grants.find((item) => item.kind === "network" && item.profile_id === context.policy.network_profile);
    return definition && grant?.definition_digest === definitionDigest("network", definition)
      ? [{ profile_id: definition.id, destinations: [...definition.destinations] }] : [];
  })() : [];
  const credential_profiles = context.policy.credential_profiles.flatMap((profileId) => {
    const definition = context.permissions?.resource_profiles.credentials.find((item) => item.id === profileId);
    const grant = grants.find((item) => item.kind === "credential" && item.profile_id === profileId);
    if (!definition || !grant?.environment_sources || grant.definition_digest !== definitionDigest("credential", definition)) return [];
    const environment: Record<string, string> = {};
    for (const name of definition.environment) {
      const localName = grant.environment_sources[name];
      const value = localName ? process.env[localName] : undefined;
      if (typeof value !== "string") throw new Error(`Credential environment variable is unavailable: ${localName ?? name}`);
      environment[name] = value;
    }
    return [{ profile_id: profileId, environment }];
  });
  return { writable_targets, network_profiles, credential_profiles };
}

function definitionDigest(kind: GrantKind, definition: unknown): string {
  return createHash("sha256").update(JSON.stringify(["openmates-command-resource-v1", kind, definition])).digest("hex");
}
function upsert(grant: StoredGrant): void {
  validateIdentity(grant.project_id, grant.source_id, grant.profile_id);
  const others = readStore().filter((item) => !(item.project_id === grant.project_id && item.source_id === grant.source_id && item.kind === grant.kind && item.profile_id === grant.profile_id));
  writeStore([...others, grant]);
}
function readStore(): StoredGrant[] {
  const path = join(resolveStateDir(), STORE_FILE);
  if (!existsSync(path)) return [];
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.isSymbolicLink() || (stat.mode & 0o077) !== 0) throw new Error("Remote command resource grant store is not private");
  const parsed = JSON.parse(readFileSync(path, "utf8")) as { grants?: StoredGrant[] };
  if (!Array.isArray(parsed.grants)) throw new Error("Invalid remote command resource grant store");
  return parsed.grants;
}
function writeStore(grants: StoredGrant[]): void {
  const directory = resolveStateDir();
  mkdirSync(directory, { recursive: true, mode: 0o700 }); chmodSync(directory, 0o700);
  const path = join(directory, STORE_FILE);
  if (existsSync(path) && lstatSync(path).isSymbolicLink()) throw new Error("Remote command resource grant store cannot be a symbolic link");
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify({ version: 1, grants }, null, 2)}\n`, { mode: 0o600, flag: "wx" });
  renameSync(temporary, path); chmodSync(path, 0o600);
}
function validateIdentity(projectId: string, sourceId: string, profileId: string): void {
  if (!projectId || projectId.length > 128 || !sourceId || sourceId.length > 128 || !ID.test(profileId)) throw new Error("Invalid remote command resource grant identity");
}
function isInside(parent: string, child: string): boolean { const value = relative(parent, child); return value !== "" && !value.startsWith("..") && !isAbsolute(value); }
function pathsOverlap(left: string, right: string): boolean { return left === right || isInside(left, right) || isInside(right, left); }
function privateStatePath(): string {
  const directory = resolveStateDir();
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  chmodSync(directory, 0o700);
  return realpathSync(directory);
}
function safeStoredWritable(projectRoot: string, hostPath: string): boolean {
  try {
    const root = realpathSync(projectRoot);
    const writable = realpathSync(hostPath);
    return statSync(writable).isDirectory() && !pathsOverlap(root, writable) && !pathsOverlap(privateStatePath(), writable);
  } catch {
    return false;
  }
}
function empty(): ResolvedRemoteCommandResourceGrants { return { writable_targets: [], network_profiles: [], credential_profiles: [] }; }
