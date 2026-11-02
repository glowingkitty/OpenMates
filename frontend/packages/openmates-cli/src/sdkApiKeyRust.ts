/** Partial direct Rust API-key foundation. Existing OpenMates remains supported. */
import {createRequire} from "node:module";
export interface RustApiKeyOptions {apiKey:string;apiUrl:string;deviceId:string;appUrl?:string;privacy:{enhanced:boolean};allowPrivateOperations:boolean}
export interface RustApiKeyCallOptions {signal?:AbortSignal}
interface Output {releaseJson():string;discard():void}
interface Request {accountInfoPrepare():Promise<Output>;listProjectSourcesRawPrepare(project:string,filters:string):Promise<Output>;runSkillPrepare(app:string,skill:string,input:string):Promise<Output>;cancel():void}
interface Native {request():Request;cancel():void;close():void}
export class RustApiKeyClientError extends Error {
  readonly code:string;
  constructor(code:string,message:string){super(message);this.code=code;this.name="RustApiKeyClientError";}
}
function failure(error:unknown):RustApiKeyClientError {
  if(error instanceof RustApiKeyClientError)return error;
  try{const value=JSON.parse(error instanceof Error?error.message:"");if(typeof value.code==="string"&&typeof value.message==="string")return new RustApiKeyClientError(value.code,value.message);}catch{/* Not a structured native error; use the fixed generic failure below. */}
  return new RustApiKeyClientError("native_failure","The native API-key operation failed.");
}
function projectFiltersJson(filters:{personal?:boolean;teamId?:string;includeArchived?:boolean}):string {
  const names:Record<string,string>={teamId:"team_id",includeArchived:"include_archived"};
  const result:Record<string,unknown>=Object.create(null);
  for(const [name,value]of Object.entries(filters)){
    const wire=names[name]??name;
    if(Object.hasOwn(result,wire))throw new RustApiKeyClientError("invalid_argument","Duplicate Project filter field.");
    result[wire]=value;
  }
  return JSON.stringify(result);
}
function constructor():new(options:string)=>Native {
  const require=createRequire(import.meta.url);
  try{
    if(process.platform==="linux"&&process.arch==="arm64")return require("../native/linux-arm64.node").NativeApiKeyClient;
    if(process.platform==="linux"&&process.arch==="x64")return require("../native/linux-x64.node").NativeApiKeyClient;
    if(process.platform==="darwin"&&process.arch==="arm64")return require("../native/darwin-arm64.node").NativeApiKeyClient;
    if(process.platform==="darwin"&&process.arch==="x64")return require("../native/darwin-x64.node").NativeApiKeyClient;
    if(process.platform==="win32"&&process.arch==="arm64")return require("../native/win32-arm64.node").NativeApiKeyClient;
    if(process.platform==="win32"&&process.arch==="x64")return require("../native/win32-x64.node").NativeApiKeyClient;
  }catch{/* Missing or incompatible native artifact: typed refusal below, never a CLI fallback. */}
  throw new RustApiKeyClientError("native_binding_unavailable","Install an OpenMates build containing the native API-key extension for this platform.");
}
export class RustApiKeyClient {
  private readonly native:Native;
  constructor(options:RustApiKeyOptions){
    if(!options||typeof options.apiKey!=="string"||!options.apiKey||typeof options.apiUrl!=="string"||typeof options.deviceId!=="string"||typeof options.privacy?.enhanced!=="boolean"||typeof options.allowPrivateOperations!=="boolean")throw new RustApiKeyClientError("invalid_argument","Supply explicit API-key credentials, endpoint, device identity and policy.");
    const Native=constructor();
    try{this.native=new Native(JSON.stringify({api_key:options.apiKey,api_url:options.apiUrl,device_id:options.deviceId,app_url:options.appUrl??null,enhanced_privacy:options.privacy.enhanced,allow_private_operations:options.allowPrivateOperations}));}catch(error){throw failure(error);}
  }
  private async invoke<T>(operation:(request:Request)=>Promise<Output>,options:RustApiKeyCallOptions):Promise<T>{
    let request:Request;try{request=this.native.request();}catch(error){throw failure(error);}
    const cancel=()=>request.cancel();let output:Output|undefined;
    try{
      options.signal?.addEventListener("abort",cancel,{once:true});if(options.signal?.aborted)cancel();
      // Await/drain the actual Rust driver; cancellation never replays paid work.
      output=await operation(request);
      const encoded=output.releaseJson();
      return JSON.parse(encoded) as T;
    }catch(error){throw failure(error);}finally{options.signal?.removeEventListener("abort",cancel);try{output?.discard();}finally{request.cancel();}}
  }
  accountInfo<T=Record<string,unknown>>(options:RustApiKeyCallOptions={}):Promise<T>{return this.invoke(request=>request.accountInfoPrepare(),options);}
  runSkill<T=unknown>(app:string,skill:string,input:Record<string,unknown>,options:RustApiKeyCallOptions={}):Promise<T>{return this.invoke(request=>request.runSkillPrepare(app,skill,JSON.stringify(input)),options);}
  /** Raw Project source rows; never loads a Master key or CLI profile. */
  listProjectSourcesRaw(project:string,filters:{personal?:boolean;teamId?:string;includeArchived?:boolean},options:RustApiKeyCallOptions={}):Promise<unknown[]>{
    return this.invoke(request=>request.listProjectSourcesRawPrepare(project,projectFiltersJson(filters)),options);
  }
  cancel():void{try{this.native.cancel();}catch(error){throw failure(error);}}
  close():void{try{this.native.close();}catch(error){throw failure(error);}}
}
