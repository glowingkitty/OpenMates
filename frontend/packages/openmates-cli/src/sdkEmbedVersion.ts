/** Stateless Rust reconstruction only. No HTTP, profile, credentials or fallback. */
import {loadSdkWasm} from "./sdkWasm.js";
import {SessionClientError} from "./sdkSession.js";
export function reconstructEmbedVersionLocal(rows:unknown[],key:Uint8Array):string {
  let encoded:string;
  try {
    if(key.length!==32 || rows.length===0 || rows.length>10000)throw Error();
    encoded=JSON.stringify({rows,key:Array.from(key)});
    if(Buffer.byteLength(encoded,"utf8")>64*1024*1024)throw Error();
  } catch {throw new SessionClientError("invalid_argument","Invalid typed version reconstruction input.");}
  const native=loadSdkWasm();
  if(!native)throw new SessionClientError("native_binding_unavailable","Install an OpenMates SDK build containing its WebAssembly module.");
  try {const content=native.reconstructEmbedVersion(encoded);if(typeof content!=="string"||Buffer.byteLength(content,"utf8")>16*1024*1024)throw Error();return content;}
  catch(error){
    try {const value=JSON.parse(error instanceof Error?error.message:"");if(["crypto","protocol","invalid_argument","cancelled"].includes(value.code))throw new SessionClientError(value.code,"Local version reconstruction failed.");}
    catch(mapped){if(mapped instanceof SessionClientError)throw mapped;}
    throw new SessionClientError("protocol","Local version reconstruction failed.");
  }
}
