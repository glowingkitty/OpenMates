// Flag-off incognito updates stay synchronous between reading and replacing a row;
// flag-on (Worker answers) concurrent updates and inits stay consistent.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mode = vi.hoisted(() => ({ rust: false, calls: [] as string[], release: null as null | (() => void) }));

vi.mock("../shareState/decide", async (importOriginal) => {
  const real = await importOriginal<typeof import("../shareState/decide")>();
  return {
    ...real,
    shareStateClient: () => (mode.rust ? ({} as never) : null),
    decideShareState: async (op: string, input: never) => {
      mode.calls.push(op);
      if (mode.release === null) {
        await new Promise<void>((resolve) => { mode.release = resolve; });
      }
      return real.directShareState(op as never, input);
    },
  };
});

import { incognitoChatService } from "../incognitoChatService";
import type { Chat, Message } from "../../types/chat";

const row = (id: string, content: string) =>
  ({ chat_id: "incognito-1", message_id: id, role: "user", created_at: 1, status: "queued", content }) as Message;

async function seed(): Promise<void> {
  await incognitoChatService.storeChat({ chat_id: "incognito-1", is_incognito: true, created_at: 1, updated_at: 1 } as Chat);
  await incognitoChatService.addMessage("incognito-1", row("m1", "start"));
}

beforeEach(() => { mode.rust = false; mode.calls = []; mode.release = null; sessionStorage.clear(); });
afterEach(async () => { await incognitoChatService.deleteAllChats(); });

describe("incognito updateMessage ordering", () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it("flag off replaces the row in the same tick it was read, so concurrent updates chain", async () => {
    await seed();
    const seen: string[] = [];
    const bump = (suffix: string) => (current: Readonly<Message>) => {
      seen.push(String(current.content));
      return { ...current, content: `${String(current.content)}${suffix}` } as Message;
    };
    const results = await Promise.all([
      incognitoChatService.updateMessage("incognito-1", "m1", bump("+a")),
      incognitoChatService.updateMessage("incognito-1", "m1", bump("+b")),
    ]);
    expect(results).toEqual([true, true]);
    expect(seen).toEqual(["start", "start+a"]);
    expect((await incognitoChatService.getMessagesForChat("incognito-1"))[0].content).toBe("start+a+b");
    expect(mode.calls).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it("flag on re-finds the row after the Worker answer and reports a removed row as not updated", async () => {
    await seed();
    mode.rust = true;
    const pending = incognitoChatService.updateMessage("incognito-1", "m1", (current) => ({ ...current, content: "late" }) as Message);
    await vi.waitFor(() => expect(mode.calls).toContain("incognitoUpdateAccepted"));
    await incognitoChatService.deleteAllChats();
    mode.release!();
    expect(await pending).toBe(false);
  });
});

describe("incognito concurrent init", () => {
  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it("flag on shares one load between concurrent callers", async () => {
    sessionStorage.setItem("incognito_chats", JSON.stringify([{ chat_id: "incognito-9" }]));
    (incognitoChatService as unknown as { initialized: boolean }).initialized = false;
    mode.rust = true;
    const first = incognitoChatService.init();
    const second = incognitoChatService.init();
    await vi.waitFor(() => expect(mode.release).not.toBeNull());
    mode.release!();
    await Promise.all([first, second]);
    expect(mode.calls.filter((op) => op === "incognitoNormalize")).toHaveLength(1);
    expect((await incognitoChatService.getAllChats()).map((chat) => chat.chat_id)).toContain("incognito-9");
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it("flag off loads without any await window", async () => {
    sessionStorage.setItem("incognito_chats", JSON.stringify([{ chat_id: "incognito-8" }]));
    (incognitoChatService as unknown as { initialized: boolean }).initialized = false;
    const first = incognitoChatService.init();
    // The load has finished synchronously inside init(): the flag is already set.
    expect((incognitoChatService as unknown as { initialized: boolean }).initialized).toBe(true);
    await first;
    expect(mode.calls).toEqual([]);
  });
});
