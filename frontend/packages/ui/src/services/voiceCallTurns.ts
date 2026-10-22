/** Voice is an input mode of an ordinary encrypted chat turn. */
import type { Message, VoiceHeardBoundary } from '../types/chat';
import { chatDB } from './db';
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';
import { getWorkspaceCacheEpoch } from './workspaceCacheLifecycle';
import { formatVoiceArtifactReference, type VoiceArtifactReference } from './voiceCallArtifactReferences';

export interface VoiceCallTurn {
  callId: string;
  chatId: string;
  turnId: string;
  text: string;
  createdAt?: number;
  embedReferences?: VoiceArtifactReference[];
  heardBoundary?: VoiceHeardBoundary;
  isCurrent?: () => boolean;
}

interface VoiceCallDeliveryFailure {
  errorClass?: string;
  errorCode?: string;
  httpStatus?: number;
  module?: string;
  line?: number;
}

const deliveryErrorClasses = new Set(['Error', 'TypeError', 'RangeError', 'SyntaxError', 'ReferenceError',
  'DOMException', 'AbortError', 'OperationError', 'InvalidStateError', 'InvalidAccessError', 'DataError',
  'QuotaExceededError', 'ConstraintError', 'TransactionInactiveError', 'NotFoundError', 'DataCloneError',
  'NetworkError', 'PreflightRejectionError', 'PendingAdmissionCompatibilityError']);
const deliveryErrorCodes = new Set(['immutable_chat_key_mismatch', 'message_identity_mismatch', 'preflight_mismatch',
  'recovery_key_mismatch', 'version_conflict', 'inference_commitment_mismatch', 'client_update_required',
  'durable_preflight_failed', 'preflight_expired', 'preflight_required', 'team_chat_scope_mismatch',
  'existing_chat_metadata_forbidden', 'websocket_receipt_connection_changed']);
const deliveryHttpStatuses = new Set([400, 401, 403, 404, 408, 409, 413, 422, 429, 500, 502, 503, 504]);
const deliveryErrorModules = new Set(['services/voiceCallTurns.ts', 'services/chatSyncService.ts',
  'services/sendersChatMessages.ts', 'services/preparedPrivacyForSend.ts', 'services/preflightAcknowledgement.ts',
  'services/serverCapabilityGate.ts', 'services/outboundMessageSends.ts', 'services/personalChatTurnBarrier.ts',
  'services/fastAdmissionJournal.ts', 'services/fastAdmissionPhaseJournal.ts', 'services/savedPersonalAdmissionHistory.ts',
  'services/websocketService.ts', 'services/chatKeyWriteGuard.ts', 'services/chatKeyConsistency.ts',
  'services/encryption/ChatKeyManager.ts', 'services/db.ts', 'services/db/messageOperations.ts',
  'services/db/chatCrudOperations.ts', 'services/db/messageJournalOperations.ts', 'utils/chatCompletionRecovery.ts']);

/** Extract only known categories and a static repository location. The raw
 * message, stack, URL and query never enter delivery evidence. */
function deliveryFailureMetadata(error: unknown): VoiceCallDeliveryFailure {
  if (!error || typeof error !== 'object') return {};
  const value = error as { name?: unknown; code?: unknown; status?: unknown; statusCode?: unknown;
    constructor?: { name?: unknown }; stack?: unknown };
  const failure: VoiceCallDeliveryFailure = {};
  for (const name of [value.constructor?.name, value.name]) {
    if (typeof name === 'string' && deliveryErrorClasses.has(name)) { failure.errorClass = name; break; }
  }
  if (typeof value.code === 'string' && deliveryErrorCodes.has(value.code)) failure.errorCode = value.code;
  const status = value.status ?? value.statusCode;
  if (typeof status === 'number' && deliveryHttpStatuses.has(status)) failure.httpStatus = status;
  if (typeof value.stack === 'string') {
    for (const frame of value.stack.slice(0, 16_384).split('\n').slice(1, 17)) {
      const location = frame.match(/\/src\/([A-Za-z0-9_/]+\.ts)(?:\?[^\s):]*)?:(\d{1,6}):\d{1,6}\)?\s*$/);
      if (!location || !deliveryErrorModules.has(location[1])) continue;
      const line = Number(location[2]);
      if (line < 1) continue;
      failure.module = location[1]; failure.line = line; break;
    }
  }
  return failure;
}

/** Local, content-free delivery evidence. Never contains text, audio or credentials. */
export function reportVoiceCallTurnDelivery(
  turn: Pick<VoiceCallTurn, 'callId' | 'chatId' | 'turnId'>,
  phase: string,
  reason?: string,
  failure?: VoiceCallDeliveryFailure,
): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent('voiceCallTurnDelivery', { detail: {
    callId: turn.callId, chatId: turn.chatId, turnId: turn.turnId, phase,
    ...(reason ? { reason } : {}), ...(failure ? { failure } : {}),
  } }));
}

function deliveryFailureCode(error: unknown): string {
  if (error instanceof Error) {
    if (error.message === 'The previous encrypted reply has not been saved. Retry this message after recovery.') return 'predecessor_not_saved';
    if (error.message === 'An active message send cannot change its immutable content.') return 'message_identity_conflict';
    if (error.message === 'Cannot bind a settled encrypted chat turn.') return 'turn_already_settled';
  }
  const code = error && typeof error === 'object' ? (error as { code?: unknown }).code : undefined;
  return typeof code === 'string' && deliveryErrorCodes.has(code) ? code : 'operation_failed';
}

/** The ordinary sender owns encryption, admission, routing, retries and responses.
 * No assistant transcript or spoken projection is ever written by this adapter.
 */
export async function sendVoiceCallTurn(turn: VoiceCallTurn): Promise<boolean> {
  let phase = 'validating';
  const enter = (next: string) => { phase = next; reportVoiceCallTurnDelivery(turn, next); };
  const refuse = (reason: string) => { reportVoiceCallTurnDelivery(turn, 'refused', reason); return false; };
  enter(phase);
  try {
    if (!turn.callId || !turn.chatId || !turn.turnId || !turn.text.trim()) return refuse('invalid_turn');
    const identity = getWorkspaceCacheIdentity();
    const epoch = getWorkspaceCacheEpoch();
    const current = () => !!identity && identity === getWorkspaceCacheIdentity() && epoch === getWorkspaceCacheEpoch() && (turn.isCurrent?.() ?? true);
    if (!current()) return refuse('scope_changed');
    enter('sender_loading');
    const { chatSyncService } = await import('./chatSyncService');
    if (!current()) return refuse('scope_changed');
    if (!chatSyncService.webSocketConnected_FOR_SENDERS_ONLY) return refuse('disconnected');
    const references = [...new Map((turn.embedReferences ?? []).map(ref => [ref.embed_id, ref])).values()];
    const message: Message = {
      message_id: turn.turnId, chat_id: turn.chatId, role: 'user',
      content: [turn.text.trim(), ...references.map(formatVoiceArtifactReference)].join('\n\n'),
      created_at: turn.createdAt ?? Math.floor(Date.now() / 1000), status: 'sending',
      voice_call_id: turn.callId, voice_turn_id: turn.turnId, voice_mode: true,
      ...(turn.heardBoundary ? { voice_heard_boundary: turn.heardBoundary } : {}),
      auto_speak: true, preserve_draft: true,
    };
    enter('chat_loading');
    const chat = await chatDB.getChat(turn.chatId);
    if (!current()) return refuse('scope_changed');
    if (!chat || chat.team_id || chat.chat_visibility === 'direct') return refuse('personal_chat_unavailable');
    // Match the ordinary composer's encrypted optimistic row before admission.
    // Delivery metadata belongs only to this request, never the durable row.
    const { voice_call_id: _call, voice_turn_id: _turn, voice_mode: _voice,
      auto_speak: _speak, preserve_draft: _draft, voice_heard_boundary: _heard, ...durableMessage } = message;
    enter('message_saving');
    await chatDB.saveMessage(durableMessage);
    if (!current()) return refuse('scope_changed');
    enter('chat_refreshing');
    const currentChat = await chatDB.getChat(turn.chatId);
    if (!current()) return refuse('scope_changed');
    if (!currentChat) return refuse('personal_chat_unavailable');
    const optimisticChat = { ...currentChat, messages_v: (currentChat.messages_v ?? 0) + 1,
      updated_at: message.created_at, last_edited_overall_timestamp: message.created_at };
    enter('chat_updating');
    await chatDB.updateChat(optimisticChat);
    if (!current()) return refuse('scope_changed');
    chatSyncService.dispatchEvent(new CustomEvent('chatUpdated', {
      detail: { chat_id: turn.chatId, chat: optimisticChat, newMessage: durableMessage },
    }));
    enter('canonical_sending');
    await chatSyncService.sendNewMessage(message);
    enter('receipt_reading');
    const stored = await chatDB.getMessage(turn.turnId);
    if (!stored) return refuse('message_row_unavailable');
    if (stored.status === 'failed') return refuse('message_failed');
    if (stored.status === 'waiting_for_internet') return refuse('message_waiting_for_connection');
    enter('accepted');
    return true;
  } catch (error) {
    reportVoiceCallTurnDelivery(turn, 'failed', `${phase}:${deliveryFailureCode(error)}`, deliveryFailureMetadata(error));
    throw error;
  }
}
