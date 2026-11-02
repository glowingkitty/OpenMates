/** Thin phase orchestration for one actual Rust initial-sync operation.
 * No metadata DTO, key, network policy, retry, full-sync or close ACK lives here.
 */
export interface InitialSyncControl {cancel():void;ensure_current(client:InitialSyncClient):void;free():void}
export interface InitialSyncNativeTerminal {native_io_quiescent():boolean;free():void}
export interface InitialSyncStored {ensure_current(client:InitialSyncClient):void;stored_metadata_count(client:InitialSyncClient):number;free():void}
export interface InitialSyncStoreDriver {
  control():InitialSyncControl;drive():Promise<void>;finish(client:InitialSyncClient):InitialSyncStored;
  terminal():InitialSyncNativeTerminal|undefined;free():void;
}
export interface InitialSyncMetadata {
  ensure_current(client:InitialSyncClient):void;received_metadata_count(client:InitialSyncClient):number;
  begin_store(client:InitialSyncClient):InitialSyncStoreDriver;cancel():void;free():void;
}
export interface InitialSyncHandle {
  control():InitialSyncControl;drive():Promise<void>;retain(client:InitialSyncClient):InitialSyncMetadata;free():void;
}
export interface InitialSyncClient {
  begin_initial_sync(handle:string,generation:number,owner:string,monitorId:string):InitialSyncHandle;
}
export interface InitialSyncCounts {receivedMetadataCount:number;storedMetadataCount:number}
/** Keep this object in the owning Worker slot through errors and cancellation.
 * A rejected drive cannot erase original Rust resources or enable a successor.
 */
export class OwnedInitialSyncOperation {
  private handle:InitialSyncHandle|null=null;
  private control:InitialSyncControl|null=null;
  private metadata:InitialSyncMetadata|null=null;
  private store:InitialSyncStoreDriver|null=null;
  private storeControl:InitialSyncControl|null=null;
  private stored:InitialSyncStored|null=null;
  private running=false;
  private invoked=false;
  private cancelled=false;
  private completed=false;
  private receivedCount:number|null=null;
  constructor(private readonly client:InitialSyncClient,
    private readonly phase:<T>(operation:()=>Promise<T>)=>Promise<T>,
    private readonly current:()=>void){}
  cancel():void {
    this.cancelled=true;
    this.control?.cancel();this.storeControl?.cancel();this.metadata?.cancel();
  }
  get succeeded():boolean{return this.completed;}
  /** Counts are data only, never full-metadata/hint completion or readiness. */
  async run(binding:{handle:string;generation:number;owner:string;monitorId:string}):Promise<InitialSyncCounts>{
    if(this.invoked||this.running)throw Error('unavailable');
    this.invoked=true;this.running=true;
    const check=()=>{this.current();if(this.cancelled)throw Error('cancelled');};
    try{
      await this.phase(async()=>{check();this.handle=this.client.begin_initial_sync(binding.handle,binding.generation,binding.owner,binding.monitorId);this.control=this.handle.control();check();});
      // Actual actor/socket IO is awaited outside the Client/auth phase.
      await this.handle!.drive();
      await this.phase(async()=>{check();this.control!.ensure_current(this.client);this.metadata=this.handle!.retain(this.client);this.metadata.ensure_current(this.client);
        const metadata=this.metadata;this.receivedCount=metadata.received_metadata_count(this.client);
        // wasm-bindgen consumes self even when begin_store throws. The driver
        // owns the source thereafter; never call the consumed wrapper again.
        this.metadata=null;this.store=metadata.begin_store(this.client);this.storeControl=this.store.control();check();});
      // Actual native transaction terminal + same-DB reread own this await.
      // Cancellation requests a negative; it does not select-drop this future.
      await this.store!.drive();
      let result!:InitialSyncCounts;
      await this.phase(async()=>{
        check();this.storeControl!.ensure_current(this.client);
        this.stored=this.store!.finish(this.client);this.stored.ensure_current(this.client);check();
        const received=this.receivedCount!,stored=this.stored.stored_metadata_count(this.client);
        if(!Number.isSafeInteger(received)||received<0||!Number.isSafeInteger(stored)||stored<0||stored>received)throw Error('unavailable');
        result=Object.freeze({receivedMetadataCount:received,storedMetadataCount:stored});check();this.completed=true;
      });
      return result;
    }finally{this.running=false;}
  }
  /** NATIVE IO only. This is never socket/HTTP/Worker drain or a rearm grant. */
  nativeIoQuiescent():boolean {
    const terminal=this.store?.terminal();
    if(!terminal)return false;
    try{return terminal.native_io_quiescent();}finally{terminal.free();}
  }
}
