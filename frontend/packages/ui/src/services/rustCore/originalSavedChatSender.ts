/** Shared thin Page lifetime for the existing original Rust send operation.
 * Extracted from productionSavedChatSession; Rust still owns all headless work.
 * Same actual Host/profile/currentness and selection guard are supplied by owner.
 * No restore/new Client, wire/crypto/storage policy, fallback or retry is added.
 * Unknown IO and cancellation retain the original operation's existing lifetime.
 */
import type {ProductionSavedChatSend,ExistingSavedChatProfile} from './secondDeviceSavedChatSession';
import type {SavedChatSelection} from './selectedSavedChat';
import type {BrowserCoreWorkerHost} from './workerHost';
import type {SessionStatus} from './protocol';
import type {SendEvent} from './sendProtocol';
type SendSlot={terminal:boolean;closing:boolean;polling:boolean;pending:number;prior:ExistingSavedChatProfile|null;closePromise?:Promise<void>};
export interface OriginalSavedChatSender {startSend(text:string):Promise<ProductionSavedChatSend>;startNewSend(text:string):Promise<ProductionSavedChatSend>;invalidate():void}
export function createOriginalSavedChatSender(input:{host:BrowserCoreWorkerHost;status:Readonly<SessionStatus>;signal:AbortSignal;
 current():void;closed():boolean;profile():ExistingSavedChatProfile|null;assertProfile(prior:ExistingSavedChatProfile):Promise<void>;
 currentSelection():SavedChatSelection;busy():boolean;setBusy(value:boolean):void;close():void}):OriginalSavedChatSender{
 let activeSend:SendSlot|null=null;
    const startSend = async (text: string, newChat=false): Promise<ProductionSavedChatSend> => {
      if (input.busy() || input.status.localReadOnly) throw new Error("unavailable");
      const slot: SendSlot = { terminal: false, closing: false, polling: false, pending: 0, prior: null };
      input.setBusy(true); activeSend = slot;
      const release = () => {
        if (slot.terminal && slot.pending === 0) {
          slot.prior = null;
          if (activeSend === slot) { activeSend = null; input.setBusy(false); }
        }
      };
      const assertLive = () => {
        if (activeSend !== slot || slot.terminal || slot.closing) throw new Error("session_expired");
      };
      try {
        input.current();
        slot.prior = input.profile();
        const selected = Object.freeze({ ...input.currentSelection() });
        if(newChat&&selected.chatId!=="")throw Error("unavailable");
        const navigationChanged=new Error("invalidated_snapshot");
        const rootSendCurrent=()=>{
          assertLive();input.current();const now=input.currentSelection();
          if(selected.teamId!==null||selected.ownerId!==input.status.principal
            ||(['ownerId','teamId','workspaceEpoch'] as const).some(field=>selected[field]!==now[field]))throw Error("invalidated_snapshot");
        };
        const selectedCurrent = () => {
          rootSendCurrent();const now=input.currentSelection();
          if((['chatId','selectionGeneration','revision'] as const).some(field=>selected[field]!==now[field]))throw navigationChanged;
        };
        const verifyRoot=async()=>{
          rootSendCurrent();const prior=slot.prior;if(!prior)throw Error("invalidated_snapshot");
          await input.assertProfile(prior);rootSendCurrent();
        };
        const verify = async () => {selectedCurrent();await verifyRoot();selectedCurrent();};
        await verify(); selectedCurrent();
        const started = await input.host.request(newChat
          ? {operation:"start_new_send",handle:input.status.handle,generation:input.status.generation,text}
          : { operation: "start_send", handle: input.status.handle,
          generation: input.status.generation, chatId: selected.chatId, text }, input.signal);
        await verify(); selectedCurrent();
        if (!started.ok || !started.status || started.status.handle !== input.status.handle
          || started.status.generation !== input.status.generation || started.status.principal !== input.status.principal
          || started.status.persistence !== input.status.persistence || started.status.localReadOnly !== false
          || !started.send || started.send.kind !== "started") throw new Error("session_expired");
        const operationId = started.send.operationId;
        const control = async (operation: "cancel_send" | "close_send") => {
          // Negative control uses only this exact original Rust operation. It
          // never acquires replacement authority or reports a terminal outcome.
          return input.host.request({ operation, handle: input.status.handle, generation: input.status.generation,
            operationId }, input.signal);
        };
        const origin=Object.freeze({chatId:selected.chatId,operationId});
        const pullNext=async(consume:(event:SendEvent|null)=>void,visible:boolean)=>{
          assertLive();if(slot.polling)throw Error("unavailable");slot.polling=true;slot.pending++;
          try{
            await verifyRoot();rootSendCurrent();if(visible)selectedCurrent();
            const response=await input.host.request({operation:"next_send_event",handle:input.status.handle,
              generation:input.status.generation,operationId},input.signal);
            await verifyRoot();rootSendCurrent();
            if(!response.ok||response.status!==null||!response.send||response.send.operationId!==operationId||response.send.kind!=="event")throw Error("session_expired");
            const event=response.send.event;
            const terminal=event?.type!=="update"?input.host.consumeSendTerminal(response,input.status.handle,input.status.generation,operationId):null;
            const finish=()=>{
              if(event===null||event.type!=="update"){
                slot.terminal=true;if(event?.type==="error"&&!terminal?.canContinueParent)input.close();
              }
            };
            if(visible){
              try{selectedCurrent();}catch(error){if(error===navigationChanged)finish();throw error;}
            }else rootSendCurrent();
            consume(event);finish();
          }catch(error){if(error!==navigationChanged&&!slot.closing)input.close();throw error;}
          finally{slot.polling=false;slot.pending--;release();}
        };
        return Object.freeze({ operationId,
          publishNext:(publish:(event:SendEvent|null)=>void)=>pullNext(publish,true),
          consumeNext:(consume:(event:SendEvent|null,origin:Readonly<{chatId:string;operationId:string}>)=>void)=>pullNext(event=>consume(event,origin),false),
          async cancel() {
            assertLive(); slot.pending++;
            let response;
            try {
              await verifyRoot();rootSendCurrent();response=await control("cancel_send");
              await verifyRoot();rootSendCurrent();
            } catch (error) {
              if (!slot.terminal && !slot.closing && activeSend === slot) input.close();
              throw error;
            } finally { slot.pending--; release(); }
            // A denial may race a completed driver. Leave canonical next_event
            // available rather than converting a rejected cancel into completion.
            if (!response.ok) throw new Error(response.error);
            if (response.status !== null || !response.send || response.send.kind !== "cancel_requested"
              || response.send.operationId !== operationId) { input.close(); throw new Error("session_expired"); }
          },
          close() {
            if (slot.closePromise) return slot.closePromise;
            // Old completed operation A cannot close a later send B/session.
            if (activeSend !== slot || slot.terminal || input.closed()) return Promise.resolve();
            // Reserve this control lifetime before user/transport reentrancy.
            // A terminal callback can request close before its pull releases.
            slot.closing = true; slot.pending++;
            slot.closePromise = control("close_send").then(response => {
              if (!response.ok || response.status !== null || !response.send || response.send.kind !== "closed"
                || response.send.operationId !== operationId) throw new Error("session_expired");
            }).finally(() => { slot.pending--; slot.terminal = true; input.close(); release(); });
            return slot.closePromise;
          },
        });
      } catch (error) { slot.terminal = true; input.close(); release(); throw error; }
    };
 return Object.freeze({startSend:(text:string)=>startSend(text),startNewSend:(text:string)=>startSend(text,true),invalidate(){if(activeSend)activeSend.prior=null;}});
}
