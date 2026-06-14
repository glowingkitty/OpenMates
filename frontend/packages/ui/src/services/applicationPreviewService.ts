// frontend/packages/ui/src/services/applicationPreviewService.ts
//
// Client helpers for generated application preview sessions.
// These APIs start, poll, and stop server-side E2B preview sessions while the
// actual app traffic is loaded from the separate user-content preview origin.

import { getApiUrl } from '../config/api';
import { decodeToonContent, extractEmbedReferences, resolveEmbed } from './embedResolver';

const AUTO_START_RESOLVE_ATTEMPTS = 6;
const AUTO_START_RESOLVE_DELAY_MS = 500;

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
  auto_started?: boolean;
  auto_opened_at?: number | null;
}

export interface CachedApplicationPreviewSession extends ApplicationPreviewStartResponse {
  application_embed_id: string;
  chat_id: string;
  message_id?: string;
  auto_started?: boolean;
  started_at: number;
}

interface ApplicationPreviewStartOptions {
  sharedContext?: string;
  autoStarted?: boolean;
  sourceMessageId?: string;
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

const applicationPreviewSessions = new Map<string, CachedApplicationPreviewSession>();
const autoStartAttempts = new Set<string>();

function sessionCacheKey(chatId: string, applicationEmbedId: string): string {
  return `${chatId}:${applicationEmbedId}`;
}

function normalizeStartOptions(sharedContextOrOptions?: string | ApplicationPreviewStartOptions): ApplicationPreviewStartOptions {
  if (typeof sharedContextOrOptions === 'string') return { sharedContext: sharedContextOrOptions };
  return sharedContextOrOptions ?? {};
}

function rememberApplicationPreviewSession(session: CachedApplicationPreviewSession) {
  applicationPreviewSessions.set(sessionCacheKey(session.chat_id, session.application_embed_id), session);
}

export function getCachedApplicationPreviewSession(
  chatId: string | undefined,
  applicationEmbedId: string | undefined,
): CachedApplicationPreviewSession | undefined {
  if (!chatId || !applicationEmbedId) return undefined;
  return applicationPreviewSessions.get(sessionCacheKey(chatId, applicationEmbedId));
}

export function updateCachedApplicationPreviewSessionStatus(
  chatId: string | undefined,
  applicationEmbedId: string | undefined,
  status: ApplicationPreviewStatusValue,
) {
  const session = getCachedApplicationPreviewSession(chatId, applicationEmbedId);
  if (!session) return;
  session.status = status;
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
  sharedContextOrOptions?: string | ApplicationPreviewStartOptions,
): Promise<ApplicationPreviewStartResponse> {
  const options = normalizeStartOptions(sharedContextOrOptions);
  const response = await fetch(`${getApiUrl()}/v1/applications/${encodeURIComponent(applicationEmbedId)}/preview/start`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: chatId,
      shared_context: options.sharedContext,
      auto_started: options.autoStarted ?? false,
      source_message_id: options.sourceMessageId,
    }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(errorMessageFromPayload(payload, `Application preview failed to start (${response.status})`));
  }

  const session = await response.json() as ApplicationPreviewStartResponse;
  rememberApplicationPreviewSession({
    ...session,
    application_embed_id: applicationEmbedId,
    chat_id: chatId,
    message_id: options.sourceMessageId,
    auto_started: options.autoStarted,
    started_at: Date.now(),
  });
  return session;
}

export async function autoStartCreatedApplicationPreview(
  chatId: string,
  messageId: string,
  markdown: string,
): Promise<ApplicationPreviewStartResponse | undefined> {
  const applicationRefs = extractEmbedReferences(markdown).filter((ref) => ref.type === 'application' || ref.type === 'code-application');
  const applicationEmbedId = applicationRefs.length ? applicationRefs[applicationRefs.length - 1].embed_id : undefined;
  if (!applicationEmbedId) return undefined;

  const attemptKey = `${chatId}:${messageId}:${applicationEmbedId}`;
  if (autoStartAttempts.has(attemptKey)) return undefined;
  autoStartAttempts.add(attemptKey);

  try {
    const embedReady = await waitForApplicationEmbed(applicationEmbedId);
    if (!embedReady) return undefined;
    return await startApplicationPreview(chatId, applicationEmbedId, {
      autoStarted: true,
      sourceMessageId: messageId,
    });
  } catch (error) {
    console.warn('[applicationPreviewService] Auto-start application preview failed:', error);
    return undefined;
  }
}

async function waitForApplicationEmbed(applicationEmbedId: string): Promise<boolean> {
  for (let attempt = 0; attempt < AUTO_START_RESOLVE_ATTEMPTS; attempt += 1) {
    try {
      const embed = await resolveEmbed(applicationEmbedId);
      const decoded = await decodeToonContent(embed?.content);
      if (decoded && String(decoded.type || '').toLowerCase() === 'application') return true;
    } catch {
      // Embed data can arrive just after the final assistant chunk; retry briefly.
    }
    await new Promise((resolve) => setTimeout(resolve, AUTO_START_RESOLVE_DELAY_MS));
  }
  return false;
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

export async function openApplicationPreviewSession(sessionId: string): Promise<ApplicationPreviewStatus> {
  const response = await fetch(`${getApiUrl()}/v1/applications/preview/${encodeURIComponent(sessionId)}/open`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(errorMessageFromPayload(payload, `Application preview open failed (${response.status})`));
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
