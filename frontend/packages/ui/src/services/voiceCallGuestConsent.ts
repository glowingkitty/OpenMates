/**
 * Guest voice-call privacy notice. Signed-out visitors cannot save the profile
 * acknowledgement the signed-in call uses, so a version-3 acknowledgement is kept
 * in localStorage. It reuses the signed-in call's notice texts and Continue UI
 * (see voiceCallPrivacy.ts). No acknowledgement means no microphone and no socket.
 */
import { get } from 'svelte/store';
import { text } from '../i18n/translations';
import { notificationStore } from '../stores/notificationStore';
import { externalLinks } from '../config/links';

export const GUEST_VOICE_ACK_KEY = 'openmates.guestVoiceAck.v3';

/** A failed read (storage blocked, corrupt value) means: ask again. */
export function hasGuestVoiceAck(): boolean {
  try { return localStorage.getItem(GUEST_VOICE_ACK_KEY) === '3'; }
  catch { return false; }
}

function saveGuestVoiceAck(): boolean {
  try { localStorage.setItem(GUEST_VOICE_ACK_KEY, '3'); return true; }
  catch { return false; }
}

/** Resolves true when acknowledged (now or earlier). `onContinueGesture` runs inside the click. */
export function ensureGuestVoiceAck(signal: AbortSignal, onContinueGesture: () => void): Promise<boolean> {
  if (signal.aborted) return Promise.resolve(false);
  if (hasGuestVoiceAck()) return Promise.resolve(true);
  return new Promise<boolean>((resolve) => {
    let settled = false;
    let notificationId = '';
    let unsubscribe = () => {};
    const translate = get(text);
    const finish = (accepted: boolean) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener('abort', cancel);
      unsubscribe();
      if (notificationId) notificationStore.removeNotification(notificationId);
      resolve(accepted);
    };
    const cancel = () => finish(false);
    notificationId = notificationStore.addNotificationWithOptions('info', {
      title: translate('voicecall.privacy_title'),
      message: translate('voicecall.privacy_description'),
      messageLink: { href: externalLinks.legal.privacyPolicy, label: translate('voicecall.privacy_terms') },
      duration: 0,
      dismissible: true,
      dedupeKey: 'voice-call-privacy',
      keepOnAction: true,
      actionLabel: translate('voicecall.privacy_continue'),
      secondaryActionLabel: translate('common.cancel'),
      onSecondaryAction: cancel,
      onAction: () => {
        if (settled || signal.aborted) return;
        onContinueGesture();
        // Storage may be blocked: the call still proceeds this time, and asks again next time.
        saveGuestVoiceAck();
        finish(true);
      },
    });
    unsubscribe = notificationStore.subscribe(state => {
      const owned = state.notifications.find(notification => notification.id === notificationId);
      if (!owned || owned.isExiting) finish(false);
    });
    if (settled) { unsubscribe(); return; }
    signal.addEventListener('abort', cancel, { once: true });
  });
}
