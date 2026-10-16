import { writable } from 'svelte/store';
import type { VoiceCallStatus } from '../../services/voiceCall';

function fixture(status: VoiceCallStatus, showClose = true, showCall = true) {
  const callState = writable({ status });
  return {
    callState, showCall, showClose,
    onToggleCall: () => callState.update(({ status }) => ({
      status: status === 'connecting' || status === 'live' ? 'ended' : 'connecting',
    })),
    onClose: () => window.dispatchEvent(new CustomEvent('voice-call-preview-close')),
  };
}

export default fixture('idle');
export const variants = {
  connecting: fixture('connecting'),
  live: fixture('live'),
  newChat: fixture('idle', false),
  unavailable: fixture('idle', true, false),
};
