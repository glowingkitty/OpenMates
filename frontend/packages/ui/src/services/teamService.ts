// frontend/packages/ui/src/services/teamService.ts
// Browser Teams V1 service for first-party web sessions. It mirrors the CLI
// encrypted team payload contract: a random team AES key encrypts team metadata,
// then the user's master key wraps that team key for the current membership.
// Backend routes remain first-party/session-authenticated and reject cleartext
// in encrypted fields. Spec: docs/specs/teams-v1/spec.yml

import { getApiEndpoint, getUploadEndpoint } from "../config/api";
import { prepareFileForUpload } from "./uploadPrivacy";
import { get } from "svelte/store";
import { userProfile } from "../stores/userProfile";
import { WorkspaceQueryCache, getWorkspaceCacheIdentity } from "./workspaceQueryCache";
import { getWorkspaceCacheEpoch, registerWorkspaceCacheClear } from "./workspaceCacheLifecycle";
import { getActiveTeamContextSnapshot, setActiveTeamContext, TEAMS_UPDATED_EVENT } from "../stores/teamStore";
import { matesMetadata } from "../data/matesMetadata";
import {
  decryptChatKeyWithMasterKey,
  decryptWithEmbedKey,
  encryptChatKeyWithMasterKey,
  encryptWithEmbedKey,
  generateEmbedKey,
  unwrapEmbedKeyWithEmbedKey,
  wrapEmbedKeyWithChatKey,
} from "./cryptoService";

export type TeamRole = "owner" | "admin" | "member" | "viewer";
export type InviteRole = Exclude<TeamRole, "owner">;

export interface TeamRecord {
  team_id?: string;
  slug?: string | null;
  encrypted_name?: string;
  encrypted_description?: string | null;
  encrypted_profile_image_metadata?: string | null;
  encrypted_team_key?: string | null;
  encrypted_zero_balance?: string | null;
  role?: TeamRole;
  status?: string;
  created_at?: number;
  updated_at?: number;
  security_policy?: TeamSecurityPolicy;
  encrypted_member_profile?: string;
}

export interface TeamSecurityPolicy {
  restrict_email_domains: boolean;
  allowed_email_domains: string[];
  require_invite_link_approval: boolean;
  require_strong_auth: boolean;
}

export interface TeamMember {
  user_id?: string;
  hashed_user_id?: string;
  role: TeamRole;
  status: string;
  joined_at?: number;
  encrypted_member_profile?: string | null;
  profile_image_url?: string | null;
  profile?: TeamMemberProfile;
}

export interface TeamMemberProfile {
  display_name: string;
  avatar: { mode: "generated"; icon_name: string; background_color: string };
}

export interface TeamInvite {
  invite_id: string;
  role: InviteRole;
  status: string;
  kind?: string;
  expires_at?: number;
  created_at?: number;
  encrypted_recipient_hint?: string | null;
  recipientEmail?: string;
}

export interface TeamViewModel {
  team_id: string;
  name: string;
  description: string;
  role: TeamRole;
  status: string;
  profileImageMetadata: Record<string, unknown>;
  zeroBalance: number;
  createdAt: number;
  updatedAt: number;
  encrypted: TeamRecord;
  securityPolicy?: TeamSecurityPolicy;
}

export interface TeamBillingSummary {
  balanceCredits: number;
  version?: number;
  encryptedBalance?: string | null;
  raw: Record<string, unknown>;
}

export interface TeamStorageUnit {
  unit_id: string;
  kind: 'upload' | 'cold_chat' | 'artifact_history';
  resource_id: string;
  oldest_at: number;
  bytes: number;
  fingerprint: string;
}

export interface TeamStorageNotice {
  episode_id: string | null;
  warning_count: number;
  deadline_at: number | null;
  manual_review: boolean;
  unit_selection_hash: string | null;
  units: TeamStorageUnit[];
  has_more: boolean;
  next_after_unit_id: string | null;
}

export interface TeamStorageSummary {
  total_bytes: number;
  legacy_upload_bytes: number;
  logical_s3_bytes: number;
  categories: Record<string, number>;
  measurement_at: number;
  metering_source_version: string;
  metering_policy_version: string;
  free_bytes: number;
  credits_per_started_excess_gib_per_week: number;
  billable_gib: number;
  weekly_cost_credits: number;
  billing_status: 'disabled_pending_validation' | 'current' | 'unpaid' | 'manual_review';
  billing: {
    status: 'disabled_pending_validation' | 'current' | 'unpaid' | 'manual_review';
    warning_count: number;
    deadline_at: number | null;
    expiry_due: boolean;
    expiry_enabled: boolean;
    affected_units: TeamStorageUnit[];
    has_more_affected_units: boolean;
  };
}

export interface TeamInviteResult {
  inviteId: string;
  role: InviteRole;
  status: string;
  deliveryStatus: string;
  raw: Record<string, unknown>;
  inviteUrl?: string;
}

export class TeamApiError extends Error {
  constructor(public readonly status: number, public readonly detail: string) {
    super(detail);
    this.name = "TeamApiError";
  }
}

export function isTeamAIInvocation(content: string): boolean {
  if (/(?:^|[^\w@])@openmates(?![\w-])/i.test(content)) return true;
  const knownMateIds = new Set(matesMetadata.map((mate) => mate.id));
  const mentions = content.matchAll(/(?:^|[^\w@])@mate:([a-z0-9_-]+)(?![\w-])/gi);
  return Array.from(mentions).some((match) => knownMateIds.has(match[1].toLowerCase()));
}

const teamKeyCache = new Map<string, Uint8Array>();
let teamKeyScope: string | null = null;
const teamListCache = new WorkspaceQueryCache<TeamViewModel[]>({ ttlMs: 60_000, maxEntries: 1 });
registerWorkspaceCacheClear(() => { teamKeyCache.clear(); teamKeyScope = null; });
if (typeof window !== "undefined") {
  window.addEventListener(TEAMS_UPDATED_EVENT, () => teamListCache.invalidate("teams"));
}

type TeamKeyScope = { identity: string | null; epoch: number };

export class TeamRequestCancelledError extends Error {
  constructor() {
    super("Team request was cancelled because the account or key changed.");
    this.name = "TeamRequestCancelledError";
  }
}

function ensureTeamKeyScope(): TeamKeyScope {
  const identity = getWorkspaceCacheIdentity();
  const epoch = getWorkspaceCacheEpoch();
  if (identity !== teamKeyScope) {
    teamKeyCache.clear();
    teamKeyScope = identity;
  }
  return { identity, epoch };
}

function assertTeamKeyScope(scope: TeamKeyScope): void {
  if (scope.epoch !== getWorkspaceCacheEpoch() || scope.identity !== getWorkspaceCacheIdentity()) {
    throw new TeamRequestCancelledError();
  }
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function defaultProfileImageMetadata(): Record<string, unknown> {
  return {
    version: 1,
    mode: "generated",
    icon_name: "team",
    icon_color: "#ffffff",
    background_color: "#4d73ff",
  };
}

function ownTeamMemberProfile(): TeamMemberProfile {
  const current = get(userProfile);
  return {
    display_name: current.username?.trim() || "Team member",
    avatar: { mode: "generated", icon_name: "mate", background_color: "#4d73ff" },
  };
}

export function generatedTeamProfileImageMetadata(iconName = "team", backgroundColor = "#4d73ff"): Record<string, unknown> {
  return { version: 1, mode: "generated", icon_name: iconName, icon_color: "#ffffff", background_color: backgroundColor };
}

const DEFAULT_SECURITY_POLICY: TeamSecurityPolicy = {
  restrict_email_domains: false,
  allowed_email_domains: [],
  require_invite_link_approval: true,
  require_strong_auth: false,
};

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(getApiEndpoint(path), {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string };
    throw new TeamApiError(response.status, body.detail ?? `Teams API failed (${response.status})`);
  }
  return (await response.json()) as T;
}

async function decryptOptional(value: string | null | undefined, key: Uint8Array): Promise<string> {
  if (!value) return "";
  return (await decryptWithEmbedKey(value, key)) ?? "";
}

async function teamKeyForRecord(record: TeamRecord, scope: TeamKeyScope): Promise<Uint8Array | null> {
  ensureTeamKeyScope();
  assertTeamKeyScope(scope);
  const teamId = record.team_id;
  if (!teamId) return null;
  const cached = teamKeyCache.get(teamId);
  if (cached) return cached;
  if (!record.encrypted_team_key) return null;
  const teamKey = await decryptChatKeyWithMasterKey(record.encrypted_team_key);
  assertTeamKeyScope(scope);
  if (!teamKey) return null;
  if (scope.identity) teamKeyCache.set(teamId, teamKey);
  return teamKey;
}

async function decryptTeam(record: TeamRecord, scope: TeamKeyScope): Promise<TeamViewModel | null> {
  assertTeamKeyScope(scope);
  const teamId = record.team_id;
  const teamKey = await teamKeyForRecord(record, scope);
  if (!teamId || !teamKey) return null;
  const profileText = await decryptOptional(record.encrypted_profile_image_metadata, teamKey);
  let profileImageMetadata = defaultProfileImageMetadata();
  if (profileText) {
    try {
      const parsed = JSON.parse(profileText) as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        profileImageMetadata = parsed as Record<string, unknown>;
      }
    } catch {
      profileImageMetadata = defaultProfileImageMetadata();
    }
  }
  const zeroBalanceText = await decryptOptional(record.encrypted_zero_balance, teamKey);
  const zeroBalance = Number.parseInt(zeroBalanceText || "0", 10);
  const name = await decryptOptional(record.encrypted_name, teamKey);
  const description = await decryptOptional(record.encrypted_description, teamKey);
  assertTeamKeyScope(scope);
  return {
    team_id: teamId,
    name: name || "Untitled team",
    description,
    role: record.role ?? "viewer",
    status: record.status ?? "active",
    profileImageMetadata,
    zeroBalance: Number.isFinite(zeroBalance) ? zeroBalance : 0,
    createdAt: record.created_at ?? 0,
    updatedAt: record.updated_at ?? 0,
    encrypted: record,
    securityPolicy: { ...DEFAULT_SECURITY_POLICY, ...record.security_policy },
  };
}

export async function listTeams(): Promise<TeamViewModel[]> {
  return teamListCache.load("teams", async () => {
    const scope = ensureTeamKeyScope();
    const data = await requestJson<{ teams: TeamRecord[] }>("/v1/teams");
    assertTeamKeyScope(scope);
    const decrypted = await Promise.all((data.teams ?? []).map(record => decryptTeam(record, scope)));
    return decrypted.filter((team): team is TeamViewModel => team !== null);
  });
}

export function subscribeTeamListRefresh(listener: () => void): () => void {
  return teamListCache.subscribe(() => {
    if (teamListCache.isFresh("teams")) listener();
  });
}

export async function getTeam(teamId: string): Promise<TeamViewModel> {
  const scope = ensureTeamKeyScope();
  const data = await requestJson<{ team: TeamRecord }>(`/v1/teams/${encodeURIComponent(teamId)}`);
  assertTeamKeyScope(scope);
  const decrypted = await decryptTeam(data.team, scope);
  assertTeamKeyScope(scope);
  if (!decrypted) throw new Error("Team could not be decrypted");
  return decrypted;
}

/** Forget local decrypted Team material only after the server confirms deletion. */
export async function deleteTeam(teamId: string): Promise<void> {
  await requestJson<{ success: boolean }>(`/v1/teams/${encodeURIComponent(teamId)}`, { method: "DELETE" });
  teamKeyCache.delete(teamId);
  teamListCache.invalidate("teams");
  if (getActiveTeamContextSnapshot().teamId === teamId) setActiveTeamContext(null);
}

export async function getTeamKey(teamId: string): Promise<Uint8Array> {
  const scope = ensureTeamKeyScope();
  const cached = teamKeyCache.get(teamId);
  if (cached) return cached;
  const team = await getTeam(teamId);
  assertTeamKeyScope(scope);
  const teamKey = teamKeyCache.get(teamId) ?? (team.encrypted.encrypted_team_key
    ? await decryptChatKeyWithMasterKey(team.encrypted.encrypted_team_key)
    : null);
  assertTeamKeyScope(scope);
  if (!teamKey) throw new Error(`Team key is unavailable for team ${teamId}`);
  return teamKey;
}

export async function unwrapTeamChatKey(
  teamId: string,
  encryptedChatKey: string,
): Promise<Uint8Array> {
  const chatKey = await unwrapEmbedKeyWithEmbedKey(
    encryptedChatKey,
    await getTeamKey(teamId),
  );
  if (!chatKey) throw new Error(`Team chat key could not be unwrapped for team ${teamId}`);
  return chatKey;
}

export async function wrapTeamChatKey(
  teamId: string,
  chatKey: Uint8Array,
): Promise<string> {
  const encryptedChatKey = await wrapEmbedKeyWithChatKey(
    chatKey,
    await getTeamKey(teamId),
  );
  if (!encryptedChatKey) throw new Error(`Team chat key could not be wrapped for team ${teamId}`);
  return encryptedChatKey;
}

export async function approveTeamName(name: string): Promise<string> {
  const data = await requestJson<{ approval_token: string }>("/v1/teams/name-approval", {
    method: "POST",
    body: JSON.stringify({ name: name.trim().toLowerCase() }),
  });
  return data.approval_token;
}

export async function createTeam(input: { name: string; description?: string | null; profileImageMetadata?: Record<string, unknown> }): Promise<TeamViewModel> {
  const scope = ensureTeamKeyScope();
  const name = input.name.trim();
  if (!name) throw new Error("Team name is required");
  const nameApprovalToken = await approveTeamName(name);
  const teamKey = generateEmbedKey();
  const encryptedTeamKey = await encryptChatKeyWithMasterKey(teamKey);
  if (!encryptedTeamKey) throw new Error("Could not wrap team key with master key");
  const teamId = crypto.randomUUID();
  const timestamp = nowSeconds();
  const payload: TeamRecord = {
    team_id: teamId,
    encrypted_name: await encryptWithEmbedKey(name, teamKey),
    encrypted_description: input.description ? await encryptWithEmbedKey(input.description, teamKey) : undefined,
    encrypted_profile_image_metadata: await encryptWithEmbedKey(JSON.stringify(input.profileImageMetadata ?? defaultProfileImageMetadata()), teamKey),
    encrypted_member_profile: await encryptWithEmbedKey(JSON.stringify(ownTeamMemberProfile()), teamKey),
    encrypted_team_key: encryptedTeamKey,
    encrypted_zero_balance: await encryptWithEmbedKey("0", teamKey),
    created_at: timestamp,
    updated_at: timestamp,
  };
  const data = await requestJson<{ team: TeamRecord }>("/v1/teams", {
    method: "POST",
    body: JSON.stringify({ ...payload, name_approval_token: nameApprovalToken }),
  });
  const returnedTeam = data.team ?? {};
  assertTeamKeyScope(scope);
  const createdTeamId = returnedTeam.team_id ?? teamId;
  if (scope.identity) teamKeyCache.set(createdTeamId, teamKey);
  const createdRecord: TeamRecord = {
    ...returnedTeam,
    team_id: createdTeamId,
    encrypted_name: returnedTeam.encrypted_name ?? payload.encrypted_name,
    encrypted_description: returnedTeam.encrypted_description ?? payload.encrypted_description,
    encrypted_profile_image_metadata: returnedTeam.encrypted_profile_image_metadata ?? payload.encrypted_profile_image_metadata,
    encrypted_team_key: encryptedTeamKey,
    encrypted_zero_balance: returnedTeam.encrypted_zero_balance ?? payload.encrypted_zero_balance,
    role: returnedTeam.role ?? "owner",
    created_at: returnedTeam.created_at ?? payload.created_at,
    updated_at: returnedTeam.updated_at ?? payload.updated_at,
  };
  const decrypted = await decryptTeam(createdRecord, scope);
  assertTeamKeyScope(scope);
  if (!decrypted) throw new Error("Created team could not be decrypted");
  teamListCache.invalidate("teams");
  return decrypted;
}

export async function updateTeamName(team: TeamViewModel, name: string): Promise<TeamViewModel> {
  const scope = ensureTeamKeyScope();
  const teamKey = await teamKeyForRecord(team.encrypted, scope);
  if (!teamKey) throw new Error("Team key is unavailable");
  const nameApprovalToken = await approveTeamName(name);
  const encryptedName = await encryptWithEmbedKey(name.trim(), teamKey);
  const data = await requestJson<{ team: TeamRecord }>(`/v1/teams/${encodeURIComponent(team.team_id)}`, {
    method: "PATCH",
    body: JSON.stringify({ encrypted_name: encryptedName, name_approval_token: nameApprovalToken, updated_at: nowSeconds() }),
  });
  const next = await decryptTeam({ ...team.encrypted, ...data.team, encrypted_name: encryptedName }, scope);
  if (!next) throw new Error("Updated team could not be decrypted");
  teamListCache.invalidate("teams");
  return next;
}

export async function updateTeamProfileMetadata(team: TeamViewModel, metadata: Record<string, unknown>): Promise<TeamViewModel> {
  const scope = ensureTeamKeyScope();
  const teamKey = await teamKeyForRecord(team.encrypted, scope);
  if (!teamKey) throw new Error("Team key is unavailable");
  const encryptedMetadata = await encryptWithEmbedKey(JSON.stringify(metadata), teamKey);
  const data = await requestJson<{ team: TeamRecord }>(`/v1/teams/${encodeURIComponent(team.team_id)}`, {
    method: "PATCH",
    body: JSON.stringify({ encrypted_profile_image_metadata: encryptedMetadata, updated_at: nowSeconds() }),
  });
  const next = await decryptTeam({ ...team.encrypted, ...data.team, encrypted_profile_image_metadata: encryptedMetadata }, scope);
  if (!next) throw new Error("Updated team could not be decrypted");
  teamListCache.invalidate("teams");
  return next;
}

export async function uploadTeamProfileImage(team: TeamViewModel, file: File): Promise<TeamViewModel> {
  const scope = ensureTeamKeyScope();
  const teamKey = await teamKeyForRecord(team.encrypted, scope);
  if (!teamKey) throw new Error("Team key is unavailable");
  const metadata = {
    version: 1, mode: "uploaded", image_url: `/v1/teams/${team.team_id}/profile-image`,
    content_safety_status: "accepted", updated_at: nowSeconds(), team_id: team.team_id,
  };
  const form = new FormData();
  form.append("team_id", team.team_id);
  form.append("encrypted_profile_image_metadata", await encryptWithEmbedKey(JSON.stringify(metadata), teamKey));
  form.append("file", await prepareFileForUpload(file));
  const response = await fetch(getUploadEndpoint("/v1/upload/team-profile-image"), {
    method: "POST", credentials: "include", body: form,
  });
  const data = await response.json().catch(() => ({})) as { status?: string; detail?: string; reject_count?: number };
  if (data.status === "account_deleted") {
    localStorage.setItem("policy_violation_lockout", String(Date.now() + 600_000));
    sessionStorage.setItem("account_deleted", "true");
    window.dispatchEvent(new CustomEvent("account-deleted"));
    throw new TeamApiError(response.status, "ACCOUNT_DELETED");
  }
  if (data.status === "rejected") throw new TeamApiError(response.status, data.reject_count === 3 ? "IMAGE_REJECTED_FINAL_WARNING" : "IMAGE_REJECTED");
  if (!response.ok || data.status !== "ok") throw new TeamApiError(response.status, data.detail ?? "IMAGE_UPLOAD_FAILED");
  return getTeam(team.team_id);
}

export async function loadTeamMembers(teamId: string): Promise<TeamMember[]> {
  const scope = ensureTeamKeyScope();
  const data = await requestJson<{ members: TeamMember[] }>(`/v1/teams/${encodeURIComponent(teamId)}/members`);
  assertTeamKeyScope(scope);
  const teamKey = await getTeamKey(teamId);
  assertTeamKeyScope(scope);
  const members = await Promise.all((data.members ?? []).map(async member => {
    if (!member.encrypted_member_profile) return member;
    try {
      const profileText = await decryptWithEmbedKey(member.encrypted_member_profile, teamKey);
      const parsed = JSON.parse(profileText ?? "{}") as Partial<TeamMemberProfile>;
      if (typeof parsed.display_name !== "string" || !parsed.display_name.trim()) return member;
      return { ...member, profile: { display_name: parsed.display_name, avatar: parsed.avatar ?? ownTeamMemberProfile().avatar } };
    } catch { return member; }
  }));
  assertTeamKeyScope(scope);
  return members;
}

export async function loadTeamMemberAvatar(teamId: string, member: TeamMember): Promise<string | null> {
  const scope = ensureTeamKeyScope();
  if (!member.user_id || member.profile_image_url !== `/v1/teams/${teamId}/members/${member.user_id}/profile-image`) return null;
  const response = await fetch(getApiEndpoint(member.profile_image_url), { credentials: "include" });
  assertTeamKeyScope(scope);
  if (!response.ok || !response.headers.get("content-type")?.startsWith("image/")) return null;
  const blob = await response.blob();
  assertTeamKeyScope(scope);
  return URL.createObjectURL(blob);
}

export async function updateTeamMemberRole(teamId: string, userId: string, role: InviteRole): Promise<void> {
  await requestJson(`/v1/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}`, {
    method: "PATCH", body: JSON.stringify({ role, updated_at: nowSeconds() }),
  });
}

export async function removeTeamMember(teamId: string, userId: string): Promise<void> {
  await requestJson(`/v1/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(userId)}/remove`, {
    method: "POST", body: JSON.stringify({ removed_at: nowSeconds() }),
  });
}

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function fromBase64Url(value: string): Uint8Array {
  const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(binary, character => character.charCodeAt(0));
}

function lengthPrefix(value: Uint8Array): Uint8Array {
  const output = new Uint8Array(4 + value.length);
  new DataView(output.buffer).setUint32(0, value.length, false);
  output.set(value, 4);
  return output;
}

async function deriveInviteKey(input: { recipientEmail: string; secret: string; inviteId: string; teamId: string; origin: string }): Promise<Uint8Array> {
  const encoder = new TextEncoder();
  const salt = await crypto.subtle.digest("SHA-256", encoder.encode("openmates:team-invite:v1"));
  const pieces = [input.recipientEmail.trim().toLowerCase(), input.inviteId, input.teamId, input.origin.replace(/\/$/, "")]
    .map(value => lengthPrefix(encoder.encode(value)));
  const info = new Uint8Array(pieces.reduce((sum, piece) => sum + piece.length, 0));
  let offset = 0;
  for (const piece of pieces) { info.set(piece, offset); offset += piece.length; }
  const material = await crypto.subtle.importKey("raw", new Uint8Array(fromBase64Url(input.secret)), "HKDF", false, ["deriveBits"]);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt, info: new Uint8Array(info) }, material, 256));
}

async function encryptInviteTeamKey(teamKey: Uint8Array, inviteKey: Uint8Array): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new Uint8Array(inviteKey), "AES-GCM", false, ["encrypt"]);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new Uint8Array(teamKey)));
  const combined = new Uint8Array(iv.length + ciphertext.length);
  combined.set(iv);
  combined.set(ciphertext, iv.length);
  let binary = "";
  for (const byte of combined) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export async function acceptTeamInviteFromFragment(inviteId: string, secret: string, verifiedEmail: string): Promise<{ status: string }> {
  const data = await requestJson<{ invite: Record<string, unknown> }>(`/v1/teams/invites/${encodeURIComponent(inviteId)}/preview`, {
    method: "POST", body: JSON.stringify({ verified_email: verifiedEmail.trim().toLowerCase() }),
  });
  const invite = data.invite;
  const context = invite.invite_key_kdf_context as Record<string, unknown> | undefined;
  const teamId = String(context?.team_id ?? "");
  const origin = String(context?.origin ?? window.location.origin);
  const encrypted = String(invite.encrypted_invite_team_key ?? "");
  if (!teamId || !encrypted) throw new Error("Invite is missing encrypted team key");
  const isLink = invite.kind === "link" || !invite.hashed_recipient_email;
  const key = await deriveInviteKey({ recipientEmail: isLink ? "" : verifiedEmail, secret, inviteId, teamId, origin });
  const bytes = Uint8Array.from(atob(encrypted), character => character.charCodeAt(0));
  const aes = await crypto.subtle.importKey("raw", new Uint8Array(key), "AES-GCM", false, ["decrypt"]);
  const teamKey = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: bytes.slice(0, 12) }, aes, bytes.slice(12)));
  const encryptedTeamKey = await encryptChatKeyWithMasterKey(teamKey);
  if (!encryptedTeamKey) throw new Error("Could not wrap accepted team key");
  const accepted = await requestJson<{ status?: string; status_label?: string }>(`/v1/teams/invites/${encodeURIComponent(inviteId)}/accept`, {
    method: "POST", body: JSON.stringify({ encrypted_team_key: encryptedTeamKey,
      encrypted_member_profile: await encryptWithEmbedKey(JSON.stringify(ownTeamMemberProfile()), teamKey),
      verified_email: verifiedEmail.trim().toLowerCase(), accepted_at: nowSeconds() }),
  });
  teamListCache.invalidate("teams");
  return { status: accepted.status ?? accepted.status_label ?? "pending" };
}

export async function declineTeamInvite(inviteId: string, verifiedEmail: string): Promise<void> {
  await requestJson(`/v1/teams/invites/${encodeURIComponent(inviteId)}/decline`, {
    method: "POST", body: JSON.stringify({ verified_email: verifiedEmail.trim().toLowerCase(), declined_at: nowSeconds() }),
  });
}

export async function loadTeamInvites(team: TeamViewModel): Promise<TeamInvite[]> {
  const data = await requestJson<{ invites: TeamInvite[] }>(`/v1/teams/${encodeURIComponent(team.team_id)}/invites`);
  const teamKey = await getTeamKey(team.team_id);
  return Promise.all((data.invites ?? []).map(async invite => {
    let recipientEmail = "";
    if (invite.encrypted_recipient_hint) {
      try {
        const hint = await decryptWithEmbedKey(invite.encrypted_recipient_hint, teamKey);
        recipientEmail = String((JSON.parse(hint ?? "{}") as { recipient_email?: string }).recipient_email ?? "");
      } catch { /* A revoked or legacy hint may be undecryptable. */ }
    }
    return { ...invite, recipientEmail };
  }));
}

export async function revokeTeamInvite(teamId: string, inviteId: string): Promise<void> {
  await requestJson(`/v1/teams/${encodeURIComponent(teamId)}/invites/${encodeURIComponent(inviteId)}/revoke`, { method: "POST" });
}

export async function updateTeamSecurity(teamId: string, policy: TeamSecurityPolicy): Promise<TeamSecurityPolicy> {
  const data = await requestJson<{ security_policy: TeamSecurityPolicy }>(`/v1/teams/${encodeURIComponent(teamId)}/security`, {
    method: "PATCH", body: JSON.stringify(policy),
  });
  teamListCache.invalidate("teams");
  return data.security_policy ?? policy;
}

export async function loadTeamBilling(team: TeamViewModel): Promise<TeamBillingSummary> {
  const scope = ensureTeamKeyScope();
  const data = await requestJson<{ billing: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(team.team_id)}/billing`);
  assertTeamKeyScope(scope);
  const version = data.billing.version;
  const authoritative = typeof version === 'number' && Number.isInteger(version);
  const rawBalance = authoritative
    ? data.billing.balance_credits
    : data.billing.balance_credits ?? data.billing.credits ?? data.billing.balance;
  let balanceCredits = typeof rawBalance === "number" ? rawBalance : Number.parseInt(String(rawBalance ?? ""), 10);
  const encryptedBalance = typeof data.billing.encrypted_balance === "string" ? data.billing.encrypted_balance : null;
  if (authoritative && (typeof rawBalance !== 'number' || !Number.isInteger(balanceCredits) || balanceCredits < 0)) {
    throw new Error('Team wallet balance is unavailable');
  }
  if ((!Number.isFinite(balanceCredits) || balanceCredits < 0) && encryptedBalance) {
    const teamKey = await teamKeyForRecord(team.encrypted, scope);
    if (teamKey) {
      const decrypted = await decryptWithEmbedKey(encryptedBalance, teamKey);
      balanceCredits = Number.parseInt(decrypted ?? "0", 10);
    }
  }
  if (!Number.isFinite(balanceCredits) || balanceCredits < 0) balanceCredits = team.zeroBalance;
  return { balanceCredits, version: authoritative ? version : undefined, encryptedBalance, raw: data.billing };
}

export async function loadTeamStorage(teamId: string): Promise<TeamStorageSummary> {
  const scope = ensureTeamKeyScope();
  const data = await requestJson<{ storage: TeamStorageSummary }>(`/v1/teams/${encodeURIComponent(teamId)}/storage`);
  assertTeamKeyScope(scope);
  return data.storage;
}

export async function loadTeamStorageNotice(teamId: string, afterUnitId?: string): Promise<TeamStorageNotice> {
  const scope = ensureTeamKeyScope();
  const query = new URLSearchParams({ limit: '50' });
  if (afterUnitId) query.set('after_unit_id', afterUnitId);
  const notice = await requestJson<TeamStorageNotice>(`/v1/teams/${encodeURIComponent(teamId)}/storage/notice?${query}`);
  assertTeamKeyScope(scope);
  return notice;
}

export async function loadTeamMemoryCount(teamId: string): Promise<number> {
  const data = await requestJson<{ memories: unknown[] }>(`/v1/teams/${encodeURIComponent(teamId)}/memories`);
  return Array.isArray(data.memories) ? data.memories.length : 0;
}

export async function createTeamEmailInvite(team: TeamViewModel, email: string, role: InviteRole = "member"): Promise<TeamInviteResult> {
  const scope = ensureTeamKeyScope();
  const recipientEmail = email.trim().toLowerCase();
  if (!recipientEmail) throw new Error("Recipient email is required");
  const teamKey = await teamKeyForRecord(team.encrypted, scope);
  if (!teamKey) throw new Error("Team key is unavailable for invite encryption");
  const inviteId = crypto.randomUUID();
  const secret = base64Url(crypto.getRandomValues(new Uint8Array(32)));
  const origin = window.location.origin;
  const inviteKey = await deriveInviteKey({ recipientEmail, secret, inviteId, teamId: team.team_id, origin });
  const payload = {
    invite_id: inviteId,
    role,
    recipient_email: recipientEmail,
    encrypted_recipient_hint: await encryptWithEmbedKey(JSON.stringify({ recipient_email: recipientEmail, role }), teamKey),
    encrypted_invite_team_key: await encryptInviteTeamKey(teamKey, inviteKey),
    invite_key_kdf_context: { v: 1, kdf: "HKDF-SHA256", cipher: "AES-256-GCM", team_id: team.team_id, invite_id: inviteId, origin },
    created_at: nowSeconds(),
    expires_at: nowSeconds() + 7 * 24 * 60 * 60,
  };
  const data = await requestJson<{ invite: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(team.team_id)}/invites`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return {
    inviteId: String(data.invite.invite_id ?? payload.invite_id),
    role: (data.invite.role as InviteRole | undefined) ?? role,
    status: String(data.invite.status ?? "created"),
    deliveryStatus: String(data.invite.delivery_status ?? "created"),
    raw: data.invite,
    inviteUrl: `${origin}/teams/invites/${inviteId}#key=${secret}`,
  };
}

export async function createTeamLinkInvite(team: TeamViewModel, role: InviteRole = "member"): Promise<TeamInviteResult> {
  const teamKey = await getTeamKey(team.team_id);
  const inviteId = crypto.randomUUID();
  const secret = base64Url(crypto.getRandomValues(new Uint8Array(32)));
  const inviteKey = await deriveInviteKey({ recipientEmail: "", secret, inviteId, teamId: team.team_id, origin: window.location.origin });
  const payload = {
    invite_id: inviteId, role,
    encrypted_invite_team_key: await encryptInviteTeamKey(teamKey, inviteKey),
    invite_key_kdf_context: { v: 1, kdf: "HKDF-SHA256", cipher: "AES-256-GCM", team_id: team.team_id, invite_id: inviteId, origin: window.location.origin },
    created_at: nowSeconds(), expires_at: nowSeconds() + 24 * 60 * 60,
  };
  const data = await requestJson<{ invite: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(team.team_id)}/invites`, {
    method: "POST", body: JSON.stringify(payload),
  });
  return {
    inviteId: String(data.invite.invite_id ?? inviteId), role, status: String(data.invite.status ?? "created"),
    deliveryStatus: "link", raw: data.invite,
    inviteUrl: `${window.location.origin}/teams/invites/${inviteId}#key=${secret}`,
  };
}
