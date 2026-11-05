/** Fixed web platform provider only. Ordinary builds supply the closed stub;
 * no callback installer, Page response import or caller-selected Worker URL. */
export {readOriginalFirstSessionCheck} from './firstSessionPlatform';
export interface OriginalFirstSessionInput {
 endpoint:string;appOrigin:string;sessionId:string;deviceSignals:Record<string,string|null>;
 signal:AbortSignal;deadlineEpochMs:number;isCurrent():boolean;
}
export interface OriginalFirstSessionData {httpStatus:number|null;data:import('../../stores/authTypes').SessionCheckResult|null}
