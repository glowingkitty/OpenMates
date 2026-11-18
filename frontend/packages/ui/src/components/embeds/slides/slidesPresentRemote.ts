/**
 * frontend/packages/ui/src/components/embeds/slides/slidesPresentRemote.ts
 *
 * Thin shell glue for the slides presentation remote. Encryption and ordering
 * (stale/duplicate refusal) belong to the Rust core, reached through
 * presentRemoteClient; this module only numbers frames, sends them over the
 * websocket relay and hands accepted frames to a callback.
 * Spec: slides.present.remote-control, slides.present.remote-relay-private.
 */
import { webSocketService } from '../../../services/websocketService';
import {
  acceptPresentRemoteState,
  decryptPresentRemoteState,
  encryptPresentRemoteState,
  type PresentRemoteOrigin,
  type PresentRemoteState
} from '../../../services/rustCore/presentRemote/presentRemoteClient';

export type { PresentRemoteState, PresentRemoteOrigin };

export const PRESENT_HEARTBEAT_MS = 10_000;
export const PRESENT_STALE_MS = 25_000;

const FRAME_TYPE = 'slides_present_state';
const REJECTED_FRAME_TYPE = 'slides_present_state_rejected';

export type PresentRemoteFields = Pick<PresentRemoteState, 'index' | 'step' | 'notesVisible' | 'presenting'>;

/** One sender per embed and device: its session id and increasing sequence. */
export interface PresentRemotePublisher {
  readonly sessionId: string;
  publish(fields: PresentRemoteFields): Promise<void>;
}

export function createPresentRemotePublisher(
  embedId: string,
  origin: PresentRemoteOrigin,
  sessionId: string = crypto.randomUUID()
): PresentRemotePublisher {
  let seq = 0;
  return {
    sessionId,
    async publish(fields) {
      seq += 1;
      const ciphertext = await encryptPresentRemoteState({ embedId, sessionId, seq, origin, ...fields });
      await webSocketService.sendMessage(FRAME_TYPE, { embed_id: embedId, ciphertext });
    }
  };
}

/**
 * Listens for frames of this embed from the user's other devices. Returns the
 * unsubscribe function. Frames the core refuses (stale, replayed, undecryptable)
 * are dropped.
 */
export function subscribePresentRemote(
  embedId: string,
  onState: (state: PresentRemoteState) => void
): () => void {
  const handler = async (payload: { embed_id?: string; ciphertext?: string }) => {
    if (payload?.embed_id !== embedId || typeof payload.ciphertext !== 'string') return;
    let state: PresentRemoteState;
    try {
      state = await decryptPresentRemoteState(embedId, payload.ciphertext);
    } catch (error) {
      console.warn('[SlidesPresentRemote] Dropped a remote frame the core could not open.', error);
      return;
    }
    if (state.embedId !== embedId) return;
    if (await acceptPresentRemoteState(state)) onState(state);
  };
  const rejected = (payload: { embed_id?: string; code?: string }) => {
    if (payload?.embed_id !== embedId) return;
    console.warn(`[SlidesPresentRemote] The relay refused a frame: ${payload.code ?? 'unknown'}.`);
  };
  webSocketService.on(FRAME_TYPE, handler);
  webSocketService.on(REJECTED_FRAME_TYPE, rejected);
  return () => {
    webSocketService.off(FRAME_TYPE, handler);
    webSocketService.off(REJECTED_FRAME_TYPE, rejected);
  };
}

/**
 * Follows the presenter of an embed: `live` is true while a presenter state
 * arrived within PRESENT_STALE_MS and says presenting.
 */
export function watchPresenter(
  embedId: string,
  onChange: (live: boolean, state: PresentRemoteState | null) => void
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const expire = () => onChange(false, null);
  const unsubscribe = subscribePresentRemote(embedId, (state) => {
    clearTimeout(timer);
    if (state.origin !== 'presenter') return;
    if (!state.presenting) return onChange(false, state);
    onChange(true, state);
    timer = setTimeout(expire, PRESENT_STALE_MS);
  });
  return () => {
    clearTimeout(timer);
    unsubscribe();
  };
}
