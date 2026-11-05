import type { SavedPageSelector } from "./protocol";
import type { LocalCursorSelector, LocalReadPlan } from "./protocol";
/** Selected saved-view publication stays page-owned and synchronous.
 * Rust owns account admission, ciphertext decoding, PII and read/sync policy.
 * A profile witness only restricts an already-admitted session; it grants none.
 * Generic witnesses permit the genuine existing-key adapter without inventing
 * encrypted-email fields or requiring extractable keys. Known invalidations,
 * selection changes and cancellation remain fenced across every awaited step.
 */
import type { BrowserCoreWorkerHost } from "./workerHost";
import type { PriorProfileLifecycle } from "./platformLifecycle";
import type { SessionStatus } from "./protocol";
import type { SavedChatReadback, LocalChatReadback, CheckpointPresentation } from "./savedReadProtocol";

/** UI selection identity only. It cannot grant Rust account/workspace authority. */
export interface SavedChatSelection {
  ownerId: string; chatId: string; teamId: string | null;
  workspaceEpoch: number; selectionGeneration: number; revision: number;
}
export interface SavedReadWitness {
  readonly generation: number;
  readonly profile: { readonly principal: string };
}
export interface SelectedSavedReadInput<P extends SavedReadWitness> {
  host: Pick<BrowserCoreWorkerHost, "request" | "close">;
  reader: { assertCurrent(snapshot: P): Promise<void> };
  lifecycle: Pick<PriorProfileLifecycle, "current">;
  prior: P; status: SessionStatus; signal: AbortSignal;
  currentSelection(): SavedChatSelection;
}
const selectionFields = ["ownerId", "chatId", "teamId", "workspaceEpoch", "selectionGeneration", "revision"] as const;
function selectionGuard<P extends SavedReadWitness>(input: SelectedSavedReadInput<P>, selected: SavedChatSelection): () => void {
  return () => {
    const now = input.currentSelection();
    if (input.signal.aborted) throw new Error("cancelled");
    if (selected.teamId !== null || selected.ownerId !== input.status.principal
      || selected.ownerId !== input.prior.profile.principal
      || input.lifecycle.current() !== input.prior.generation
      || selectionFields.some(field => selected[field] !== now[field])) throw new Error("invalidated_snapshot");
  };
}
function supportedView(page: SavedChatReadback | LocalChatReadback): boolean {
  return !!page.messageMetadata && page.chat.messages.every(message => ["user", "assistant", "system"].includes(message.role))
    && page.messageMetadata.every(message =>
      (message.queueMode === null || ["follow_up", "steer"].includes(message.queueMode))
      && (message.queueDispatchMode === null || ["follow_up", "steer"].includes(message.queueDispatchMode))
      && (message.queueDispatchStatus === null || ["queued", "processing", "paused"].includes(message.queueDispatchStatus)));
}
async function publishOwnedSelection<P extends SavedReadWitness, T>(
  input: SelectedSavedReadInput<P> & { publish(page: T): void },
  read: (selected: SavedChatSelection, current: () => void) => Promise<T>,
  supported:(page:T)=>boolean,
): Promise<void> {
  const selected = { ...input.currentSelection() };
  const current = selectionGuard(input, selected);
  try {
    current(); await input.reader.assertCurrent(input.prior); current();
    const page = await read(selected, current);current();
    await input.reader.assertCurrent(input.prior); current();
    if (!supported(page)) throw new Error("unavailable");
    // No await between the final selection/lifetime check and the owned UI write.
    current(); input.publish(page);
  } catch (error) { input.host.close(); throw error; }
}
async function publishSelected<P extends SavedReadWitness,T extends SavedChatReadback|LocalChatReadback>(input:SelectedSavedReadInput<P>&{publish(page:T):void},read:(selected:SavedChatSelection,current:()=>void)=>Promise<T>):Promise<void>{
  await publishOwnedSelection(input,read,supportedView);
}
function sameStatus(current: SessionStatus | null | undefined, expected: SessionStatus): boolean {
  return !!current && current.principal === expected.principal && current.handle === expected.handle
    && current.generation === expected.generation && current.persistence === expected.persistence
    && current.localReadOnly === expected.localReadOnly;
}
function copyPageSelector(selector:SavedPageSelector):SavedPageSelector {
  if(selector.direction==="latest")return Object.freeze({direction:"latest"});
  if(selector.direction==="around")return Object.freeze({direction:"around",anchorMessageId:selector.anchorMessageId});
  return Object.freeze({direction:selector.direction,cursor:Object.freeze({...selector.cursor})});
}
async function publishCanonicalSavedPage<P extends SavedReadWitness>(input:SelectedSavedReadInput<P>&{publish(page:SavedChatReadback):void},selector?:SavedPageSelector):Promise<void>{
  const selectedPage=selector?copyPageSelector(selector):undefined;
  await publishSelected(input,async selected=>{
    if(input.status.localReadOnly===true)throw Error("unavailable");
    const body=selectedPage?{operation:"read_saved_chat_page" as const,handle:input.status.handle,generation:input.status.generation,chatId:selected.chatId,selector:selectedPage}:
      {operation:"read_saved_chat" as const,handle:input.status.handle,generation:input.status.generation,chatId:selected.chatId};
    const response=await input.host.request(body,input.signal);
    if(!response.ok||!sameStatus(response.status,input.status)||!response.savedRead||response.savedRead.chat.id!==selected.chatId)throw Error("session_expired");
    return response.savedRead;
  });
}
/** Existing latest request shape remains unchanged. */
export async function publishSelectedSavedChat<P extends SavedReadWitness>(input:SelectedSavedReadInput<P>&{publish(page:SavedChatReadback):void}):Promise<void>{
  await publishCanonicalSavedPage(input);
}
/** Existing shared canonical paging; no local/raw/TS fallback on refusal. */
export async function publishSelectedSavedChatPage<P extends SavedReadWitness>(input:SelectedSavedReadInput<P>&{selector:SavedPageSelector;publish(page:SavedChatReadback):void}):Promise<void>{
  await publishCanonicalSavedPage(input,input.selector);
}
/** Explicit offline branch. The adapter supplies only owned encrypted rows;
 * Rust performs the same shared local saved-read operation and PII interpretation.
 * Unknown retained boundaries and local provenance are never upgraded here.
 */
export async function publishSelectedLocalSavedChat<P extends SavedReadWitness>(input: SelectedSavedReadInput<P> & {
  readEncryptedRows(selected: Readonly<SavedChatSelection>, signal: AbortSignal): Promise<unknown>;
  publish(page: LocalChatReadback): void;
}): Promise<void> {
  await publishSelected(input, async (selected, current) => {
    if (input.status.localReadOnly !== true) throw new Error("unavailable");
    const encryptedRows = await input.readEncryptedRows(Object.freeze({ ...selected }), input.signal);
    current(); await input.reader.assertCurrent(input.prior); current();
    const response = await input.host.request({ operation: "read_local_saved_chat", handle: input.status.handle,
      generation: input.status.generation, expectedPrincipal: input.status.principal,
      chatId: selected.chatId, encryptedRows }, input.signal);
    if (!response.ok || !sameStatus(response.status, input.status) || !response.localRead
      || !("chatMetadata" in response.localRead) || response.localRead.chat.id !== selected.chatId) throw new Error("session_expired");
    return response.localRead;
  });
}

/** Actual Rust-issued cursor IO on the same request-owned Worker channel. */
export async function publishSelectedCursorSavedChat<P extends SavedReadWitness>(input: SelectedSavedReadInput<P> & {
  selector: LocalCursorSelector;
  executeReadPlan(selected: Readonly<SavedChatSelection>, plan: LocalReadPlan, signal: AbortSignal): Promise<string>;
  publish(page: LocalChatReadback): void;
}): Promise<void> {
  const selector:LocalCursorSelector=copyPageSelector(input.selector);
  await publishSelected(input, async(selected,current)=>{
    if(input.status.localReadOnly!==true)throw Error("unavailable");
    const response=await input.host.request({operation:"read_local_saved_chat_cursor",handle:input.status.handle,
      generation:input.status.generation,expectedPrincipal:input.status.principal,chatId:selected.chatId,selector},input.signal,undefined,{
      current,
      async execute(plan,signal){
        current();await input.reader.assertCurrent(input.prior);current();
        if(plan.owner!==selected.ownerId||plan.chatId!==selected.chatId)throw Error("invalidated_snapshot");
        const packet=await input.executeReadPlan(Object.freeze({...selected}),plan,signal);current();
        await input.reader.assertCurrent(input.prior);current();return packet;
      }
    });
    if(!response.ok||!sameStatus(response.status,input.status)||!response.localRead||!("chatMetadata" in response.localRead)
      ||response.localRead.chat.id!==selected.chatId)throw Error("session_expired");
    return response.localRead;
  });
}

/** Fixed-name stage marks (no content) for the cache-first breakdown. */
function stage(name: string): void {
  if (typeof performance !== "undefined") performance.mark(`openmates:rust:${name}`);
}
function fixedCode(error: unknown): string {
  return error instanceof Error && /^[a-z_]{1,40}$/.test(error.message) ? error.message : "other";
}

/** Cache-first view: Rust schedules readonly IDB plans over the existing
 * retained rows and decrypts them in the Worker. `online` runs on a
 * server-checked session; `local` on the local-only admission that precedes
 * the server check. A cache miss (`chat_unavailable`) keeps the admitted session
 * for the server read; every other failure closes it like the canonical read.
 * Provenance stays local. */
export async function publishSelectedOnlineCachedSavedChat<P extends SavedReadWitness>(input: SelectedSavedReadInput<P> & {
  selector: LocalCursorSelector;
  mode?: "online" | "local";
  executeReadPlan(selected: Readonly<SavedChatSelection>, plan: LocalReadPlan, signal: AbortSignal): Promise<string>;
  publish(page: LocalChatReadback): void;
}): Promise<void> {
  const selector:LocalCursorSelector=copyPageSelector(input.selector);
  const selected = { ...input.currentSelection() };
  const current = selectionGuard(input, selected);
  try {
    current(); await input.reader.assertCurrent(input.prior); current();
    const local=input.mode==="local";
    if((input.status.localReadOnly===true)!==local)throw Error("unavailable");
    const response=await input.host.request({operation:local?"read_local_saved_chat_cursor":"read_online_cached_saved_chat",handle:input.status.handle,
      generation:input.status.generation,expectedPrincipal:input.status.principal,chatId:selected.chatId,selector},input.signal,undefined,{
      current,
      async execute(plan,signal){
        current();
        if(plan.owner!==selected.ownerId||plan.chatId!==selected.chatId)throw Error("invalidated_snapshot");
        try{
          const packet=await input.executeReadPlan(Object.freeze({...selected}),plan,signal);current();
          stage(`cache-plan-${plan.kind}`);return packet;
        }catch(error){stage(`cache-plan-${plan.kind}-failed-${fixedCode(error)}`);throw error;}
      }
    });
    if(!response.ok&&"error" in response&&response.error==="chat_unavailable"){current();stage("cache-miss-rust");throw new Error("chat_unavailable");}
    const read=!response.ok?undefined:local?response.localRead:response.onlineCachedRead;
    if(!response.ok||!sameStatus(response.status,input.status)||!read||!("chatMetadata" in read)
      ||read.chat.id!==selected.chatId)throw Error("session_expired");
    const page:LocalChatReadback=read;current();
    // An unsupported retained shape is a cache miss; the server read decides.
    if (!supportedView(page)) { stage("cache-miss-unsupported"); throw new Error("chat_unavailable"); }
    input.publish(page);
  } catch (error) {
    if (!(error instanceof Error && error.message === "chat_unavailable")) input.host.close();
    throw error;
  }
}

/** Exact retained checkpoint; platform executes only Rust's scoped metadata IO. */
export async function publishSelectedCheckpointSummary<P extends SavedReadWitness>(input:SelectedSavedReadInput<P>&{
  checkpointId:string;executeReadPlan(selected:Readonly<SavedChatSelection>,plan:LocalReadPlan,signal:AbortSignal):Promise<string>;
  publish(page:CheckpointPresentation):void;
}):Promise<void>{
 const checkpointId=input.checkpointId;
 await publishOwnedSelection(input,async(selected,current)=>{
  if(input.status.localReadOnly!==true)throw Error("unavailable");
  const response=await input.host.request({operation:"read_local_checkpoint_summary",handle:input.status.handle,generation:input.status.generation,
    expectedPrincipal:input.status.principal,chatId:selected.chatId,checkpointId},input.signal,undefined,{
    current,async execute(plan,signal){current();await input.reader.assertCurrent(input.prior);current();
      if(plan.kind!=="metadata"||plan.owner!==selected.ownerId||plan.chatId!==selected.chatId)throw Error("invalidated_snapshot");
      const packet=await input.executeReadPlan(Object.freeze({...selected}),plan,signal);current();await input.reader.assertCurrent(input.prior);current();return packet;
    }});
  if(!response.ok||!sameStatus(response.status,input.status)||!response.checkpointRead||response.checkpointRead.coverage!=="retained_selected"
    ||response.checkpointRead.checkpoint!==null&&(response.checkpointRead.checkpoint.id!==checkpointId||response.checkpointRead.checkpoint.chatId!==selected.chatId))throw Error("session_expired");
  return response.checkpointRead;
 },()=>true);
}
