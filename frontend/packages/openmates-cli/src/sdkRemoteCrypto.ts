/** Pure local Core crypto with explicit caller keys/identity; grants no remote consent or IO. */
import {createRequire} from "node:module";
export type RemoteRole="requester"|"source";
export interface RemoteIdentity {ownerId:string;contextType?:"personal"|"team";contextId?:string;projectId:string;sourceId:string;sourceSessionId:string;requestingClientId:string;hostMemberId?:string;hostDeviceId?:string;requesterMemberId?:string;requesterDeviceId?:string;keyEpoch:number}
export interface RemoteHandshakeWire {version:number;role:RemoteRole;publicKey:string;authenticationTag:string}
export interface RemoteEnvelope {version:number;nonce:string;ciphertext:string}
interface NativeSession {seal(id:string,text:Uint8Array):string;open(id:string,envelope:string):Uint8Array;openJsonText(id:string,envelope:string):string;close():void}
interface NativeHandshake {handshakeJson():string;finish(remote:string):NativeSession;close():void}
export class RemoteCryptoError extends Error {readonly code:string;constructor(code:string,message:string){super(message);this.code=code;this.name="RemoteCryptoError";}}
function failure(error:unknown):RemoteCryptoError {
  if(error instanceof RemoteCryptoError)return error;
  try{const value=JSON.parse(error instanceof Error?error.message:"");if(typeof value.code==="string"&&typeof value.message==="string")return new RemoteCryptoError(value.code,value.message);}catch{/* Not a structured native error; use the fixed generic failure below. */}
  return new RemoteCryptoError("native_failure","The native remote crypto operation failed.");
}
function native():new(key:Uint8Array,identity:string,role:string)=>NativeHandshake {
  const platform=process.platform,arch=process.arch;
  if(!["linux","darwin","win32"].includes(platform)||!["arm64","x64"].includes(arch))throw new RemoteCryptoError("native_binding_unavailable","Install a native SDK build containing remote crypto.");
  try{return createRequire(import.meta.url)(`../native/${platform}-${arch}.node`).NativeRemoteHandshake;}catch{throw new RemoteCryptoError("native_binding_unavailable","Install a native SDK build containing remote crypto.");}
}
function bytes(value:Uint8Array):void {if(!(value instanceof Uint8Array))throw new RemoteCryptoError("invalid_argument","Supply caller-owned bytes.");}
/** Holds only an opaque native exchange. finish is single-use even on refusal. */
export class RemoteHandshake {
  #native:NativeHandshake;
  constructor(key:Uint8Array,identity:RemoteIdentity,role:RemoteRole){
    bytes(key);
    try{const Native=native();this.#native=new Native(key,JSON.stringify(identity),role);}catch(error){throw failure(error);}
  }
  handshake():RemoteHandshakeWire {try{return JSON.parse(this.#native.handshakeJson()) as RemoteHandshakeWire;}catch(error){throw failure(error);}}
  finish(remote:RemoteHandshakeWire):RemoteSession {
    let encoded:string;
    try{
      encoded=JSON.stringify(remote);
      if(typeof encoded!=="string")throw new RemoteCryptoError("native_failure","The native remote crypto operation failed.");
    }catch(error){
      const original=failure(error);
      try{this.#native.close();}catch{/* Preserve the original serializer refusal. */}
      throw original;
    }
    try{return new RemoteSession(this.#native.finish(encoded));}catch(error){throw failure(error);}
  }
  close():void {try{this.#native.close();}catch(error){throw failure(error);}}
}
/** Opaque Core traffic key/replay history. Output bytes/text belong to the caller. */
export class RemoteSession {
  #native:NativeSession;
  /** @internal Obtained only from RemoteHandshake.finish. */
  constructor(handle:NativeSession){this.#native=handle;}
  seal(requestId:string,plaintext:Uint8Array):RemoteEnvelope {bytes(plaintext);try{return JSON.parse(this.#native.seal(requestId,plaintext)) as RemoteEnvelope;}catch(error){throw failure(error);}}
  open(requestId:string,envelope:RemoteEnvelope):Uint8Array {try{return this.#native.open(requestId,JSON.stringify(envelope));}catch(error){throw failure(error);}}
  /** Core-validated JSON serialization, preserving unsafe integers as text.
   * Raw open retains original plaintext bytes; JSON.parse here is caller-controlled. */
  openJsonText(requestId:string,envelope:RemoteEnvelope):string {try{return this.#native.openJsonText(requestId,JSON.stringify(envelope));}catch(error){throw failure(error);}}
  close():void {try{this.#native.close();}catch(error){throw failure(error);}}
}
