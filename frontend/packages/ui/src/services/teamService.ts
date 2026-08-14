// frontend/packages/ui/src/services/teamService.ts
// Browser Teams V1 service for first-party web sessions. It mirrors the CLI
// encrypted team payload contract: a random team AES key encrypts team metadata,
// then the user's master key wraps that team key for the current membership.
// Backend routes remain first-party/session-authenticated and reject cleartext
// in encrypted fields. Spec: docs/specs/teams-v1/spec.yml

import { getApiEndpoint } from "../config/api";
import {
  decryptChatKeyWithMasterKey,
  decryptWithEmbedKey,
  encryptChatKeyWithMasterKey,
  encryptWithEmbedKey,
  generateEmbedKey,
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
}

export interface TeamBillingSummary {
  balanceCredits: number;
  encryptedBalance?: string | null;
  raw: Record<string, unknown>;
}

export interface TeamInviteResult {
  inviteId: string;
  role: InviteRole;
  status: string;
  deliveryStatus: string;
  raw: Record<string, unknown>;
}

const teamKeyCache = new Map<string, Uint8Array>();

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
    const detail = await response.text();
    throw new Error(`Teams API failed (${response.status}): ${detail}`);
  }
  return (await response.json()) as T;
}

async function decryptOptional(value: string | null | undefined, key: Uint8Array): Promise<string> {
  if (!value) return "";
  return (await decryptWithEmbedKey(value, key)) ?? "";
}

async function teamKeyForRecord(record: TeamRecord): Promise<Uint8Array | null> {
  const teamId = record.team_id;
  if (!teamId) return null;
  const cached = teamKeyCache.get(teamId);
  if (cached) return cached;
  if (!record.encrypted_team_key) return null;
  const teamKey = await decryptChatKeyWithMasterKey(record.encrypted_team_key);
  if (!teamKey) return null;
  teamKeyCache.set(teamId, teamKey);
  return teamKey;
}

async function decryptTeam(record: TeamRecord): Promise<TeamViewModel | null> {
  const teamId = record.team_id;
  const teamKey = await teamKeyForRecord(record);
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
  return {
    team_id: teamId,
    name: await decryptOptional(record.encrypted_name, teamKey) || "Untitled team",
    description: await decryptOptional(record.encrypted_description, teamKey),
    role: record.role ?? "viewer",
    status: record.status ?? "active",
    profileImageMetadata,
    zeroBalance: Number.isFinite(zeroBalance) ? zeroBalance : 0,
    createdAt: record.created_at ?? 0,
    updatedAt: record.updated_at ?? 0,
    encrypted: record,
  };
}

export async function listTeams(): Promise<TeamViewModel[]> {
  const data = await requestJson<{ teams: TeamRecord[] }>("/v1/teams");
  const decrypted = await Promise.all((data.teams ?? []).map(decryptTeam));
  return decrypted.filter((team): team is TeamViewModel => team !== null);
}

export async function getTeam(teamId: string): Promise<TeamViewModel> {
  const data = await requestJson<{ team: TeamRecord }>(`/v1/teams/${encodeURIComponent(teamId)}`);
  const decrypted = await decryptTeam(data.team);
  if (!decrypted) throw new Error("Team could not be decrypted");
  return decrypted;
}

export async function createTeam(input: { name: string; description?: string | null }): Promise<TeamViewModel> {
  const name = input.name.trim();
  if (!name) throw new Error("Team name is required");
  const teamKey = generateEmbedKey();
  const encryptedTeamKey = await encryptChatKeyWithMasterKey(teamKey);
  if (!encryptedTeamKey) throw new Error("Could not wrap team key with master key");
  const teamId = crypto.randomUUID();
  const timestamp = nowSeconds();
  const payload: TeamRecord = {
    team_id: teamId,
    encrypted_name: await encryptWithEmbedKey(name, teamKey),
    encrypted_description: input.description ? await encryptWithEmbedKey(input.description, teamKey) : undefined,
    encrypted_profile_image_metadata: await encryptWithEmbedKey(JSON.stringify(defaultProfileImageMetadata()), teamKey),
    encrypted_team_key: encryptedTeamKey,
    encrypted_zero_balance: await encryptWithEmbedKey("0", teamKey),
    created_at: timestamp,
    updated_at: timestamp,
  };
  const data = await requestJson<{ team: TeamRecord }>("/v1/teams", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const returnedTeam = data.team ?? {};
  const createdTeamId = returnedTeam.team_id ?? teamId;
  teamKeyCache.set(createdTeamId, teamKey);
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
  const decrypted = await decryptTeam(createdRecord);
  if (!decrypted) throw new Error("Created team could not be decrypted");
  return decrypted;
}

export async function loadTeamBilling(team: TeamViewModel): Promise<TeamBillingSummary> {
  const data = await requestJson<{ billing: Record<string, unknown> }>(`/v1/teams/${encodeURIComponent(team.team_id)}/billing`);
  const rawBalance = data.billing.balance_credits ?? data.billing.credits ?? data.billing.balance;
  let balanceCredits = typeof rawBalance === "number" ? rawBalance : Number.parseInt(String(rawBalance ?? ""), 10);
  const encryptedBalance = typeof data.billing.encrypted_balance === "string" ? data.billing.encrypted_balance : null;
  const teamKey = await teamKeyForRecord(team.encrypted);
  if ((!Number.isFinite(balanceCredits) || balanceCredits < 0) && encryptedBalance && teamKey) {
    const decrypted = await decryptWithEmbedKey(encryptedBalance, teamKey);
    balanceCredits = Number.parseInt(decrypted ?? "0", 10);
  }
  if (!Number.isFinite(balanceCredits) || balanceCredits < 0) balanceCredits = team.zeroBalance;
  return { balanceCredits, encryptedBalance, raw: data.billing };
}

export async function loadTeamMemoryCount(teamId: string): Promise<number> {
  const data = await requestJson<{ memories: unknown[] }>(`/v1/teams/${encodeURIComponent(teamId)}/memories`);
  return Array.isArray(data.memories) ? data.memories.length : 0;
}

export async function createTeamEmailInvite(team: TeamViewModel, email: string, role: InviteRole = "member"): Promise<TeamInviteResult> {
  const recipientEmail = email.trim().toLowerCase();
  if (!recipientEmail) throw new Error("Recipient email is required");
  const teamKey = await teamKeyForRecord(team.encrypted);
  if (!teamKey) throw new Error("Team key is unavailable for invite encryption");
  const payload = {
    invite_id: crypto.randomUUID(),
    role,
    recipient_email: recipientEmail,
    encrypted_recipient_hint: await encryptWithEmbedKey(JSON.stringify({ recipient_email: recipientEmail, role }), teamKey),
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
  };
}
