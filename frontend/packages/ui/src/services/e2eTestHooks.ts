/**
 * Dev-only E2E browser hooks for Playwright readiness and fixture seeding.
 *
 * These hooks are installed only on localhost/dev hosts. They expose small,
 * explicit test-only probes on window without initializing the full app twice.
 * Production hosts never receive these globals.
 */
import { get } from 'svelte/store';
import { chatDB } from './db';
import { draftEditorUIState } from './drafts/draftState';

export type E2EDraftSelectionDecision = {
  chatId: string;
  consumer: 'active_chat' | 'chat_list';
  result: 'applied' | 'paused' | 'skipped';
};

type E2EDraftSelectionGate = {
  promise: Promise<void>;
  release: () => void;
};

function isE2EHost(): boolean {
  return typeof window !== 'undefined' && (
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1' ||
    window.location.hostname.endsWith('.dev.openmates.org')
  );
}

export function recordE2EDraftSelectionDecision(decision: E2EDraftSelectionDecision): void {
  if (!isE2EHost()) return;
  const testWindow = window as unknown as {
    __openmatesE2EDraftSelectionTrace?: E2EDraftSelectionDecision[];
  };
  testWindow.__openmatesE2EDraftSelectionTrace?.push(decision);
}

export async function waitForE2EDraftSelectionCommit(
  chatId: string,
  consumer: E2EDraftSelectionDecision['consumer'],
): Promise<void> {
  if (!isE2EHost()) return;
  const testWindow = window as unknown as {
    __openmatesE2EDraftSelectionGate?: E2EDraftSelectionGate;
  };
  const gate = testWindow.__openmatesE2EDraftSelectionGate;
  if (!gate) return;
  recordE2EDraftSelectionDecision({ chatId, consumer, result: 'paused' });
  await gate.promise;
}

export async function installE2ETestHooks() {
  if (typeof window === 'undefined') return;
  const isDevHost =
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1' ||
    window.location.hostname.endsWith('.dev.openmates.org');
  if (!isDevHost) return;

  const testWindow = window as unknown as {
    __openmatesE2ESeedChat?: (input: {
      chat: Record<string, unknown>;
      messages: Record<string, unknown>[];
    }) => Promise<{ chatId: string; messageCount: number }>;
    __openmatesE2EChatConnectionState?: () => Promise<{
      online: boolean;
      websocketConnected: boolean;
      cachePrimed: boolean;
    }>;
    __openmatesE2EReplayDraftSelection?: (chatId: string, pauseBeforeCommit?: boolean) => void;
    __openmatesE2EReleaseDraftSelection?: () => void;
    __openmatesE2EDraftSelectionGate?: E2EDraftSelectionGate;
    __openmatesE2EDraftSelectionTrace?: E2EDraftSelectionDecision[];
    __openmatesE2EDraftState?: () => Record<string, unknown>;
  };

  testWindow.__openmatesE2ESeedChat = async ({ chat, messages }) => {
    const chatId = String(chat.chat_id || '');
    if (!chatId.startsWith('e2e-')) {
      throw new Error('E2E seed chat IDs must start with e2e-');
    }

    const { chatKeyManager } = await import('./encryption/ChatKeyManager');
    chatKeyManager.createKeyForNewChat(chatId);
    await chatDB.addChat(chat as unknown as Parameters<typeof chatDB.addChat>[0]);
    for (const message of messages) {
      await chatDB.saveMessage(
        message as unknown as Parameters<typeof chatDB.saveMessage>[0],
      );
    }
    window.dispatchEvent(new CustomEvent('localChatListChanged', { detail: { chat_id: chatId } }));
    return { chatId, messageCount: messages.length };
  };

  testWindow.__openmatesE2EChatConnectionState = async () => {
    const { chatSyncService } = await import('./chatSyncService');
    return {
      online: window.navigator.onLine,
      websocketConnected: chatSyncService.webSocketConnected_FOR_SENDERS_ONLY,
      cachePrimed: chatSyncService.cachePrimed_FOR_HANDLERS_ONLY,
    };
  };

  testWindow.__openmatesE2EReplayDraftSelection = (chatId: string, pauseBeforeCommit = false) => {
    testWindow.__openmatesE2EDraftSelectionTrace = [];
    if (pauseBeforeCommit) {
      let release = () => undefined;
      const promise = new Promise<void>((resolve) => {
        release = resolve;
      });
      testWindow.__openmatesE2EDraftSelectionGate = { promise, release };
    }
    draftEditorUIState.update((state) => ({
      ...state,
      newlyCreatedChatIdToSelect: chatId,
    }));
  };

  testWindow.__openmatesE2EReleaseDraftSelection = () => {
    testWindow.__openmatesE2EDraftSelectionGate?.release();
    delete testWindow.__openmatesE2EDraftSelectionGate;
  };

  testWindow.__openmatesE2EDraftState = () => structuredClone(
    get(draftEditorUIState) as unknown as Record<string, unknown>,
  );
}
