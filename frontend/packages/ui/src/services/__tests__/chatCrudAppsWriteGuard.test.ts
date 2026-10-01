import { describe, expect, it, vi } from "vitest";
import { writable } from "svelte/store";

vi.mock("../../stores/signupState", () => ({
  forcedLogoutInProgress: writable(false), isLoggingOut: writable(false),
}));
vi.mock("../../demo_chats/convertToChat", () => ({ isPublicChat: () => true }));
vi.mock("../anonymousChatIds", () => ({ isAnonymousChatId: () => false }));

describe("Apps legacy chat metadata write guard", () => {
  // contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
  it("rejects an account switch after transaction setup but before the IndexedDB put", async () => {
    const { addChat } = await import("../db/chatCrudOperations");
    let releaseTransaction: ((value: unknown) => void) | undefined;
    const put = vi.fn();
    const transaction = { objectStore: () => ({ put }), error: null };
    const db = {
      db: {} as IDBDatabase,
      CHATS_STORE_NAME: "chats",
      init: vi.fn(async () => {}),
      getTransaction: vi.fn(() => new Promise((resolve) => { releaseTransaction = resolve; })),
    };
    let activeUser = "account-a";
    const saving = addChat(db as never, {
      chat_id: "demo-apps-legacy-guard", encrypted_title: "ciphertext", created_at: 1, updated_at: 1,
    } as never, undefined, {
      isFromSync: true,
      writeGuard: () => { if (activeUser !== "account-a") throw new Error("account changed"); },
    });
    await vi.waitFor(() => expect(releaseTransaction).toBeTypeOf("function"));
    activeUser = "account-b";
    releaseTransaction?.(transaction);
    await expect(saving).rejects.toThrow("account changed");
    expect(put).not.toHaveBeenCalled();
  });
});
