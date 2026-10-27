// contract-test-file: infrastructure
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../message_parsing/utils", () => ({
  computeSHA256: async (value: string) => `hash:${value}`,
}));
vi.mock("../../recentChatWindowCache", () => ({ invalidateRecentChatWindow: vi.fn() }));
vi.mock("../../cryptoService", () => ({
  encryptChatKeyWithMasterKey: vi.fn(), decryptChatKeyWithMasterKey: vi.fn(),
}));
vi.mock("../../encryption/ChatKeyManager", () => ({
  chatKeyManager: {getKey:vi.fn(async()=>new Uint8Array(32))}, computeKeyFingerprint: vi.fn(),
}));
vi.mock("../../anonymousChatKeyWrapping", () => ({ unwrapAnonymousChatKey: vi.fn() }));
vi.mock("../../chatKeyConsistency", () => ({ chatKeysEqual: vi.fn() }));
vi.mock("../../../stores/signupState", () => ({
  forcedLogoutInProgress: {}, isLoggingOut: {},
}));
vi.mock("../../../demo_chats/convertToChat", () => ({ isPublicChat: vi.fn() }));
vi.mock("../../anonymousChatIds", () => ({ isAnonymousChatId: vi.fn() }));
vi.mock("../../teamService", () => ({
  unwrapTeamChatKey: vi.fn(), wrapTeamChatKey: vi.fn(),
}));

vi.mock("../../encryption/MessageEncryptor",()=>({decryptWithChatKey:async(value:string)=>value}));

import { deleteEmptyVoiceCallChat, deleteChatIfNoPendingTurn, deleteDraftOnlyChat } from "../chatCrudOperations";

function guardedDeletionDb(pendingTurn: boolean) {
  let currentChat: Record<string, unknown> | undefined;
  let hasMessage = false;
  const head = {
    contentRef: "embed:artifact", embed_id: "artifact", hashed_chat_id: "hash:draft-chat",
    encrypted_content: "sealed head", version_number: 1,
  };
  const wrappers = [
    { id: "master", key_type: "master", hashed_embed_id: "hash:artifact", hashed_chat_id: null },
    { id: "chat", key_type: "chat", hashed_embed_id: "hash:artifact", hashed_chat_id: "hash:draft-chat" },
  ];
  const writes: string[] = [];
  const request = <T>(result: T) => {
    const item = { result, error: null, onsuccess: null as (() => void) | null,
      onerror: null as (() => void) | null };
    queueMicrotask(() => item.onsuccess?.());
    return item;
  };
  const candidate = {
    objectStore: (name: string) => {
      expect(name).toBe("embeds");
      return { index: () => ({ getAll: () => request([head]) }) };
    },
  };
  const writer = {
    error: null,
    oncomplete: null as (() => void) | null,
    onerror: null as (() => void) | null,
    onabort: null as (() => void) | null,
    abort: vi.fn(),
    objectStore: (name: string) => {
      if (name === "messages") return {
        index: (indexName: string) => ({ openCursor: () => {
          if (indexName === "pending_turn_created_at_message_id") {
            return request(pendingTurn ? { value: {
              chat_id: "draft-chat", pending_encrypted_turn_preflight_v1: "sealed journal",
            } } : null);
          }
          expect(indexName).toBe("chat_id");
          return request(hasMessage ? { value: { message_id: "first-message" } } : null);
        } }),
      };
      if (name === "chats") return { get: () => request(currentChat), delete: (id: string) => { writes.push(`chat:${id}`); return request(undefined); } };
      if (name === "embeds") return {
        index: () => ({ getAll: () => request([head]) }),
        delete: (id: string) => { writes.push(`head:${id}`); return request(undefined); },
      };
      if (name === "embed_keys") return {
        index: () => ({ getAll: () => request(wrappers) }),
        delete: (id: string) => { writes.push(`key:${id}`); return request(undefined); },
      };
      throw new Error(`Unexpected store ${name}`);
    },
  };
  const db = {
    CHATS_STORE_NAME: "chats", init: async () => undefined,
    getTransaction: vi.fn(async (_stores: string | string[], mode: string) => {
      if (mode === "readonly") return candidate;
      expect(_stores).toEqual(["chats", "messages", "embeds", "embed_keys"]);
      return writer;
    }),
  };
  return { db, writer, writes, commit: (chat: Record<string, unknown>, message = false) => {
    currentChat = chat; hasMessage = message;
  } };
}

afterEach(() => vi.unstubAllGlobals());

describe("inferred Phase 2 chat deletion", () => {
  // contract-test: supporting surface=gui.web assertions=apps.requests.natural-language,chats.persistence.client-encrypted
  it.each(["header-before-message", "message-before-header"])("retains a first send committed after stale draft cleanup reads (%s)", async (interval) => {
    vi.stubGlobal("IDBKeyRange", { bound: () => ({}), only: () => ({}) });
    const { db, writer, writes, commit } = guardedDeletionDb(false);
    // The cleanup caller already observed a draft-only header + empty history.
    const draft = { chat_id: "draft-chat", messages_v: 0, draft_v: 1, encrypted_title: null };
    commit(draft);
    const deleting = deleteDraftOnlyChat(db as never, "draft-chat");
    // Commit while candidate embeds/crypto are prepared before the write lock.
    // New-chat addChat writes messages_v:1 BEFORE saveMessage; existing-draft
    // send writes its first message before updating the old draft-only header.
    commit(interval === "header-before-message"
      ? { ...draft, messages_v: 1, draft_v: 0, encrypted_chat_key: "first-send-wrapped-key" }
      : draft, interval === "message-before-header");
    await vi.waitFor(() => expect(writer.oncomplete).toBeTypeOf("function"));
    writer.oncomplete?.();
    expect(await deleting).toEqual({ deleted: false, deletedEmbedIds: [] });
    expect(writes).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
  it("deletes a genuinely empty draft shell and its unshared embeds", async () => {
    vi.stubGlobal("IDBKeyRange", { bound: () => ({}), only: () => ({}) });
    const { db, writer, writes, commit } = guardedDeletionDb(false);
    commit({ chat_id: "draft-chat", messages_v: 0, draft_v: 0, encrypted_title: null });
    const deleting = deleteDraftOnlyChat(db as never, "draft-chat");
    await vi.waitFor(() => expect(writes).toContain("chat:draft-chat"));
    writer.oncomplete?.();
    expect(await deleting).toEqual({ deleted: true, deletedEmbedIds: ["artifact"] });
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
  it("retains the complete encrypted draft when a pending journal appears before the write transaction", async () => {
    vi.stubGlobal("IDBKeyRange", { bound: () => ({}), only: () => ({}) });
    const { db, writer, writes } = guardedDeletionDb(true);
    const result = deleteChatIfNoPendingTurn(db as never, "draft-chat");
    await vi.waitFor(() => expect(writer.oncomplete).toBeTypeOf("function"));
    writer.oncomplete?.();
    expect(await result).toEqual({ deleted: false, deletedEmbedIds: [] });
    expect(writes).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("deletes an unpending inferred chat, its head, and wrappers inside one write transaction", async () => {
    vi.stubGlobal("IDBKeyRange", { bound: () => ({}), only: () => ({}) });
    const { db, writer, writes } = guardedDeletionDb(false);
    const result = deleteChatIfNoPendingTurn(db as never, "draft-chat");
    await vi.waitFor(() => expect(writes).toContain("chat:draft-chat"));
    expect(writes).toEqual(expect.arrayContaining([
      "chat:draft-chat", "head:embed:artifact", "key:master", "key:chat",
    ]));
    writer.oncomplete?.();
    expect(await result).toEqual({ deleted: true, deletedEmbedIds: ["artifact"] });
  });
});


describe('atomic empty-call local deletion',()=>{
  // contract-test: supporting surface=gui.web assertions=video-call.chat.call-events,video-call.lifecycle.recovery-and-billing
  it.each(['empty','new-message','new-draft','pending-turn','new-artifact','editor-race','ciphertext-race','owner-race'])(
    'retains newer local state under the write lock (%s)',async scenario=>{
      vi.stubGlobal('IDBKeyRange',{bound:()=>({}),only:()=>({})});
      const callId='0123456789abcdef0123456789abcdef';
      let chat:Record<string,unknown>={chat_id:'call-chat',messages_v:2,draft_v:0};
      const rows:Array<Record<string,unknown>>=['started','ended'].map(action=>({
        message_id:`${action==='started'?'00000000':'ffffffff'}-voice-call-${callId}-${action}`,
        chat_id:'call-chat',role:'system',status:'synced',encrypted_content:JSON.stringify({
          schema_version:1,type:'voice_call',action,call_id:callId,created_at:1700000000,active_elapsed_seconds:0}),
      }));
      const writes:string[]=[];let locked=false;
      const req=<T>(result:T)=>{const request={result,onsuccess:null as null|(()=>void),onerror:null as null|(()=>void)};
        queueMicrotask(()=>request.onsuccess?.());return request;};
      const writer={oncomplete:null as null|(()=>void),onerror:null as null|(()=>void),onabort:null as null|(()=>void),error:null,
        abort:vi.fn(),objectStore:(name:string)=>{
          if(name==='chats')return {get:()=>req(chat),delete:(id:string)=>{writes.push(id);return req(undefined);}};
          if(name==='messages')return {index:(index:string)=>({openCursor:()=>{
            if(index==='pending_turn_created_at_message_id')return req(null);
            let offset=0;const request={result:null as unknown,onsuccess:null as null|(()=>void),onerror:null};
            const advance=()=>{request.result=offset<rows.length?{value:rows[offset++],continue:()=>queueMicrotask(advance),
              delete:()=>writes.push('message')}:null;request.onsuccess?.();};queueMicrotask(advance);return request;
          }})};
          return {count:()=>req(0),index:()=>({getAll:()=>req([]),count:()=>req(scenario==='new-artifact'?1:0)})};
        }};
      const db={CHATS_STORE_NAME:'chats',init:async()=>{},getTransaction:vi.fn(async(stores:string|string[],mode:string)=>{
        if(mode==='readwrite'){
          locked=true;
          if(scenario==='new-message')rows.push({message_id:'user',chat_id:'call-chat',role:'user',status:'sending'});
          if(scenario==='new-draft')chat={...chat,encrypted_draft_md:'new draft'};
          if(scenario==='ciphertext-race')rows[0]={...rows[0],encrypted_content:'new ciphertext'};
          if(scenario==='owner-race')chat={...chat,user_id:'another owner'};
          if(scenario==='pending-turn')rows[0]={...rows[0],pending_encrypted_turn_preflight_v1:'new journal'};
          return writer;
        }
        return {objectStore:(name:string)=>name==='chats'?{get:()=>req(structuredClone(chat))}:
          {index:()=>({getAll:()=>req(name==='messages'?structuredClone(rows):[])})}};
      })};
      const deletion=deleteEmptyVoiceCallChat(db as never,'call-chat',{callId,expectedMessagesVersion:2,
        isCurrent:()=>!(locked&&scenario==='editor-race')});
      await vi.waitFor(()=>expect(locked).toBe(true));
      // All IDB request callbacks settle before the synthetic transaction commits.
      await new Promise(resolve=>setTimeout(resolve,0));writer.oncomplete?.();
      expect((await deletion).deleted).toBe(scenario==='empty');
      expect(writes.length).toBe(scenario==='empty'?3:0);
    });
});
