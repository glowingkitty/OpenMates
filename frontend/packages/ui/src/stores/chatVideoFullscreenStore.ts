/**
 * chatVideoFullscreenStore.ts
 *
 * Generic fullscreen video store — works for any chat with a video in its
 * metadata (intro chats, announcements, tips & tricks). Replaces the old
 * intro-only introVideoFullscreenStore.
 *
 * ActiveChat reads from this store to render DirectVideoEmbedFullscreen.
 * ChatHeader and hash-routing write to it.
 */

import { writable } from "svelte/store";

export interface ChatVideoFullscreen {
  mp4Url: string;
  title: string;
  chatId: string;
}

export const chatVideoFullscreenStore =
  writable<ChatVideoFullscreen | null>(null);

export function openChatVideoFullscreen(data: ChatVideoFullscreen) {
  chatVideoFullscreenStore.set(data);
}

export function closeChatVideoFullscreen() {
  chatVideoFullscreenStore.set(null);
}
