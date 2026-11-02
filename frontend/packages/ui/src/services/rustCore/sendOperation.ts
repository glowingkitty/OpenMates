/** Worker transport ownership only. Rust owns turn admission, stream and cancel. */
import { validSendEvent, validSendTerminalDisposition } from "./sendProtocol";
import type { SendEvent, SendTerminalDisposition } from "./sendProtocol";
import type { SessionStatus } from "./protocol";
interface Prepared {
  readonly operation_id: string;
  control(): Control; take_events(): Events; free(): void;
}
interface Control {
  publication_current(handle:string,generation:number,operation:string):boolean;
  cancel(handle: string, generation: number, operation: string): void;
  close(): void; free(): void;
}
interface Events {
  next_event(handle: string, generation: number, operation: string): Promise<string | null | undefined>;
  free(): void;
}
interface Terminal { free():void }
interface OwnedStep {readonly kind:"apply"|"terminal";free():void}
interface OwnedResume {free():void}
interface OwnedDriver {
  next_phase(handle:string,generation:number,operation:string):Promise<OwnedStep>;
  resume(resume:OwnedResume):void;free():void;
}
export interface SendClient {
  prepare_owned_send?(handle:string,generation:number,chatId:string):Prepared;
  prepare_new_owned_send?(handle:string,generation:number):Prepared;
  start_owned_send?(handle:string,generation:number,prepared:Prepared,text:string):OwnedDriver;
  apply_owned_send?(handle:string,generation:number,step:OwnedStep):Promise<OwnedResume>;
  finish_owned_send?(handle:string,generation:number,step:OwnedStep):string;
  prepare_send(handle: string, generation: number, chatId: string): Prepared;
  send_saved(handle: string, generation: number, prepared: Prepared, text: string): Promise<Terminal>;
  finish_send(handle:string,generation:number,terminal:Terminal):string;
}
export class OwnedSendOperation {
  readonly operationId: string;
  readonly finished: Promise<void>;
  readonly usesOwnedDriver:boolean;
  private readonly control: Control;
  private readonly events: Events;
  private settled = false;
  private closing = false;
  private freed = false;
  private polling = false;
  private driverFailed = false;
  private disposition: SendTerminalDisposition | null = null;
  get terminalDisposition():SendTerminalDisposition|null{return this.disposition;}
  get isPolling(): boolean { return this.polling; }
  get failed(): boolean { return this.driverFailed; }
  constructor(private readonly client: SendClient, private readonly authority: SessionStatus, readonly chatId: string | null,
    text: string, run: <T>(operation: () => Promise<T>) => Promise<T>, onSettled: () => void) {
    const ownedMethods=[client.prepare_owned_send,client.start_owned_send,client.apply_owned_send,client.finish_owned_send];
    this.usesOwnedDriver=ownedMethods.every(method=>typeof method==="function");
    if(!this.usesOwnedDriver&&ownedMethods.some(method=>typeof method==="function"))throw Error("unavailable");
    if(chatId===null&&(!this.usesOwnedDriver||typeof client.prepare_new_owned_send!=="function"))throw Error("unavailable");
    const prepared = chatId===null ? client.prepare_new_owned_send!(authority.handle,authority.generation)
      : this.usesOwnedDriver ? client.prepare_owned_send!(authority.handle,authority.generation,chatId)
      : client.prepare_send(authority.handle, authority.generation, chatId);
    let events: Events | null = null, control: Control | null = null, consumed = false;
    try {
      this.operationId = prepared.operation_id;
      if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(this.operationId)) throw new Error("unavailable");
      control = prepared.control(); events = prepared.take_events();
      this.control = control; this.events = events;
      const originalOperation=this.operationId;
      const running:Promise<string> = this.usesOwnedDriver ? (async()=>{
        let driver:OwnedDriver|null=null;
        try{
          driver=await run(async()=>{
            consumed=true; // Same actual one-use WASM preparation, no JSON handle.
            return client.start_owned_send!(authority.handle,authority.generation,prepared,text);
          });
          for(;;){
            // The owning Rust driver awaits socket/crypto/host queue WITHOUT a
            // Client borrow. Only its opaque actual phase enters the short lane.
            const step=await driver.next_phase(authority.handle,authority.generation,originalOperation);
            let stepConsumed=false;
            try{
              if(step.kind==="terminal")return await run(async()=>{
                stepConsumed=true;
                return client.finish_owned_send!(authority.handle,authority.generation,step);
              });
              if(step.kind!=="apply")throw Error("unavailable");
              let resume:OwnedResume|null=null,resumeConsumed=false;
              try{
                try{
                  resume=await run(()=>{
                    stepConsumed=true;
                    return client.apply_owned_send!(authority.handle,authority.generation,step);
                  });
                }catch{
                  // Actual apply failure/drop replies to this SAME Rust future.
                  // Continue to its actual terminal; never fabricate cancellation
                  // or abandon an uncertain driver because a callback refused.
                  continue;
                }
                resumeConsumed=true;driver.resume(resume);
              }finally{if(resume&&!resumeConsumed)resume.free();}
            }finally{if(!stepConsumed)step.free();}
          }
        }finally{driver?.free();}
      })() : run(() => {
        consumed = true; // wasm-bindgen consumes the one-use prepared object.
        return client.send_saved(authority.handle, authority.generation, prepared, text);
      }).then(terminal=>client.finish_send(authority.handle,authority.generation,terminal));
      this.finished = Promise.resolve(running).then(encoded => {
        // Only the exact actual Rust terminal's finish produces this metadata.
        if(typeof encoded!=="string"||encoded.length>2048)throw Error("session_expired");
        const receipt:unknown=JSON.parse(encoded);
        if(!validSendTerminalDisposition(receipt)||receipt.operationId!==this.operationId)throw Error("session_expired");
        this.disposition=Object.freeze({...receipt});this.settled=true;
      }).catch(() => {
        if (!consumed) prepared.free();
        this.driverFailed = true; this.settled = true; this.close();
      }).finally(() => { this.release(); onSettled(); });
    } catch (error) {
      control?.close(); events?.free(); control?.free();
      if (!consumed) prepared.free();
      throw error;
    }
  }
  owns(client: SendClient | null): boolean { return client === this.client; }
  matches(handle: string, generation: number, operationId: string): boolean {
    return !this.closing && !this.driverFailed && handle === this.authority.handle
      && generation === this.authority.generation && operationId === this.operationId;
  }
  private check(handle: string, generation: number, operationId: string): void {
    if (!this.matches(handle, generation, operationId)) throw new Error("session_expired");
  }
  cancel(handle: string, generation: number, operationId: string): void {
    this.check(handle, generation, operationId);
    this.control.cancel(handle, generation, operationId);
  }
  /** Negative observation of this exact original Rust resource, immediately
   * before the outer Worker continuation transfers an already parsed update. */
  publicationCurrent(handle:string,generation:number,operationId:string):boolean {
    this.check(handle,generation,operationId);
    return this.control.publication_current(handle,generation,operationId);
  }
  async next(handle: string, generation: number, operationId: string): Promise<SendEvent | null> {
    this.check(handle, generation, operationId);
    if (this.polling) throw new Error("unavailable");
    this.polling = true;
    try {
      // At most one already-encoded update can be pending when Rust revokes
      // this queue1 operation. Discard it and pull the canonical Rust terminal;
      // never synthesize a completion/ACK/error from host timing.
      for(let pull=0;pull<2;pull++){
      const encoded = await this.events.next_event(handle, generation, operationId);
      this.check(handle, generation, operationId);
      if (encoded == null) { await this.finished; this.close(); return null; }
      if (typeof encoded !== "string" || encoded.length + 8192 > 256 * 1024
        || new TextEncoder().encode(encoded).byteLength + 8192 > 256 * 1024) throw new Error("unavailable");
      const event: unknown = JSON.parse(encoded);
      if (!validSendEvent(event, this.chatId??undefined)) throw new Error("unavailable");
      if(event.type==="update"&&!this.control.publication_current(handle,generation,operationId))continue;
      if (event.type !== "update") {
        await this.finished;
        this.check(handle, generation, operationId);
        const terminal=this.disposition;
        if(!terminal||event.type==="completed"&&(terminal.outcome!=="completed"||!terminal.canContinueParent)
          ||event.type==="error"&&(event.error==="cancelled"&&!["cancelled","uncertain"].includes(terminal.outcome)))throw Error("session_expired");
        this.close();
      }
      return event;
      }
      throw new Error("session_expired");
    } catch (error) { this.close(); throw error; }
    finally { this.polling = false; this.release(); }
  }
  requestClose(handle: string, generation: number, operationId: string): void { this.check(handle, generation, operationId); this.close(); }
  close(): void { if (!this.closing) { this.closing = true; this.control.close(); } this.release(); }
  private release(): void {
    // Both WASM mutable borrows must settle before their respective objects free.
    if (!this.closing || !this.settled || this.polling || this.freed) return;
    this.freed = true; this.events.free(); this.control.free();
  }
}
