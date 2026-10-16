/** First-party, server-profile acknowledgement before any voice capture. */
import { mount, unmount } from 'svelte';
import { getApiUrl } from '../config/api';
import VoiceCallPrivacyDialog from '../components/voicecall/VoiceCallPrivacyDialog.svelte';

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

/** Always check the authoritative profile so another session/device is remembered. */
export async function ensureVoiceCallPrivacyAcknowledgement(signal: AbortSignal, onContinueGesture: () => void): Promise<boolean> {
  if (signal.aborted) return false;
  const profile = await acknowledgement(signal, false);
  if (signal.aborted) return false;
  if (profile.acknowledged) return true;
  return new Promise<boolean>((resolve, reject) => {
    let dialog: ReturnType<typeof mount> | null = null;
    let settled = false;
    const finish = (accepted: boolean) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener('abort', cancel);
      if (dialog) void unmount(dialog);
      resolve(accepted);
    };
    const cancel = () => finish(false);
    try {
      dialog = mount(VoiceCallPrivacyDialog, { target: document.body, props: {
        onCancel: cancel,
        onContinue: async () => {
          if (settled || signal.aborted) return;
          onContinueGesture();
          const saved = await acknowledgement(signal, true);
          if (!saved.acknowledged) throw new Error('Voice privacy acknowledgement was not saved');
          if (!signal.aborted) finish(true);
        },
      } });
      signal.addEventListener('abort', cancel, { once: true });
      if (signal.aborted) cancel();
    } catch (error) { reject(error); }
  });
}
