declare module 'virtual:openmates-rust-core-package' {
  export const artifact: string | null;
  export const assets: null | Readonly<{ artifact: string; javascriptUrl: string; wasmUrl: string }>;
  export function loadBinding(): Promise<unknown>;
}

declare module 'virtual:openmates-first-session-provider' {
 export const firstSessionLifetimeEnabled:boolean;
 export function stageOriginalFirstSession():Promise<boolean>;
 export function readOriginalFirstSessionCheck(input:import('@openmates/ui/src/services/rustCore/originalFirstSessionSource').OriginalFirstSessionInput):Promise<import('@openmates/ui/src/services/rustCore/originalFirstSessionSource').OriginalFirstSessionData>|null;
 export function takeOriginalFirstSessionWorker(input:{signal:AbortSignal;expectedPrincipal:string;sessionId:string}):Promise<{host:import('@openmates/ui/src/services/rustCore/workerHost').BrowserCoreWorkerHost;close():void}|null>;
}
