// frontend/packages/ui/src/components/activeChatScrollKeeper.ts
//
// Keeps the chat reading position while a pane (the workflow editor opened
// from a chat recommendation) sits beside or over the chat. At >= 1024px the
// chat shrinks to its 400px split column, which reflows the history and moves
// its scroll offset; below that the pane only covers the chat. ActiveChat
// reports the pane's chat id on every change; the keeper records the history
// scroll offset when the pane opens and, when it closes in the same chat, puts
// the history back after the split exit animation has settled: the same
// offset, or the newest message when the user was at the bottom and new
// messages arrived meanwhile.

import { tick } from 'svelte';

/** Same tolerance ChatHistory uses for "scrolled to the bottom". */
const AT_BOTTOM_TOLERANCE_PX = 50;
/** Frames to wait for the split exit animation (ActiveChat falls back after 1s). */
const MAX_SETTLE_FRAMES = 90;
const HISTORY_SELECTOR = '[data-testid="chat-history-container"]';
const EXITING_CLASS = 'side-by-side-exiting';

interface ChatScrollSnapshot {
  chatId: string;
  scrollTop: number;
  scrollHeight: number;
  atBottom: boolean;
}

export interface ChatScrollKeeper {
  /**
   * Report the chat the pane belongs to (null when it is closed). Call before
   * the DOM update that opens or closes the pane (`$effect.pre`).
   */
  update(paneChatId: string | null, currentChatId: string | null, chatPane: HTMLElement | null, scrollToBottom: () => void): void;
}

function historyContainer(chatPane: HTMLElement | null): HTMLElement | null {
  return chatPane?.querySelector<HTMLElement>(HISTORY_SELECTOR) ?? null;
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

/** Finite animations and transitions running on the chat pane element itself. */
function layoutAnimations(chatPane: HTMLElement): Animation[] {
  return chatPane.getAnimations().filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity);
}

/** Resolves once the chat pane runs no layout animation and has left its split exit state. */
async function layoutSettled(chatPane: HTMLElement): Promise<void> {
  await tick();
  for (let frame = 0; frame < MAX_SETTLE_FRAMES; frame += 1) {
    await Promise.allSettled(layoutAnimations(chatPane).map((animation) => animation.finished));
    await nextFrame();
    if (!chatPane.classList.contains(EXITING_CLASS) && layoutAnimations(chatPane).length === 0) return;
  }
}

async function restore(snapshot: ChatScrollSnapshot, chatPane: HTMLElement, scrollToBottom: () => void): Promise<void> {
  await layoutSettled(chatPane);
  const container = historyContainer(chatPane);
  if (!container) return;
  if (snapshot.atBottom && container.scrollHeight !== snapshot.scrollHeight) scrollToBottom();
  else container.scrollTop = snapshot.scrollTop;
}

export function createChatScrollKeeper(): ChatScrollKeeper {
  let snapshot: ChatScrollSnapshot | null = null;
  return {
    update(paneChatId, currentChatId, chatPane, scrollToBottom) {
      if (paneChatId) {
        if (snapshot?.chatId === paneChatId) return;
        const container = historyContainer(chatPane);
        snapshot = container
          ? {
              chatId: paneChatId,
              scrollTop: container.scrollTop,
              scrollHeight: container.scrollHeight,
              atBottom: container.scrollHeight - container.scrollTop - container.clientHeight < AT_BOTTOM_TOLERANCE_PX
            }
          : null;
        return;
      }
      const closed = snapshot;
      snapshot = null;
      // Leaving the chat closes the pane too; the new chat restores its own position.
      if (!closed || !chatPane || closed.chatId !== currentChatId) return;
      void restore(closed, chatPane, scrollToBottom);
    }
  };
}
