/** Optional Team email preview transport. Only a fresh server capability allows plaintext upload. */

import { webSocketService } from "./websocketService";
import { generateUUID } from "../message_parsing/utils";

const RESPONSE_TIMEOUT_MS = 1500;
const MAX_PREVIEW_CHARS = 2000;

type Reply = Record<string, unknown> & { request_id?: string };

async function request<T extends Reply>(event: string, responseEvent: string, payload: Record<string, unknown>): Promise<T | null> {
  const requestId = generateUUID();
  let handler: (reply: unknown) => void = () => undefined;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const response = new Promise<T | null>((resolve) => {
    handler = (reply: unknown) => {
      if (!reply || typeof reply !== "object" || (reply as Reply).request_id !== requestId) return;
      cleanup();
      resolve(reply as T);
    };
    const cleanup = () => {
      if (timeout) clearTimeout(timeout);
      webSocketService.off(responseEvent, handler);
    };
    timeout = setTimeout(() => { cleanup(); resolve(null); }, RESPONSE_TIMEOUT_MS);
    webSocketService.on(responseEvent, handler);
  });
  try {
    await webSocketService.sendMessage(event, { ...payload, request_id: requestId });
    return await response;
  } catch {
    webSocketService.off(responseEvent, handler);
    if (timeout) clearTimeout(timeout);
    return null;
  }
}

export async function stageTeamNotificationPreview(input: {
  teamId: string;
  chatId: string;
  messageId: string;
  content: string;
  title?: string | null;
}): Promise<void> {
  if (!input.content.trim() || !webSocketService.isConnected()) return;
  const capability = await request<Reply>(
    "team_notification_preview_capabilities",
    "team_notification_preview_capabilities_result",
    { team_id: input.teamId, chat_id: input.chatId },
  );
  if (!capability || typeof capability.capability_id !== "string" ||
      typeof capability.recipient_count !== "number" || capability.recipient_count <= 0) return;
  const preview = input.content.trim().split(/\r?\n/).slice(0, 10).join("\n").slice(0, MAX_PREVIEW_CHARS);
  if (!preview) return;
  const title = input.title?.trim().slice(0, 60) || undefined;
  await request<Reply>(
    "team_notification_preview_stage",
    "team_notification_preview_stage_result",
    {
      team_id: input.teamId,
      chat_id: input.chatId,
      message_id: input.messageId,
      capability_id: capability.capability_id,
      preview,
      ...(title ? { title } : {}),
    },
  );
}
