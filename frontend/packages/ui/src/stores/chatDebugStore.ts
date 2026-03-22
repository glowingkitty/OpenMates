/**
 * Chat debug mode store.
 *
 * Controls whether messages render with full formatting (embeds, markdown, etc.)
 * or are displayed as raw plain text so developers can inspect JSON embed
 * placeholders, missing content, and other rendering issues.
 *
 * Architecture: global writable store; both ChatContextMenu and
 * MessageContextMenu toggle this flag. ChatMessage.svelte reads it to decide
 * whether to pass content to ReadOnlyMessage or render it as a <pre> block.
 *
 * To add more debug features in the future, extend the ChatDebugState
 * interface and initialise the new field to its default "off" value.
 */

import { writable } from "svelte/store";
import { get } from "svelte/store";
import { userProfile } from "./userProfile";
import { logCollector, type ConsoleLogEntry } from "../services/logCollector";

export interface ChatDebugState {
  /** When true, messages show raw plain text instead of rendered content. */
  rawTextMode: boolean;

  /** Last window.debug.chat output and the chat it belongs to. */
  chatReport: string | null;
  chatReportChatId: string | null;
  chatReportLoading: boolean;

  /** Last window.debug.embed output and the embed it belongs to. */
  embedReport: string | null;
  embedReportEmbedId: string | null;
  embedReportLoading: boolean;

  /** Live warn/error console logs captured while debug mode is active. */
  streamLogs: string[];

  // Future debug flags can be added here, e.g.:
  // showEmbedBoundaries: boolean;
  // disableEncryption: boolean;
}

export interface ChatDebugStoreApi {
  subscribe: (run: (value: ChatDebugState) => void) => () => void;
  toggle: (options?: { chatId?: string }) => Promise<void>;
  setRawTextMode: (
    enabled: boolean,
    options?: { chatId?: string },
  ) => Promise<void>;
  runChatDebug: (chatId: string) => Promise<void>;
  runEmbedDebug: (embedId: string) => Promise<void>;
  reset: () => void;
}

const INITIAL_STATE: ChatDebugState = {
  rawTextMode: false,
  chatReport: null,
  chatReportChatId: null,
  chatReportLoading: false,
  embedReport: null,
  embedReportEmbedId: null,
  embedReportLoading: false,
  streamLogs: [],
};

const MAX_STREAM_LOGS = 200;

let logListener: ((entry: ConsoleLogEntry) => void) | null = null;

interface WindowDebugAPI {
  chat: (chatId: string, options?: Record<string, unknown>) => Promise<string>;
  embed: (
    embedId: string,
    options?: Record<string, unknown>,
  ) => Promise<string>;
}

function isAdminUser(): boolean {
  return get(userProfile).is_admin === true;
}

function getWindowDebugApi(): WindowDebugAPI | null {
  if (typeof window === "undefined") return null;
  const maybeDebug = (window as unknown as { debug?: Partial<WindowDebugAPI> })
    .debug;
  if (!maybeDebug?.chat || !maybeDebug?.embed) return null;
  return maybeDebug as WindowDebugAPI;
}

function formatLog(entry: ConsoleLogEntry): string {
  const timestamp = new Date(entry.timestamp)
    .toISOString()
    .replace("T", " ")
    .slice(0, 23);
  return `[${timestamp}] ${entry.level.toUpperCase()} ${entry.message}`;
}

function createChatDebugStore(): ChatDebugStoreApi {
  const { subscribe, update, set } = writable<ChatDebugState>(INITIAL_STATE);

  userProfile.subscribe((profile) => {
    if (!profile.is_admin) {
      stopLogCapture();
      set(INITIAL_STATE);
    }
  });

  function stopLogCapture(): void {
    if (logListener) {
      logCollector.offNewLog(logListener);
      logListener = null;
    }
  }

  function startLogCapture(): void {
    stopLogCapture();

    const initialLogs = logCollector.getErrorLogs(50).map(formatLog);

    update((state) => ({
      ...state,
      streamLogs: initialLogs,
    }));

    logListener = (entry: ConsoleLogEntry) => {
      if (entry.level !== "warn" && entry.level !== "error") return;
      update((state) => {
        if (!state.rawTextMode) return state;
        const nextLogs = [...state.streamLogs, formatLog(entry)].slice(
          -MAX_STREAM_LOGS,
        );
        return { ...state, streamLogs: nextLogs };
      });
    };

    logCollector.onNewLog(logListener);
  }

  async function runChatDebug(chatId: string): Promise<void> {
    if (!chatId || !isAdminUser()) return;
    const debugApi = getWindowDebugApi();
    if (!debugApi) {
      update((state) => ({
        ...state,
        chatReportLoading: false,
        chatReportChatId: chatId,
        chatReport:
          "[debug mode] window.debug.chat is not available in this runtime.",
      }));
      return;
    }

    update((state) => ({
      ...state,
      chatReportLoading: true,
      chatReportChatId: chatId,
    }));

    try {
      const report = await debugApi.chat(chatId, {
        verbose: true,
        hideKeys: true,
      });
      update((state) => ({
        ...state,
        chatReportLoading: false,
        chatReportChatId: chatId,
        chatReport: report,
      }));
    } catch (error) {
      const errorText = error instanceof Error ? error.message : String(error);
      update((state) => ({
        ...state,
        chatReportLoading: false,
        chatReportChatId: chatId,
        chatReport: `[debug mode] window.debug.chat failed: ${errorText}`,
      }));
    }
  }

  async function runEmbedDebug(embedId: string): Promise<void> {
    if (!embedId || !isAdminUser()) return;
    const debugApi = getWindowDebugApi();
    if (!debugApi) {
      update((state) => ({
        ...state,
        embedReportLoading: false,
        embedReportEmbedId: embedId,
        embedReport:
          "[debug mode] window.debug.embed is not available in this runtime.",
      }));
      return;
    }

    update((state) => ({
      ...state,
      embedReportLoading: true,
      embedReportEmbedId: embedId,
    }));

    try {
      const report = await debugApi.embed(embedId, { full: true });
      update((state) => ({
        ...state,
        embedReportLoading: false,
        embedReportEmbedId: embedId,
        embedReport: report,
      }));
    } catch (error) {
      const errorText = error instanceof Error ? error.message : String(error);
      update((state) => ({
        ...state,
        embedReportLoading: false,
        embedReportEmbedId: embedId,
        embedReport: `[debug mode] window.debug.embed failed: ${errorText}`,
      }));
    }
  }

  async function setRawTextMode(
    enabled: boolean,
    options?: { chatId?: string },
  ): Promise<void> {
    if (!isAdminUser()) {
      stopLogCapture();
      set(INITIAL_STATE);
      return;
    }

    if (!enabled) {
      stopLogCapture();
      set(INITIAL_STATE);
      return;
    }

    set({ ...INITIAL_STATE, rawTextMode: true });
    startLogCapture();

    if (options?.chatId) {
      await runChatDebug(options.chatId);
    }
  }

  return {
    subscribe,

    async toggle(options?: { chatId?: string }): Promise<void> {
      const state = get({ subscribe });
      await setRawTextMode(!state.rawTextMode, options);
    },

    setRawTextMode,

    runChatDebug,

    runEmbedDebug,

    /** Toggle the entire debug mode on/off (resets all flags to their default state). */
    reset(): void {
      stopLogCapture();
      set(INITIAL_STATE);
    },
  };
}

export const chatDebugStore = createChatDebugStore();
