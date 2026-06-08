// frontend/packages/ui/src/services/applicationPreviewService.ts
//
// Client helpers for generated application preview sessions.
// These APIs start, poll, and stop server-side E2B preview sessions while the
// actual app traffic is loaded from the separate user-content preview origin.

import { getApiUrl } from '../config/api';
import { decodeToonContent, resolveEmbed } from './embedResolver';

export interface ApplicationPreviewStartResponse {
  session_id: string;
  preview_url: string;
  status: ApplicationPreviewStatusValue;
  credits_per_minute: number;
}

export type ApplicationPreviewStatusValue = 'queued' | 'starting' | 'running' | 'stopped' | 'failed' | 'timeout';

export interface ApplicationPreviewStatus {
  session_id: string;
  status: ApplicationPreviewStatusValue;
  events?: Array<{ kind: string; text: string; timestamp: number }>;
  error?: string;
  charged_credits?: number;
  latest_screenshot_url?: string;
  latest_screenshot?: Record<string, unknown>;
}

interface ApplicationFileRef {
  path?: unknown;
  embed_id?: unknown;
  role?: unknown;
}

interface SharedPreviewContext {
  application_embed_id: string;
  application_content: Record<string, unknown>;
  child_contents: Record<string, Record<string, unknown>>;
}

function errorMessageFromPayload(payload: unknown, fallback: string): string {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && 'message' in detail) {
      const message = (detail as { message?: unknown }).message;
      if (typeof message === 'string') return message;
    }
  }
  return fallback;
}

export async function startApplicationPreview(
  chatId: string,
  applicationEmbedId: string,
  sharedContext?: string,
): Promise<ApplicationPreviewStartResponse> {
  const response = await fetch(`${getApiUrl()}/v1/applications/${encodeURIComponent(applicationEmbedId)}/preview/start`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, shared_context: sharedContext }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(errorMessageFromPayload(payload, `Application preview failed to start (${response.status})`));
  }

  return response.json();
}

export async function buildApplicationPreviewSharedContext(
  applicationEmbedId: string,
  applicationContent: Record<string, unknown>,
): Promise<string | undefined> {
  const fileRefs = Array.isArray(applicationContent.file_refs)
    ? applicationContent.file_refs as ApplicationFileRef[]
    : [];
  if (!fileRefs.length) return undefined;

  const childContents: Record<string, Record<string, unknown>> = {};
  for (const ref of fileRefs) {
    const embedId = typeof ref.embed_id === 'string' ? ref.embed_id : '';
    if (!embedId) return undefined;

    const embed = await resolveEmbed(embedId);
    const decoded = await decodeToonContent(embed?.content);
    if (!decoded) return undefined;
    childContents[embedId] = decoded;
  }

  const context: SharedPreviewContext = {
    application_embed_id: applicationEmbedId,
    application_content: applicationContent,
    child_contents: childContents,
  };
  return JSON.stringify(context);
}

export async function getApplicationPreviewStatus(sessionId: string): Promise<ApplicationPreviewStatus> {
  const response = await fetch(`${getApiUrl()}/v1/applications/preview/${encodeURIComponent(sessionId)}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(errorMessageFromPayload(payload, `Application preview status unavailable (${response.status})`));
  }

  return response.json();
}

export async function stopApplicationPreview(sessionId: string): Promise<{ session_id: string; status: string; charged_credits?: number }> {
  const response = await fetch(`${getApiUrl()}/v1/applications/preview/${encodeURIComponent(sessionId)}/stop`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(errorMessageFromPayload(payload, `Application preview stop failed (${response.status})`));
  }

  return response.json();
}
