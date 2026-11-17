// frontend/packages/ui/src/services/safetyAppealApi.ts
// REST calls of the suspended-user appeal (appeal token auth, first-party surface only).
import { getApiEndpoint } from "../config/api";

export interface AppealPayload {
  explanation: string;
  consent_share_requests: boolean;
  flagged_requests?: string[];
  attachment_data_url?: string | null;
}

async function call(path: string, token: string, init?: RequestInit): Promise<Response> {
  return fetch(getApiEndpoint(`/v1/safety/appeal${path}`), {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
  });
}

export async function submitAppeal(token: string, payload: AppealPayload): Promise<{ ok: boolean; message?: string }> {
  const response = await call("", token, { method: "POST", body: JSON.stringify(payload) });
  if (response.ok) return { ok: true };
  const body = await response.json().catch(() => ({}));
  return { ok: false, message: typeof body.detail === "string" ? body.detail : undefined };
}

export async function fetchAppealStatus(token: string): Promise<{ flagged_message_ids: string[]; appeal: { status: string; admin_question?: string | null } | null }> {
  const response = await call("", token);
  if (!response.ok) throw new Error(`Appeal status failed (${response.status})`);
  return response.json();
}
