import { chatDB } from './db';
import type { Chat } from '../types/chat';

/** Canonical private-chat lookup used before committing a navigation. */
export const chatNavigationReader = {
  readChatForNavigation(chatId: string): Promise<Chat | null> {
    // Navigation completion has its own boundary, independent of database
    // initialization and native IDB callback/transaction lifetimes.
    return new Promise((resolve, reject) => {
      chatDB.getChat(chatId).then(resolve, reject);
    });
  },
};
