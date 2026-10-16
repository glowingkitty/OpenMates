/** Adapt live call events to the shared, encrypted chat context and embed paths. */
import type { SendEmbedDataPayload } from '../types/chat';
import type { MemoryPermissionResponse } from './chatSyncServiceHandlersAppSettings';
import { parseVoiceArtifactReference } from './voiceCallArtifactReferences';

export interface VoiceToolBinding {
  callId: string;
  chatId: string;
  isCurrent: () => boolean;
  send: (message: Record<string, unknown>) => boolean;
}

export async function applyVoiceToolEvent(binding: VoiceToolBinding,
  message: Record<string, unknown>): Promise<string | undefined> {
  if (!binding.isCurrent() || message.call_id !== binding.callId ||
      typeof message.function_call_id !== 'string' ||
      typeof message.assistant_message_id !== 'string' || typeof message.user_message_id !== 'string') return;
  const payload = message.payload;
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return;
  const data = payload as Record<string, unknown>;
  if (data.chat_id !== undefined && data.chat_id !== binding.chatId) throw new Error('Call tool chat mismatch');
  const { chatSyncService } = await import('./chatSyncService');
  // A tool result admitted before teardown has already committed. Persist its
  // artifact even when speech or the call ends while shared encryption loads.
  if (!binding.isCurrent() && message.type !== 'voice_embed') return;
  switch (message.type) {
    case 'voice_memory': {
      if (typeof data.request_id !== 'string' || !Array.isArray(data.requested_keys) ||
          !data.requested_keys.every((key) => typeof key === 'string')) throw new Error('Invalid memory request');
      const { handleRequestAppSettingsMemoriesImpl } = await import('./chatSyncServiceHandlersAppSettings');
      let submitted = false;
      await handleRequestAppSettingsMemoriesImpl(chatSyncService, {
        request_id: data.request_id, chat_id: binding.chatId,
        requested_keys: (data.requested_keys as string[]).map((key) => key.replace(':', '-')),
        yaml_content: typeof data.yaml_content === 'string' ? data.yaml_content : '',
        message_id: message.user_message_id,
      }, async (entries: MemoryPermissionResponse) => {
        if (submitted || !binding.isCurrent()) throw new Error('Voice memory request is no longer active');
        submitted = true;
        if (!binding.send({ type: 'voice_memory_response',
          call_id: binding.callId, function_call_id: message.function_call_id,
          request_id: data.request_id, approved: entries.length > 0, settings_memories: entries })) {
          throw new Error('Voice memory request is no longer active');
        }
      });
      return;
    }
    case 'voice_focus': {
      if (typeof data.focus_id !== 'string') throw new Error('Invalid focus event');
      if (data.event === 'focus_mode_pending' || data.event_for_client === 'focus_mode_pending') {
        if (typeof data.embed_id !== 'string' || typeof data.expires_at !== 'number') throw new Error('Invalid focus proposal');
        const { pendingFocusActivationStore } = await import('../stores/pendingFocusActivationStore');
        pendingFocusActivationStore.set(data.embed_id, { chatId: binding.chatId,
          focusId: data.focus_id, expiresAt: data.expires_at * 1000,
          selectedSpecialist: data.selected_specialist as Parameters<typeof pendingFocusActivationStore.set>[1]['selectedSpecialist'],
          activationPolicy: data.activation_policy === 'approval' || data.activation_policy === 'immediate'
            ? data.activation_policy : 'delayed' });
      } else if (data.event === 'focus_mode_activated' || data.event_for_client === 'focus_mode_activated') {
        await chatSyncService.applyConfirmedFocusActivation(binding.chatId, data.focus_id,
          typeof data.focus_mode_name === 'string' ? data.focus_mode_name : undefined);
      } else throw new Error('Unknown focus event');
      return;
    }
    case 'voice_embed': {
      if (typeof data.embed_id === 'string' && typeof data.embed_reference === 'string' && data.content === undefined) {
        const reference = parseVoiceArtifactReference(data.embed_reference, data.embed_id);
        if (!reference) throw new Error('Invalid call artifact reference');
        // EmbedService already emitted the full content on the ordinary sync
        // socket; this call event binds its reference to the issued response.
        return data.embed_id;
      }
      if (typeof data.embed_id !== 'string' || typeof data.content !== 'string' ||
          typeof data.type !== 'string' || typeof data.status !== 'string' ||
          data.message_id !== undefined && data.message_id !== message.assistant_message_id) {
        throw new Error('Invalid call artifact');
      }
      const { handleSendEmbedDataImpl } = await import('./chatSyncServiceHandlersAI');
      // Shared handler performs chat-key verification, encryption and durable
      // embed journaling. Routing always uses the issued call response identity.
      await handleSendEmbedDataImpl(chatSyncService, { type: 'send_embed_data',
        event_for_client: 'send_embed_data', payload: { ...data, chat_id: binding.chatId,
          message_id: message.assistant_message_id } } as SendEmbedDataPayload);
      return typeof data.parent_embed_id === 'string' ? undefined : data.embed_id;
    }
    case 'voice_context': {
      const { handleChatContextApplied } = await import('./chatSyncServiceHandlersAgentContext');
      const event = data.event;
      if (!event || typeof event !== 'object' || Array.isArray(event)) throw new Error('Invalid context receipt');
      await handleChatContextApplied(chatSyncService, { chat_id: binding.chatId,
        event: { ...(event as Record<string, unknown>), chat_id: binding.chatId,
          assistant_message_id: message.assistant_message_id, user_message_id: message.user_message_id } });
      return;
    }
    case 'voice_tool_status':
      chatSyncService.dispatchEvent(new CustomEvent('voiceToolStatus', { detail: {
        ...data, chat_id: binding.chatId, call_id: binding.callId,
        assistant_message_id: message.assistant_message_id,
      } }));
  }
}

/** Confirm canonical encrypted storage before Live adopts a new summary prefix. */
export async function applyVoiceCompression(binding: VoiceToolBinding,
  message: Record<string, unknown>): Promise<void> {
  if (!binding.isCurrent() || message.call_id !== binding.callId) return;
  const payload = message.payload;
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('Invalid call compression');
  const data = payload as Record<string, unknown>;
  if (data.chat_id !== binding.chatId || typeof data.task_id !== 'string' ||
      typeof data.summary_message_id !== 'string' || typeof data.summary_content !== 'string' ||
      data.summary_content.length > 48_000 || !Array.isArray(data.covered_message_ids) ||
      !data.covered_message_ids.every((id) => typeof id === 'string') ||
      typeof data.compressed_up_to_message_id !== 'string' || !Number.isSafeInteger(data.compressed_up_to_timestamp)) {
    throw new Error('Invalid call compression boundary');
  }
  const [{ chatSyncService }, { persistClientEncryptedCompressionCheckpoint }] = await Promise.all([
    import('./chatSyncService'), import('./chatSyncServiceHandlersAI'),
  ]);
  if (!binding.isCurrent()) return;
  await persistClientEncryptedCompressionCheckpoint(data as Parameters<typeof persistClientEncryptedCompressionCheckpoint>[0], chatSyncService);
  if (binding.isCurrent() && !binding.send({ type: 'voice_compression_confirmed', call_id: binding.callId,
    checkpoint_id: data.summary_message_id })) throw new Error('Call compression confirmation failed');
}
