/*
 * Encrypted Project remote-file requester for the production CLI.
 *
 * Purpose: execute bounded list/search/read operations through the opaque bridge.
 * Security: Project-authenticated ephemeral encryption keeps arguments and results
 * private from the API; stable local errors replace ciphertext/raw relay output.
 * Spec: docs/specs/cli-remote-access-cross-device-requester/spec.yml.
 */

import { randomUUID } from "node:crypto";

import type { OpenMatesClient, ProjectSourceRecord, TeamContextOptions } from "./client.js";
import { decryptWithAesGcmCombined, encryptWithAesGcmCombined } from "./crypto.js";
import {
  RemoteAccessReplayGuard,
  createRemoteAccessHandshake,
  deriveRemoteAccessSessionKey,
  openRemoteAccessEnvelope,
  type RemoteAccessCryptoIdentity,
  type RemoteAccessEnvelope,
  type RemoteAccessHandshake,
} from "./remoteAccessCrypto.js";

const REMOTE_PROTOCOL_TIMEOUT_MS = 45_000;
const REMOTE_POLL_INTERVAL_MS = 250;
const MAX_REMOTE_RESULT_BYTES = 200 * 1024;

interface RoutingIdentity {
  context_type: string;
  context_id_hash: string;
  host_member_hash: string;
  host_device_fingerprint_hash: string;
  requester_member_hash: string;
  requester_device_fingerprint_hash: string;
}

export class ProjectRequesterError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "ProjectRequesterError";
    this.code = code;
  }
}

export async function requestProjectRemoteOperation(options: {
  client: OpenMatesClient;
  projectId: string;
  projectKey: Uint8Array;
  source: ProjectSourceRecord;
  operation: "list" | "search" | "read_text";
  arguments: Record<string, unknown>;
  context: TeamContextOptions;
  timeoutMs?: number;
}): Promise<unknown> {
  if (options.source.status !== "connected") {
    throw new ProjectRequesterError("source_offline", "The selected Project source is offline.");
  }
  const timeoutMs = options.timeoutMs ?? REMOTE_PROTOCOL_TIMEOUT_MS;
  let sourceSessionId = stringField(options.source, "source_session_id");
  let keyEpoch = numberField(options.source, "key_epoch");
  let routingIdentity: RoutingIdentity | null = null;

  if (!sourceSessionId || !keyEpoch) {
    const discovery = await discoverRouting(options, timeoutMs);
    sourceSessionId = discovery.sourceSessionId;
    keyEpoch = discovery.keyEpoch;
    routingIdentity = discovery.routingIdentity;
  }

  const requestingClientId = randomUUID();
  const requestId = randomUUID();
  const identity = await buildIdentity(
    options.client,
    options.projectId,
    options.source.source_id,
    sourceSessionId,
    requestingClientId,
    keyEpoch,
    routingIdentity,
  );
  const requester = await createRemoteAccessHandshake(options.projectKey, identity, "requester");
  const encryptedEnvelope = await encryptWithAesGcmCombined(JSON.stringify({
    requesting_client_id: requestingClientId,
    requester_handshake: requester.handshake,
    operation: options.operation,
    arguments: options.arguments,
  }), options.projectKey);
  const created = await options.client.createProjectRemoteAccessRequest(
    options.projectId,
    options.source.source_id,
    {
      request_id: requestId,
      requesting_client_id: requestingClientId,
      operation: options.operation,
      key_epoch: keyEpoch,
      encrypted_envelope: encryptedEnvelope,
    },
    options.context,
  );
  if (created.source_session_id !== sourceSessionId || created.key_epoch !== keyEpoch) {
    throw new ProjectRequesterError("source_session_changed", "The Project source session changed. Retry the request.");
  }
  const result = await pollResult(options.client, options.projectId, options.source.source_id, requestId, requestingClientId, options.context, timeoutMs);
  const payload = parseEncryptedResult(result.encrypted_envelope);
  const sessionKey = await deriveRemoteAccessSessionKey(
    options.projectKey,
    identity,
    "requester",
    requester.privateKey,
    requester.handshake,
    payload.source_handshake,
  );
  const plaintext = await openRemoteAccessEnvelope(
    sessionKey,
    identity,
    requestId,
    "result",
    payload.envelope,
    new RemoteAccessReplayGuard(),
  );
  if (plaintext.byteLength > MAX_REMOTE_RESULT_BYTES) {
    throw new ProjectRequesterError("result_too_large", "The encrypted Project source result exceeded the byte limit.");
  }
  const response = parseJsonObject(new TextDecoder("utf-8", { fatal: true }).decode(plaintext));
  if (response.ok !== true) {
    const code = typeof response.error === "string" ? response.error : "operation_failed";
    throw new ProjectRequesterError(code, remoteErrorMessage(code));
  }
  return response.result;
}

async function discoverRouting(
  options: Parameters<typeof requestProjectRemoteOperation>[0],
  timeoutMs: number,
): Promise<{ sourceSessionId: string; keyEpoch: number; routingIdentity: RoutingIdentity }> {
  const requestId = randomUUID();
  const requestingClientId = randomUUID();
  const nonce = randomUUID();
  const encryptedEnvelope = await encryptWithAesGcmCombined(JSON.stringify({
    type: "routing_discovery",
    requesting_client_id: requestingClientId,
    nonce,
  }), options.projectKey);
  const created = await options.client.createProjectRemoteAccessRequest(
    options.projectId,
    options.source.source_id,
    {
      request_id: requestId,
      requesting_client_id: requestingClientId,
      operation: "list",
      key_epoch: 1,
      encrypted_envelope: encryptedEnvelope,
    },
    options.context,
  );
  const routingIdentity = created.routing_identity as RoutingIdentity | undefined;
  if (!created.source_session_id || !created.key_epoch || routingIdentity?.context_type !== "team") {
    throw new ProjectRequesterError("routing_identity_unavailable", "The Team source routing identity is unavailable.");
  }
  const result = await pollResult(options.client, options.projectId, options.source.source_id, requestId, requestingClientId, options.context, timeoutMs);
  const discoveryText = await decryptWithAesGcmCombined(result.encrypted_envelope, options.projectKey);
  const discovery = discoveryText ? parseJsonObject(discoveryText) : {};
  if (discovery.type !== "routing_discovery_result" || discovery.nonce !== nonce) {
    throw new ProjectRequesterError("routing_identity_invalid", "The Team source routing discovery response was invalid.");
  }
  return { sourceSessionId: created.source_session_id, keyEpoch: created.key_epoch, routingIdentity };
}

async function pollResult(
  client: OpenMatesClient,
  projectId: string,
  sourceId: string,
  requestId: string,
  requestingClientId: string,
  context: TeamContextOptions,
  timeoutMs: number,
): Promise<{ status: string; encrypted_envelope: string }> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      return await client.getProjectRemoteAccessResult(projectId, sourceId, requestId, requestingClientId, context);
    } catch (error) {
      if ((error as Error & { code?: string }).code !== "request_not_found") throw error;
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, REMOTE_POLL_INTERVAL_MS));
  }
  throw new ProjectRequesterError("protocol_timeout", "The Project source did not respond before the protocol timeout.");
}

async function buildIdentity(
  client: OpenMatesClient,
  projectId: string,
  sourceId: string,
  sourceSessionId: string,
  requestingClientId: string,
  keyEpoch: number,
  routing: RoutingIdentity | null,
): Promise<RemoteAccessCryptoIdentity> {
  if (routing) {
    return {
      ownerId: routing.context_id_hash,
      contextType: "team",
      contextId: routing.context_id_hash,
      projectId,
      sourceId,
      sourceSessionId,
      requestingClientId,
      hostMemberId: routing.host_member_hash,
      hostDeviceId: routing.host_device_fingerprint_hash,
      requesterMemberId: routing.requester_member_hash,
      requesterDeviceId: routing.requester_device_fingerprint_hash,
      keyEpoch,
    };
  }
  const user = await client.whoAmI() as Record<string, unknown>;
  const ownerId = typeof user.id === "string" ? user.id : typeof user.user_id === "string" ? user.user_id : null;
  if (!ownerId) throw new ProjectRequesterError("requester_identity_unavailable", "Authenticated requester identity is unavailable.");
  return { ownerId, projectId, sourceId, sourceSessionId, requestingClientId, keyEpoch };
}

function parseEncryptedResult(value: string): { source_handshake: RemoteAccessHandshake; envelope: RemoteAccessEnvelope } {
  const parsed = parseJsonObject(value);
  if (!parsed.source_handshake || !parsed.envelope) {
    throw new ProjectRequesterError("invalid_encrypted_result", "The Project source returned an invalid encrypted result.");
  }
  return parsed as unknown as { source_handshake: RemoteAccessHandshake; envelope: RemoteAccessEnvelope };
}

function parseJsonObject(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
  } catch {
    // Stable caller-facing error below.
  }
  throw new ProjectRequesterError("invalid_remote_payload", "The Project source returned an invalid payload.");
}

function stringField(value: Record<string, unknown>, key: string): string | null {
  return typeof value[key] === "string" && value[key] ? value[key] as string : null;
}

function numberField(value: Record<string, unknown>, key: string): number | null {
  return typeof value[key] === "number" && Number.isInteger(value[key]) ? value[key] as number : null;
}

function remoteErrorMessage(code: string): string {
  const messages: Record<string, string> = {
    protected_path: "The requested path is protected or ignored.",
    unsupported_file: "The requested file is binary or invalid UTF-8.",
    invalid_path: "The requested path is invalid, unavailable, or a symbolic link.",
    search_query_required: "A search query is required.",
    operation_failed: "The Project source operation failed.",
  };
  return messages[code] ?? `The Project source rejected the request (${code}).`;
}
