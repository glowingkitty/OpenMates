/** First-party, server-profile acknowledgement before any voice capture. */
import { get } from 'svelte/store';
import { text } from '../i18n/translations';
import { notificationStore } from '../stores/notificationStore';
import { getApiUrl } from '../config/api';

interface ProcessingAcknowledgement { version: 1; acknowledged: boolean; acknowledged_at: number | null }
async function acknowledgement(signal: AbortSignal, save: boolean): Promise<ProcessingAcknowledgement> {
  const response = await fetch(`${getApiUrl()}/v1/settings/voice-google-processing-ack`, {
    method: save ? 'POST' : 'GET', credentials: 'include', signal,
    ...(save ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ version: 1 }) } : {}),
  });
  if (!response.ok) throw new Error('Voice privacy acknowledgement unavailable');
  const result = await response.json() as ProcessingAcknowledgement;
  if (result.version !== 1 || typeof result.acknowledged !== 'boolean' ||
      (result.acknowledged ? !Number.isSafeInteger(result.acknowledged_at) || result.acknowledged_at! <= 0 : result.acknowledged_at !== null)) {
    throw new Error('Invalid voice privacy acknowledgement');
  }
  return result;
}

let requestInProgress = false;

/** Always check the authoritative profile; share the existing global notification UI. */
export async function ensureVoiceCallPrivacyAcknowledgement(signal: AbortSignal, onContinueGesture: () => void): Promise<boolean> {
  if (signal.aborted || requestInProgress) return false;
  requestInProgress = true;
  try {
    const profile = await acknowledgement(signal, false);
    if (signal.aborted) return false;
    if (profile.acknowledged) return true;
    return await new Promise<boolean>((resolve) => {
      let settled = false;
      let saving = false;
      let notificationId = '';
      let unsubscribe = () => {};
      const translate = get(text);
      const finish = (accepted: boolean) => {
        if (settled) return;
        settled = true;
        signal.removeEventListener('abort', cancel);
        unsubscribe?.();
        if (notificationId) notificationStore.removeNotification(notificationId);
        resolve(accepted);
      };
      const cancel = () => finish(false);
      notificationId = notificationStore.addNotificationWithOptions('info', {
        title: translate('voicecall.privacy_title'),
        message: translate('voicecall.privacy_description'),
        messageLink: { href: 'https://ai.google.dev/gemini-api/terms#paid-services', label: translate('voicecall.privacy_terms') },
        duration: 0,
        dismissible: true,
        dedupeKey: 'voice-call-privacy',
        keepOnAction: true,
        actionLabel: translate('voicecall.privacy_continue'),
        secondaryActionLabel: translate('common.cancel'),
        onSecondaryAction: cancel,
        onAction: async () => {
          if (settled || saving || signal.aborted) return;
          saving = true;
          notificationStore.updateNotification(notificationId!, {
            isProcessing: true, actionsDisabled: true,
            actionLabel: translate('voicecall.privacy_saving'), messageSecondary: undefined,
          });
          try {
            // Warm playback during this click, before the profile POST yields.
            onContinueGesture();
            const saved = await acknowledgement(signal, true);
            if (!saved.acknowledged) throw new Error('Voice privacy acknowledgement was not saved');
            if (!signal.aborted) finish(true);
          } catch {
            if (!settled && !signal.aborted) notificationStore.updateNotification(notificationId!, {
              messageSecondary: translate('voicecall.privacy_save_failed'),
            });
          } finally {
            saving = false;
            if (!settled) notificationStore.updateNotification(notificationId!, {
              isProcessing: false, actionsDisabled: false, actionLabel: translate('voicecall.privacy_continue'),
            });
          }
        },
      });
      unsubscribe = notificationStore.subscribe(state => {
        const owned = state.notifications.find(notification => notification.id === notificationId);
        if (!owned || owned.isExiting) finish(false);
      });
      // A store may synchronously remove the notice during initial subscription.
      if (settled) { unsubscribe(); return; }
      signal.addEventListener('abort', cancel, { once: true });
      if (signal.aborted) cancel();
    });
  } finally {
    requestInProgress = false;
  }
}
