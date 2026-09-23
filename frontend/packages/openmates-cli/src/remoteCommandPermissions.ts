/** Strict, reviewable definitions for Project remote-command presets.
 *
 * The repository file only defines presets. Activation grants live in trusted
 * control state outside the command-writable Project and bind a definition
 * digest, so changing this file can never activate or broaden a grant.
 */

import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, openSync, readFileSync, realpathSync } from "node:fs";
import { isAbsolute, join, posix, relative } from "node:path";
import { parseDocument } from "yaml";

export const REMOTE_COMMAND_PERMISSIONS_PATH = ".openmates/permissions.yml";

export type RemoteCommandMode = "foreground" | "background";
export type RemoteCommandSourceAccess = "read_only" | "read_write";

export interface RemoteCommandPolicy {
  argv: string[];
  cwd: string;
  mode: RemoteCommandMode;
  source_access: RemoteCommandSourceAccess;
  deadline_ms: number;
  writable_profiles: string[];
  network_profile: string | null;
  credential_profiles: string[];
}

export interface RemoteCommandPresetDefinition {
  id: string;
  label: string;
  commands: RemoteCommandPolicy[];
}

export interface RemoteWritableProfileDefinition {
  id: string;
  purpose: "cache" | "output";
}

export interface RemoteNetworkProfileDefinition {
  id: string;
  destinations: string[];
}

export interface RemoteCredentialProfileDefinition {
  id: string;
  environment: string[];
}

export interface RemoteCommandPermissions {
  schema_version: 1;
  presets: RemoteCommandPresetDefinition[];
  resource_profiles: {
    writable: RemoteWritableProfileDefinition[];
    network: RemoteNetworkProfileDefinition[];
    credentials: RemoteCredentialProfileDefinition[];
  };
}

export interface ActiveRemoteCommandPresetGrant {
  project_id: string;
  preset_id: string;
  definition_digest: string;
  enabled: true;
}

export class RemoteCommandPermissionsError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RemoteCommandPermissionsError";
  }
}

const MAX_FILE_BYTES = 256 * 1024;
const MAX_ARGV_ITEMS = 128;
const MAX_ARGUMENT_BYTES = 16 * 1024;
const MIN_DEADLINE_MS = 100;
const MAX_DEADLINE_MS = 24 * 60 * 60 * 1000;
const IDENTIFIER = /^[a-z][a-z0-9-]{0,63}$/;
const ENVIRONMENT_NAME = /^[A-Z_][A-Z0-9_]{0,127}$/;

export function loadRemoteCommandPermissions(projectRoot: string): RemoteCommandPermissions | null {
  const root = realpathSync(projectRoot);
  const path = join(root, REMOTE_COMMAND_PERMISSIONS_PATH);
  let descriptor: number;
  try {
    descriptor = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    if ((error as NodeJS.ErrnoException).code === "ELOOP") {
      throw new RemoteCommandPermissionsError(`${REMOTE_COMMAND_PERMISSIONS_PATH} must be a regular file`);
    }
    throw error;
  }
  try {
    const stat = fstatSync(descriptor);
    if (!stat.isFile()) throw new RemoteCommandPermissionsError(`${REMOTE_COMMAND_PERMISSIONS_PATH} must be a regular file`);
    if (stat.size > MAX_FILE_BYTES) throw new RemoteCommandPermissionsError(`${REMOTE_COMMAND_PERMISSIONS_PATH} exceeds ${MAX_FILE_BYTES} bytes`);
    const canonical = realpathSync(path);
    if (!isInside(root, canonical)) throw new RemoteCommandPermissionsError(`${REMOTE_COMMAND_PERMISSIONS_PATH} escapes the Project root`);
    return parseRemoteCommandPermissions(readFileSync(descriptor, "utf8"));
  } finally {
    closeSync(descriptor);
  }
}

export function parseRemoteCommandPermissions(source: string): RemoteCommandPermissions {
  if (Buffer.byteLength(source) > MAX_FILE_BYTES) {
    throw new RemoteCommandPermissionsError(`Permissions definition exceeds ${MAX_FILE_BYTES} bytes`);
  }
  const document = parseDocument(source, { prettyErrors: true, uniqueKeys: true });
  if (document.errors.length > 0) {
    throw new RemoteCommandPermissionsError(`Invalid permissions YAML: ${document.errors[0]?.message ?? "parse error"}`);
  }
  return validateRoot(document.toJS({ maxAliasCount: 0 }));
}

export function remoteCommandPresetDigest(config: RemoteCommandPermissions, presetId: string): string {
  const preset = config.presets.find((candidate) => candidate.id === presetId);
  if (!preset) throw new RemoteCommandPermissionsError(`Unknown command preset: ${presetId}`);
  const writableIds = new Set(preset.commands.flatMap((command) => command.writable_profiles));
  const networkIds = new Set(preset.commands.flatMap((command) => command.network_profile ? [command.network_profile] : []));
  const credentialIds = new Set(preset.commands.flatMap((command) => command.credential_profiles));
  return sha256(stableJson({
    preset,
    resources: {
      writable: config.resource_profiles.writable.filter((profile) => writableIds.has(profile.id)),
      network: config.resource_profiles.network.filter((profile) => networkIds.has(profile.id)),
      credentials: config.resource_profiles.credentials.filter((profile) => credentialIds.has(profile.id)),
    },
  }));
}

export function matchEnabledRemoteCommandPreset(options: {
  config: RemoteCommandPermissions;
  projectId: string;
  policy: RemoteCommandPolicy;
  activeGrants: readonly ActiveRemoteCommandPresetGrant[];
  presetId?: string;
}): { presetId: string; definitionDigest: string } | null {
  for (const preset of options.config.presets) {
    if (options.presetId && preset.id !== options.presetId) continue;
    if (!preset.commands.some((command) => stableJson(command) === stableJson(options.policy))) continue;
    const digest = remoteCommandPresetDigest(options.config, preset.id);
    const active = options.activeGrants.some((grant) =>
      grant.enabled === true
      && grant.project_id === options.projectId
      && grant.preset_id === preset.id
      && grant.definition_digest === digest,
    );
    if (active) return { presetId: preset.id, definitionDigest: digest };
  }
  return null;
}

function validateRoot(value: unknown): RemoteCommandPermissions {
  const root = record(value, "permissions");
  exactKeys(root, ["schema_version", "presets", "resource_profiles"], "permissions");
  if (root.schema_version !== 1) throw new RemoteCommandPermissionsError("schema_version must be 1");
  const resources = root.resource_profiles === undefined
    ? { writable: [], network: [], credentials: [] }
    : validateResources(root.resource_profiles);
  const presets = array(root.presets, "presets").map((item, index) => validatePreset(item, index));
  uniqueIds(presets, "preset");
  validateReferences(presets, resources);
  return { schema_version: 1, presets, resource_profiles: resources };
}

function validateResources(value: unknown): RemoteCommandPermissions["resource_profiles"] {
  const resources = record(value, "resource_profiles");
  exactKeys(resources, ["writable", "network", "credentials"], "resource_profiles");
  const writable = optionalArray(resources.writable, "resource_profiles.writable").map((item, index) => {
    const profile = record(item, `writable[${index}]`);
    exactKeys(profile, ["id", "purpose"], `writable[${index}]`);
    return {
      id: identifier(profile.id, `writable[${index}].id`),
      purpose: oneOf(profile.purpose, ["cache", "output"] as const, `writable[${index}].purpose`),
    };
  });
  const network = optionalArray(resources.network, "resource_profiles.network").map((item, index) => {
    const profile = record(item, `network[${index}]`);
    exactKeys(profile, ["id", "destinations"], `network[${index}]`);
    const destinations = array(profile.destinations, `network[${index}].destinations`).map((destination, destinationIndex) =>
      networkDestination(destination, `network[${index}].destinations[${destinationIndex}]`));
    if (destinations.length === 0) throw new RemoteCommandPermissionsError(`network[${index}].destinations cannot be empty`);
    assertUnique(destinations, `network[${index}].destinations`);
    return { id: identifier(profile.id, `network[${index}].id`), destinations };
  });
  const credentials = optionalArray(resources.credentials, "resource_profiles.credentials").map((item, index) => {
    const profile = record(item, `credentials[${index}]`);
    exactKeys(profile, ["id", "environment"], `credentials[${index}]`);
    const environment = array(profile.environment, `credentials[${index}].environment`).map((name, environmentIndex) => {
      const result = string(name, `credentials[${index}].environment[${environmentIndex}]`);
      if (!ENVIRONMENT_NAME.test(result)) throw new RemoteCommandPermissionsError(`Invalid environment name: ${result}`);
      return result;
    });
    if (environment.length === 0) throw new RemoteCommandPermissionsError(`credentials[${index}].environment cannot be empty`);
    assertUnique(environment, `credentials[${index}].environment`);
    return { id: identifier(profile.id, `credentials[${index}].id`), environment };
  });
  uniqueIds(writable, "writable profile");
  uniqueIds(network, "network profile");
  uniqueIds(credentials, "credential profile");
  return { writable, network, credentials };
}

function validatePreset(value: unknown, index: number): RemoteCommandPresetDefinition {
  const preset = record(value, `presets[${index}]`);
  exactKeys(preset, ["id", "label", "commands"], `presets[${index}]`);
  const commands = array(preset.commands, `presets[${index}].commands`).map((command, commandIndex) =>
    validatePolicy(command, `presets[${index}].commands[${commandIndex}]`));
  if (commands.length === 0) throw new RemoteCommandPermissionsError(`presets[${index}].commands cannot be empty`);
  return {
    id: identifier(preset.id, `presets[${index}].id`),
    label: boundedString(preset.label, `presets[${index}].label`, 1, 120),
    commands,
  };
}

function validatePolicy(value: unknown, context: string): RemoteCommandPolicy {
  const policy = record(value, context);
  exactKeys(policy, [
    "argv", "cwd", "mode", "source_access", "deadline_ms", "writable_profiles", "network_profile", "credential_profiles",
  ], context);
  const argv = array(policy.argv, `${context}.argv`).map((arg, index) => boundedString(arg, `${context}.argv[${index}]`, 1, MAX_ARGUMENT_BYTES));
  if (argv.length === 0 || argv.length > MAX_ARGV_ITEMS) throw new RemoteCommandPermissionsError(`${context}.argv must contain 1-${MAX_ARGV_ITEMS} items`);
  if (argv.some((argument) => argument.includes("\0"))) throw new RemoteCommandPermissionsError(`${context}.argv cannot contain NUL bytes`);
  const mode = policy.mode === undefined ? "foreground" : oneOf(policy.mode, ["foreground", "background"] as const, `${context}.mode`);
  const sourceAccess = policy.source_access === undefined ? "read_only" : oneOf(policy.source_access, ["read_only", "read_write"] as const, `${context}.source_access`);
  if (mode === "background" && sourceAccess !== "read_only") {
    throw new RemoteCommandPermissionsError(`${context}: background commands must use read_only source access`);
  }
  const deadline = policy.deadline_ms === undefined ? 10 * 60 * 1000 : integer(policy.deadline_ms, `${context}.deadline_ms`);
  if (deadline < MIN_DEADLINE_MS || deadline > MAX_DEADLINE_MS) {
    throw new RemoteCommandPermissionsError(`${context}.deadline_ms must be ${MIN_DEADLINE_MS}-${MAX_DEADLINE_MS}`);
  }
  const writableProfiles = optionalArray(policy.writable_profiles, `${context}.writable_profiles`).map((id, index) => identifier(id, `${context}.writable_profiles[${index}]`));
  const credentialProfiles = optionalArray(policy.credential_profiles, `${context}.credential_profiles`).map((id, index) => identifier(id, `${context}.credential_profiles[${index}]`));
  assertUnique(writableProfiles, `${context}.writable_profiles`);
  assertUnique(credentialProfiles, `${context}.credential_profiles`);
  return {
    argv,
    cwd: projectRelativePath(policy.cwd ?? ".", `${context}.cwd`),
    mode,
    source_access: sourceAccess,
    deadline_ms: deadline,
    writable_profiles: writableProfiles,
    network_profile: policy.network_profile === undefined || policy.network_profile === null
      ? null
      : identifier(policy.network_profile, `${context}.network_profile`),
    credential_profiles: credentialProfiles,
  };
}

function validateReferences(
  presets: RemoteCommandPresetDefinition[],
  resources: RemoteCommandPermissions["resource_profiles"],
): void {
  const writable = new Set(resources.writable.map((profile) => profile.id));
  const network = new Set(resources.network.map((profile) => profile.id));
  const credentials = new Set(resources.credentials.map((profile) => profile.id));
  for (const preset of presets) {
    for (const command of preset.commands) {
      for (const id of command.writable_profiles) if (!writable.has(id)) throw new RemoteCommandPermissionsError(`Unknown writable profile: ${id}`);
      if (command.network_profile && !network.has(command.network_profile)) throw new RemoteCommandPermissionsError(`Unknown network profile: ${command.network_profile}`);
      for (const id of command.credential_profiles) if (!credentials.has(id)) throw new RemoteCommandPermissionsError(`Unknown credential profile: ${id}`);
    }
  }
}

function projectRelativePath(value: unknown, context: string): string {
  const path = string(value, context).replaceAll("\\", "/");
  if (path === ".") return path;
  if (!path || path.includes("\0") || isAbsolute(path) || posix.isAbsolute(path)) throw new RemoteCommandPermissionsError(`${context} must be Project-relative`);
  const normalized = posix.normalize(path);
  if (normalized === ".." || normalized.startsWith("../") || normalized !== path.replace(/^\.\//, "")) {
    throw new RemoteCommandPermissionsError(`${context} must be a normalized Project-relative path`);
  }
  return normalized;
}

function networkDestination(value: unknown, context: string): string {
  const destination = string(value, context).toLowerCase();
  if (destination.length > 253 || !/^(?:\[[0-9a-f:]+\]|[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::[1-9][0-9]{0,4})?$/.test(destination)) {
    throw new RemoteCommandPermissionsError(`${context} must be an exact hostname or hostname:port`);
  }
  return destination;
}

function record(value: unknown, context: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new RemoteCommandPermissionsError(`${context} must be a mapping`);
  return value as Record<string, unknown>;
}

function array(value: unknown, context: string): unknown[] {
  if (!Array.isArray(value)) throw new RemoteCommandPermissionsError(`${context} must be a list`);
  return value;
}

function optionalArray(value: unknown, context: string): unknown[] {
  return value === undefined ? [] : array(value, context);
}

function exactKeys(value: Record<string, unknown>, allowed: string[], context: string): void {
  const allowedSet = new Set(allowed);
  const unknown = Object.keys(value).find((key) => !allowedSet.has(key));
  if (unknown) throw new RemoteCommandPermissionsError(`${context} contains unknown key: ${unknown}`);
}

function string(value: unknown, context: string): string {
  if (typeof value !== "string") throw new RemoteCommandPermissionsError(`${context} must be a string`);
  return value;
}

function boundedString(value: unknown, context: string, minimum: number, maximum: number): string {
  const result = string(value, context);
  if (Buffer.byteLength(result) < minimum || Buffer.byteLength(result) > maximum) {
    throw new RemoteCommandPermissionsError(`${context} must be ${minimum}-${maximum} bytes`);
  }
  return result;
}

function identifier(value: unknown, context: string): string {
  const result = string(value, context);
  if (!IDENTIFIER.test(result)) throw new RemoteCommandPermissionsError(`${context} is not a valid identifier`);
  return result;
}

function integer(value: unknown, context: string): number {
  if (!Number.isSafeInteger(value)) throw new RemoteCommandPermissionsError(`${context} must be an integer`);
  return value as number;
}

function oneOf<T extends string>(value: unknown, choices: readonly T[], context: string): T {
  if (!choices.includes(value as T)) throw new RemoteCommandPermissionsError(`${context} must be one of ${choices.join(", ")}`);
  return value as T;
}

function uniqueIds(values: Array<{ id: string }>, context: string): void {
  assertUnique(values.map((value) => value.id), context);
}

function assertUnique(values: string[], context: string): void {
  if (new Set(values).size !== values.length) throw new RemoteCommandPermissionsError(`${context} contains duplicate values`);
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${stableJson(item)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function isInside(root: string, candidate: string): boolean {
  const path = relative(root, candidate);
  return path === "" || (!path.startsWith("..") && !isAbsolute(path));
}
