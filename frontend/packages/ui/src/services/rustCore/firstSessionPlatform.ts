/** Ordinary/headless UI boundary. This physical stub needs no web-app config,
 * Vite plugin, Worker, storage, network or account. The web builder replaces
 * only the two exact internal import sites when the explicit feature is on. */
import type {OriginalFirstSessionInput,OriginalFirstSessionData} from './originalFirstSessionSource';
import type {BrowserCoreWorkerHost} from './workerHost';
export const firstSessionLifetimeEnabled=false;
export async function stageOriginalFirstSession():Promise<boolean>{return false;}
export function readOriginalFirstSessionCheck(_input:OriginalFirstSessionInput):Promise<OriginalFirstSessionData>|null{return null;}
export async function takeOriginalFirstSessionWorker(_input:{signal:AbortSignal;expectedPrincipal:string;sessionId:string}):Promise<{host:BrowserCoreWorkerHost;close():void}|null>{return null;}
