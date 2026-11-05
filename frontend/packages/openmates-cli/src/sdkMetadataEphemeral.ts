/** Explicit cookie authentication and Rust-owned volatile opaque metadata only. */
import {createRequire} from "node:module";
export interface MetadataCookieCredentials {sessionId:string;cookies:Record<string,string>}
export interface MetadataAuthenticationOptions extends MetadataCookieCredentials {apiUrl:string;appUrl:string}
interface NativeAuthentication {authenticate():Promise<NativeClient>;credentialSnapshotJson():string;cancel():void;cancelAndDrain():Promise<void>}
interface NativeClient {prepareInitialSync():NativeStartup;credentialSnapshotJson():string;close():Promise<void>}
interface NativeStartup {run():Promise<NativeSnapshot>;cancel():void}
interface NativeSnapshot {receivedMetadataCount(client:NativeClient):number;cancel():void}
export class MetadataEphemeralError extends Error {
  readonly code:string;
  constructor(code:string,message:string){super(message);this.code=code;this.name="MetadataEphemeralError";}
}
function failure(value:unknown):MetadataEphemeralError {
  if(value instanceof MetadataEphemeralError)return value;
  try{const parsed=JSON.parse(value instanceof Error?value.message:"");if(typeof parsed.code==="string"&&typeof parsed.message==="string")return new MetadataEphemeralError(parsed.code,parsed.message);}catch{/* Not a structured native error; use the fixed generic failure below. */}
  return new MetadataEphemeralError("native_failure","The native metadata operation failed.");
}
function load():new(input:string)=>NativeAuthentication {
  const platform=process.platform,arch=process.arch;
  if(!["linux","darwin","win32"].includes(platform)||!["arm64","x64"].includes(arch))throw new MetadataEphemeralError("native_binding_unavailable","Install the native metadata SDK build.");
  try{return createRequire(import.meta.url)(`../native/${platform}-${arch}.node`).NativeMetadataAuthentication;}
  catch{throw new MetadataEphemeralError("native_binding_unavailable","Install the native metadata SDK build.");}
}
/** Inputs are pending credentials. Actual Core HTTP identity alone issues a client. */
export class MetadataAuthentication {
  #native:NativeAuthentication;
  constructor(options:MetadataAuthenticationOptions){try{const Native=load();this.#native=new Native(JSON.stringify(options));}catch(error){throw failure(error);}}
  async authenticate():Promise<EphemeralMetadataClient>{try{return new EphemeralMetadataClient(await this.#native.authenticate());}catch(error){throw failure(error);}}
  credentialSnapshot():MetadataCookieCredentials {try{return JSON.parse(this.#native.credentialSnapshotJson()) as MetadataCookieCredentials;}catch(error){throw failure(error);}}
  cancel():void {this.#native.cancel();}
  async cancelAndDrain():Promise<void>{try{await this.#native.cancelAndDrain();}catch(error){throw failure(error);}}
}
const clients=new WeakMap<EphemeralMetadataClient,NativeClient>();
/** Core memory only: no durable/profile/browser store, crypto or private content. */
export class EphemeralMetadataClient {
  /** @internal Issued by MetadataAuthentication.authenticate. */
  constructor(handle:NativeClient){clients.set(this,handle);}
  prepareInitialSync():EphemeralMetadataStartup {try{return new EphemeralMetadataStartup(this.#handle().prepareInitialSync());}catch(error){throw failure(error);}}
  credentialSnapshot():MetadataCookieCredentials {try{return JSON.parse(this.#handle().credentialSnapshotJson()) as MetadataCookieCredentials;}catch(error){throw failure(error);}}
  async close():Promise<void>{try{await this.#handle().close();}catch(error){throw failure(error);}}
  #handle():NativeClient {const handle=clients.get(this);if(!handle)throw new MetadataEphemeralError("cancelled","The metadata context is unavailable.");return handle;}
}
export class EphemeralMetadataStartup {
  #native:NativeStartup;
  /** @internal Issued by the original Core metadata context. */
  constructor(handle:NativeStartup){this.#native=handle;}
  async run():Promise<EphemeralMetadataSnapshot>{try{return new EphemeralMetadataSnapshot(await this.#native.run());}catch(error){throw failure(error);}}
  cancel():void{this.#native.cancel();}
}
export class EphemeralMetadataSnapshot {
  #native:NativeSnapshot;
  /** @internal Actual original memory-store observation only. */
  constructor(handle:NativeSnapshot){this.#native=handle;}
  receivedMetadataCount(client:EphemeralMetadataClient):number {
    const handle=clients.get(client);if(!handle)throw new MetadataEphemeralError("forbidden","Use the original metadata context.");
    try{return this.#native.receivedMetadataCount(handle);}catch(error){throw failure(error);}
  }
  cancel():void{this.#native.cancel();}
}
