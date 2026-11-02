/** Rich headless saved-read shape; legacy SessionChat/openChat remain independent. */
export type SessionChatDetailsHistory = {kind:"latest";limit:number}|{kind:"full"};
export interface SessionChatDetailsOptions {history?:SessionChatDetailsHistory;content_mode?:"stored"|"page_local"}
export interface SessionChatDetailsMetadata {
  id:string;chatVisibility:"personal"|"team"|"direct";participantUserHashes?:string[];activeFocusId?:string;
  shortId:string;slug:string|null;title:string|null;summary:string|null;
  createdAt:number|null;updatedAt:number|null;category:string|null;mateName:string|null;parentId:string|null;
  isSubChat:boolean;isHiddenCandidate:boolean;isHidden:boolean;pinned:boolean;
  hasDraft:boolean;draftPreview:string|null;metadataUpdatedAt:number;
}
export interface SessionChatDetailsMessage {
  id:string;clientMessageId:string;chatId:string;role:string;content:string;
  senderName:string|null;hashedSenderUserId:string|null;category:string|null;modelName:string|null;
  createdAt:number;embedIds:string[];piiMappings?:unknown;
}
export interface SessionChatDetailsRead {
  chat:SessionChatDetailsMetadata;messages:SessionChatDetailsMessage[];
  follow_up_suggestions:string[];has_more_before?:boolean;
}
import {readChatWithFirstPage, type NativeFirstPage, type SessionFirstPageOptions, type SessionFirstPageStore} from "./sdkFirstPage.js";
export type {SessionFirstPageOptions,SessionFirstPagePublication,SessionFirstPageStore} from "./sdkFirstPage.js";
/** Explicit cache policy only. Staging contains no plaintext publication or durable ACK. */
export interface SessionCacheChatStage extends SessionChatRefresh { source:"canonical"|"cache_settled"|"cached_offline" }
export type SessionCacheChatPublication = {chat:SessionChat;refreshing:false;has_more_before:boolean|null} & (
 | {source:"canonical";cached:false;history_complete:true;pii_restoration:"all_user_rows"}
 | {source:"cache_settled";cached:true;history_complete:false;pii_restoration:"all_cached_user_rows"}
 | {source:"cached_offline";cached:true;history_complete:false;pii_restoration:"page_local"});
export interface SessionSavedChatReadMetadata { id:string; title:string|null; summary:string|null; category:string|null; slug:string|null; activeFocusId:string|null; createdAt:number|null; lastEditedAt:number|null; metadataUpdatedAt:number|null; parentId:string|null; isSubChat:boolean|null; isHidden:boolean|null; pinned:boolean|null; chatVisibility:string|null; participantUserHashes:string[]|null; hasDraft:boolean|null; followUpSuggestions:string[]|null }
export interface SessionSavedChatMessageMetadata { id:string; storageId:string|null; sourceMessageId:string|null; clientMessageId:string|null; chatId:string; createdAt:number; rawStatus:string|null; senderName:string|null; category:string|null; modelName:string|null; thinkingSignature:string|null; hasThinking:boolean|null; thinkingTokenCount:number|null; hashedUserId:string|null; userMessageId:string|null; keyVersion:number|null; queueRevision:number|null; queueMode:string|null; queueDispatchStatus:string|null; queueDispatchMode:string|null; queueDispatchTaskId:string|null; embedIds:string[]|null }
/** Bounded saved read: requested 30 by default, max 100; never complete history. */
export interface SessionSavedChatReadOptions { limit?:number; before?:SessionMessageWindowCursor; after?:SessionMessageWindowCursor; anchorMessageId?:string; maxPages?:number; respectCompressionBoundary?:boolean; contentMode?:"stored"|"page_local" }
export interface SessionSavedChatRead extends Omit<SessionMessageWindow,"piiRestoration"> { chatMetadata:SessionSavedChatReadMetadata; messageMetadata:SessionSavedChatMessageMetadata[]; piiRestoration:"stored"|"page_local"; piiMappingsByMessageId:Record<string,Array<unknown>>; contentMode:"stored"|"page_local"; pagesRead:number }
export interface SessionSavedChatExactOptions { cursor:SessionMessageWindowCursor; contentMode?:"stored"|"page_local" }
export interface SessionSavedChatExactMessage { message:SessionChat["messages"][number]; chatMetadata:SessionSavedChatReadMetadata; messageMetadata:SessionSavedChatMessageMetadata; piiMappings:Array<unknown>|null; contentMode:"stored"|"page_local"; piiRestoration:"stored"|"page_local"; payloadBytes:number; historyComplete:false }
/** One live-context selector; neither a durable checkpoint nor authority. */
export interface SessionMessageWindowCursor { chatId:string; scope:string; createdAt:number; messageId:string }
export interface SessionMessageWindowOptions { direction?:"latest"|"before"|"after"|"around"; limit?:number; cursor?:SessionMessageWindowCursor; anchorMessageId?:string; respectCompressionBoundary?:boolean }
export interface SessionMessageWindow { chat:SessionChat; hasMoreBefore:boolean; hasMoreAfter:boolean; anchorFound:boolean; startCursor:SessionMessageWindowCursor|null; endCursor:SessionMessageWindowCursor|null; serverMessageCount:number|null; messagesVersion:number|null; oversizedMessage:boolean; oversizedMessageCursor:SessionMessageWindowCursor|null; payloadBytes:number; piiRestoration:"page_local"; historyComplete:false }
import {SessionChatMonitor,SessionCompletionRecovery,type NativeEssential,type SessionChatRefresh,type SessionChatDurableReceipt} from "./sdkEssential.js";
import type {SessionProjectSourceCreate,SessionProjectSourceCapabilitiesPatch,SessionProjectSource,SessionProjectSourcesDecodedNames} from "./sdkProjectSources.js";
import {SessionProjectTaskWatch,type SessionProjectTaskWatchInput} from "./sdkProjectTaskWatch.js";
/** First-party sessions are owned by the Rust SDK, without a CLI process. */
export type SessionWorkScope = { personal: true; teamId?: never } | { personal?: false; teamId: string };
export type SessionTaskFilters = SessionWorkScope & { status?: string; chatId?: string; projectId?: string; planId?: string; labels?: string[]; externalChat?: SessionExternalChat; priority?: number; limit?: number };
export type SessionProjectFilters = SessionWorkScope & { includeArchived?: boolean };
export type SessionExternalChat = { provider: string; id: string; title?: string };
export type SessionTaskCreate = { title: string; description?: string; slug?: string; taskId?: string; assign?: string; labels?: string[]; status?: string; priority?: number; dueAt?: number; primaryChatId?: string; linkedProjectIds?: string[]; planId?: string; externalChat?: SessionExternalChat; position?: number };
export type SessionTaskPatch = Partial<Pick<SessionTaskCreate, "title" | "description" | "slug" | "assign" | "labels" | "status" | "priority" | "linkedProjectIds">> & { addLabels?: string[]; removeLabels?: string[]; primaryChatId?: string | null; planId?: string | null; dueAt?: number | null; externalChat?: SessionExternalChat | null };
export type SessionProjectCreate = { name: string; description?: string; icon?: string; color?: string; slug?: string; pinned?: boolean; projectId?: string; writeMode?: "always_ask" | "apply_and_show"; chatOrganizationOnly?: boolean; defaultFocus?: { focusId: string; name: string; instructions: string; source: string } };
export type SessionProjectPatch = Partial<Pick<SessionProjectCreate, "name" | "description" | "icon" | "color" | "slug" | "pinned">> & { archived?: boolean; lastOpenedAt?: number };
export type SessionProjectUnlinkInput = { itemType: "embed" | "chat" | "workflow"; targetId: string; confirmed: true };
export type SessionPlanFilters = SessionWorkScope & { status?: string; chatId?: string; projectId?: string; activeOnly?: boolean };
export type SessionPlanEvidence = { kind: "url"; url: string } | { kind: "file"; path: string; startLine?: number; endLine?: number } | { kind: "embed"; embedId: string; startLine?: number; endLine?: number };
export type SessionPlanFlow = { flowId: string; title: string; actor?: string | null; steps: Array<{ stepId: string; text: string; references?: SessionPlanEvidence[] }>; expectedOutcome: string; linkedTaskIds?: string[]; linkedCriterionIds?: string[] };
export type SessionPlanCreate = { title: string; goal: string; linkedProjectIds: string[]; slug?: string; planId?: string; scopeIn?: string; scopeOut?: string; userFlows?: SessionPlanFlow[]; assumptions?: string; openQuestions?: string; constraints?: string; decisions?: string; risks?: string; referencePatterns?: string; context?: string; status?: string; primaryChatId?: string; plannerFocusId?: string };
export type SessionPlanPatch = Partial<Omit<SessionPlanCreate,"primaryChatId"|"plannerFocusId"|"planId">> & { primaryChatId?: string | null; plannerFocusId?: string | null };
export type SessionWorkflowFilters = SessionWorkScope & { appId?: string; offset?: number; limit?: number };
export type SessionWorkflowNodeType = "schedule_trigger" | "manual_trigger" | "webhook_trigger" | "event_trigger" | "app_skill_action" | "decision" | "check" | "send_chat_message" | "repeat" | "for_each" | "create_chat_report" | "start_new_chat" | "send_notification" | "send_email_notification" | "ask_user" | "wait" | "custom_code" | "end";
export type SessionWorkflowNode = { id: string; type: SessionWorkflowNodeType; title?: string; config?: Record<string,unknown>; inputMapping?: Record<string,unknown>; ui?: Record<string,unknown> };
export type SessionWorkflowGraph = { version?: number; triggerNodeId?: string; nodes: SessionWorkflowNode[]; edges: Array<{from:string;to:string;branch?:string}>; variables?: Record<string,unknown>; limits?: Record<string,unknown>; uiLayout?: Record<string,unknown> };
export type SessionWorkflowCreate = { title: string; graph: SessionWorkflowGraph; description?: string; category?: string; icon?: string; enabled?: boolean; runContentRetention?: "last_5" | "none"; lifecycle?: "persisted" | "temporary" | "chat_embed"; source?: string; slug?: string; sourceChatId?: string; createdByAssistant?: boolean; autoDeleteAt?: number };
export type SessionWorkflowPatch = Partial<Pick<SessionWorkflowCreate,"title"|"description"|"category"|"icon"|"graph"|"enabled"|"runContentRetention"|"slug">> & { version?: number };
export type SessionWorkflowRunOptions = { idempotencyKey: string; mode?: "manual" | "test"; input?: Record<string,unknown>; sourceChatId?: string; messageDestinationOverrides?: Record<string,string>; returnOutputs?: Record<string,Record<string,string>> };
export type SessionWorkflowWaitOptions = { timeoutMs?: number; pollIntervalMs?: number; syncIntervalMs?: number };
function workJson(input: object): string {
  const keys: Record<string, string> = { scopeIn:"scope_in", scopeOut:"scope_out", userFlows:"user_flows", openQuestions:"open_questions", referencePatterns:"reference_patterns", plannerFocusId:"planner_focus_id", flowId:"flow_id", stepId:"step_id", expectedOutcome:"expected_outcome", linkedTaskIds:"linked_task_ids", linkedCriterionIds:"linked_criterion_ids", embedId:"embed_id", startLine:"start_line", endLine:"end_line", activeOnly:"active_only", appId:"app_id", triggerNodeId:"trigger_node_id", inputMapping:"input_mapping", uiLayout:"ui_layout", runContentRetention:"run_content_retention", sourceChatId:"source_chat_id", createdByAssistant:"created_by_assistant", autoDeleteAt:"auto_delete_at", idempotencyKey:"idempotency_key", messageDestinationOverrides:"message_destination_overrides", returnOutputs:"return_outputs", timeoutMs:"timeout_ms", pollIntervalMs:"poll_interval_ms", syncIntervalMs:"sync_interval_ms", teamId:"team_id",chatId:"chat_id",projectId:"project_id",planId:"plan_id",externalChat:"external_chat",taskId:"task_id",dueAt:"due_at",primaryChatId:"primary_chat_id",linkedProjectIds:"linked_project_ids",addLabels:"add_labels",removeLabels:"remove_labels",includeArchived:"include_archived",writeMode:"write_mode",chatOrganizationOnly:"chat_organization_only",defaultFocus:"default_focus",focusId:"focus_id",lastOpenedAt:"last_opened_at" };
  keys.itemType = "item_type";
  keys.targetId = "target_id";
  function convert(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(convert);
    if (value && typeof value === "object") {
      const output: Record<string, unknown> = Object.create(null);
      for (const [key, child] of Object.entries(value)) {
        const wire = keys[key] ?? key;
        if (Object.hasOwn(output, wire)) throw new SessionClientError("invalid_argument", "Duplicate work input field.");
        // User variable/configuration names are data, not DTO field names.
        output[wire] = new Set(["config","input","input_mapping","ui","variables","limits","ui_layout","message_destination_overrides","return_outputs"]).has(wire) ? child : convert(child);
      }
      return output;
    }
    return value;
  }
  return JSON.stringify(convert(input));
}
// Source metadata is an opaque JSON object. Map only the outer DTO and never
// send it through workJson's recursive work-field renaming.
function sourceJson(input:object,patch=false):string{
  const fields:Record<string,string>=patch?{capabilities:'capabilities',updatedAt:'updated_at'}:{sourceId:'source_id',sourceType:'source_type',displayName:'display_name',metadata:'metadata',capabilities:'capabilities',status:'status',createdAt:'created_at',updatedAt:'updated_at',lastIndexedAt:'last_indexed_at'};
  try{
    if(!input||typeof input!=='object'||Array.isArray(input)||Reflect.ownKeys(input).some(k=>typeof k!=='string'||!Object.hasOwn(fields,k)))throw Error();
    let budget=1024*1024;
    const active=new Set<object>();
    function visit(value:unknown,depth:number):void{
      if(depth>128)throw Error();
      if(value===null){budget-=4;}
      else if(typeof value==='string'){if(value.length>1024*1024)throw Error();budget-=Buffer.byteLength(value,'utf8');}
      else if(typeof value==='number'){if(!Number.isFinite(value))throw Error();budget-=1;}
      else if(typeof value==='boolean'){budget-=value?4:5;}
      else if(typeof value==='object'){
        if(active.has(value)||(!Array.isArray(value)&&Object.getPrototypeOf(value)!==Object.prototype&&Object.getPrototypeOf(value)!==null))throw Error();
        if(Array.isArray(value)&&(value.length>1024*1024||Object.keys(value).length!==value.length))throw Error();
        active.add(value);budget-=2;
        for(const key of Reflect.ownKeys(value)){
          if(Array.isArray(value)&&key==='length')continue;
          if(typeof key!=='string'||(Array.isArray(value)&&(!Number.isInteger(Number(key))||Number(key)<0||Number(key)>=value.length||String(Number(key))!==key)))throw Error();
          const descriptor=Object.getOwnPropertyDescriptor(value,key);if(!descriptor||!('value'in descriptor)||!descriptor.enumerable)throw Error();
          if(!Array.isArray(value))budget-=Buffer.byteLength(key,'utf8')+3;visit(descriptor.value,depth+1);
        }
        active.delete(value);
      }else{throw Error();}
      if(budget<0)throw Error();
    }
    const dto:Record<string,unknown>=Object.create(null);
    for(const key of Object.keys(input)){const descriptor=Object.getOwnPropertyDescriptor(input,key);if(!descriptor||!('value'in descriptor))throw Error();if(key==='lastIndexedAt'&&descriptor.value===undefined)continue;dto[fields[key]]=descriptor.value;}
    if(!patch&&(!dto.metadata||typeof dto.metadata!=='object'||Array.isArray(dto.metadata)))throw Error();
    visit(dto,0);const encoded=JSON.stringify(dto);if(Buffer.byteLength(encoded,'utf8')>1024*1024)throw Error();return encoded;
  }catch{throw new SessionClientError('invalid_argument','Invalid typed Project source input.');}
}
/** Direct Rust Cookie draft output. Ciphertext fields remain available for
 * caller-owned encrypted storage; this response grants no cache receipt. */
export interface SessionDraftRecord {
  chat_id:string; encrypted_draft_md:string; encrypted_draft_preview:string|null;
  draft_v:number; markdown:string; preview:string|null;
}
export interface SessionDraftReadOptions { refresh?:boolean }
function draftOptions(options:SessionDraftReadOptions):string {
  if(!options||typeof options!=="object"||Array.isArray(options))throw new SessionClientError("invalid_argument","Invalid typed draft options.");
  const {refresh,...extra}=options;
  // Preserve unknown fields for the authoritative closed Rust schema to reject.
  return JSON.stringify({...extra,...(refresh===undefined?{}:{force_refresh:refresh})});
}
export class SessionEmbeds {
  private readonly native:Pick<NativeClient,"embedsVersionContent"|"embedsShareUrl">;
  private readonly invoke:<T>(op:()=>Promise<T>)=>Promise<T>;
  constructor(native:Pick<NativeClient,"embedsVersionContent"|"embedsShareUrl">,invoke:<T>(op:()=>Promise<T>)=>Promise<T>){this.native=native;this.invoke=invoke;}
  /** Explicit full-ID Personal saved read. The returned fragment URL is secret. */
  async shareUrl(id:string,expires:number|bigint=0,password:string=""):Promise<string>{
    return this.invoke(preparedNative(()=>{
      if(typeof id!=="string"||typeof password!=="string"||(typeof expires!=="bigint"&&(typeof expires!=="number"||!Number.isSafeInteger(expires))))throw new SessionClientError("invalid_argument","Invalid share options.");
      const duration=BigInt(expires);
      if(duration<-(1n<<63n)||duration>(1n<<63n)-1n)throw new SessionClientError("invalid_argument","Invalid signed integer duration.");
      return [id,duration.toString(),password] as const;
    },args=>this.native.embedsShareUrl(args[0],args[1],args[2])));
  }
  async versionContent(id:string,version:number):Promise<Record<string,unknown>>{if(!Number.isSafeInteger(version)||version<1)throw new SessionClientError("invalid_argument","Invalid integer version.");return JSON.parse(await this.invoke(preparedNative(() => [id, JSON.stringify(version)] as const, args => this.native.embedsVersionContent(args[0], args[1]))));}
}
export class SessionDrafts {
  private readonly native:Pick<NativeClient,"draftsList"|"draftsListCached"|"draftsGet"|"draftsSync">;
  private readonly invoke:<T>(operation:()=>Promise<T>)=>Promise<T>;
  constructor(native:Pick<NativeClient,"draftsList"|"draftsListCached"|"draftsGet"|"draftsSync">,invoke:<T>(operation:()=>Promise<T>)=>Promise<T>){this.native=native;this.invoke=invoke;}
  async cachedList():Promise<SessionDraftRecord[]>{return JSON.parse(await this.invoke(preparedNative(() => [] as const, () => this.native.draftsListCached())));}
  async list(options:SessionDraftReadOptions={}):Promise<SessionDraftRecord[]>{return JSON.parse(await this.invoke(preparedNative(() => [draftOptions(options)] as const, args => this.native.draftsList(args[0]))));}
  async get(id:string,options:SessionDraftReadOptions={}):Promise<SessionDraftRecord|null>{return JSON.parse(await this.invoke(preparedNative(() => [id, draftOptions(options)] as const, args => this.native.draftsGet(args[0], args[1]))));}
  async sync():Promise<Record<string,number>>{return JSON.parse(await this.invoke(preparedNative(() => [] as const, () => this.native.draftsSync())));}
}
export class SessionTasks {
  private readonly native: NativeClient;
  private readonly invoke: <T>(operation: () => Promise<T>) => Promise<T>;
  constructor(native: NativeClient, invoke: <T>(operation: () => Promise<T>) => Promise<T>) { this.native = native; this.invoke = invoke; }
  async list(filters: SessionTaskFilters): Promise<Array<Record<string, unknown>>> { return JSON.parse(await this.invoke(preparedNative(() => [workJson(filters)] as const, args => this.native.tasksList(args[0])))); }
  async show(id: string, filters: SessionTaskFilters): Promise<Record<string, unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, workJson(filters)] as const, args => this.native.tasksShow(args[0], args[1])))); }
  async create(input: SessionTaskCreate, filters: SessionTaskFilters): Promise<Record<string, unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [workJson(input), workJson(filters)] as const, args => this.native.tasksCreate(args[0], args[1])))); }
  async update(id: string, input: SessionTaskPatch, filters: SessionTaskFilters): Promise<Record<string, unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, workJson(input), workJson(filters)] as const, args => this.native.tasksUpdate(args[0], args[1], args[2])))); }
  async delete(id: string, confirmation: { confirmed: true }, filters: SessionTaskFilters): Promise<Record<string, unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, confirmation?.confirmed === true, workJson(filters)] as const, args => this.native.tasksDelete(args[0], args[1], args[2])))); }
}
export class SessionAccount {
  private readonly native: Pick<NativeClient,"accountRemindersOpen">;
  private readonly invoke:<T>(operation:()=>Promise<T>)=>Promise<T>;
  constructor(native:Pick<NativeClient,"accountRemindersOpen">,invoke:<T>(operation:()=>Promise<T>)=>Promise<T>){this.native=native;this.invoke=invoke;}
  /** Full raw fixed-route JSON, including encrypted/unknown fields. */
  async reminders(options:{signal?:AbortSignal}={}):Promise<unknown>{
    let operation:ReturnType<NativeClient["accountRemindersOpen"]>|undefined;
    let output:{releaseJson():string;discard():void}|undefined,signal:AbortSignal|undefined;
    const abort=()=>operation?.cancel();
    try{
      output=await this.invoke(preparedNative(()=>{
        signal=options.signal;
        if(signal!==undefined&&!(signal instanceof AbortSignal))throw new SessionSettingsReadError("invalid_argument","Supply an AbortSignal for reminders cancellation.",null);
        return [] as const;
      },()=>{
        operation=this.native.accountRemindersOpen();
        if(signal)addAbortListener.call(signal,"abort",abort,{once:true});
        if(appsAborted(signal))operation.cancel();
        return operation.run();
      }));
      return JSON.parse(output.releaseJson());
    }catch(error){const typed=failure(error);if(typed instanceof SessionSettingsReadError)throw typed;throw new SessionSettingsReadError(typed.code,typed.message,null);}
    finally{if(signal)removeAbortListener.call(signal,"abort",abort);try{output?.discard();}finally{operation?.cancel();}}
  }
}
export interface SessionWorkflowFileSyncOptions {sourceChat?:string;approvedPaths?:string[]}
export interface SessionWorkflowFileSaveStatus {project_id:string;status:"saved"|"pending"|"conflict"|"failed";error?:string}
function workflowFileSyncJson(workflowId:string,expectedVersion:string,options:SessionWorkflowFileSyncOptions):string{
  const fail=()=>{throw new SessionClientError("invalid_argument","Invalid Workflow file synchronization options.");};
  if(typeof workflowId!=="string"||typeof expectedVersion!=="string"||!options||typeof options!=="object"||Array.isArray(options)||(Object.getPrototypeOf(options)!==Object.prototype&&Object.getPrototypeOf(options)!==null))return fail();
  const out:Record<string,unknown>={workflow_id:workflowId,expected_version:expectedVersion};
  for(const key of Reflect.ownKeys(options)){
    if(key!=="sourceChat"&&key!=="approvedPaths")return fail();
    const d=Object.getOwnPropertyDescriptor(options,key);if(!d||!("value" in d)||!d.enumerable)return fail();
    if(d.value===undefined)continue;
    if(key==="sourceChat"){if(typeof d.value!=="string")return fail();out.source_chat=d.value;}
    else{
      const paths=d.value;if(!Array.isArray(paths)||paths.length>64||Reflect.ownKeys(paths).some(k=>k!=="length"&&(typeof k!=="string"||!Number.isInteger(Number(k))||Number(k)<0||Number(k)>=paths.length||String(Number(k))!==k)))return fail();
      const owned:string[]=[];
      for(let n=0;n<paths.length;n++){const item=Object.getOwnPropertyDescriptor(paths,String(n));if(!item||!("value" in item)||!item.enumerable||typeof item.value!=="string")return fail();owned.push(item.value);}
      out.approved_paths=owned;
    }
  }
  return JSON.stringify(out);
}
export class SessionProjects {
  /** Headless existing-binding save. Exact approved paths express local intent
   * across the explicit scope; Core still verifies focus/policy/server approval.
   * No prompt, file IO, credential discovery or CLI is used. */
  async syncWorkflowFiles(workflowId:string,expectedVersion:string,options:SessionWorkflowFileSyncOptions,filters:SessionProjectFilters):Promise<SessionWorkflowFileSaveStatus[]>{
    return JSON.parse(await this.invoke(preparedNative(()=>[workflowFileSyncJson(workflowId,expectedVersion,options),workJson(filters)] as const,args=>this.native.projectsSyncWorkflowFiles(args[0],args[1]))));
  }

  /** Raw rows, including unknown/encrypted metadata; no name/key resolution. */
  async listSourcesRaw(project:string,filters:SessionProjectFilters):Promise<unknown[]>{return JSON.parse(await this.invoke(preparedNative(() => [project, workJson(filters)] as const, args => this.native.projectsListSourcesRaw(args[0],args[1]))));}
  /** Resolve the Project key for display names only; metadata remains raw. */
  async listSourcesDecodedNames(project:string,filters:SessionProjectFilters):Promise<SessionProjectSourcesDecodedNames>{return JSON.parse(await this.invoke(preparedNative(() => [project, workJson(filters)] as const, args => this.native.projectsListSourcesDecodedNames(args[0],args[1]))));}
  async createSource(project:string,input:SessionProjectSourceCreate,filters:SessionWorkScope):Promise<SessionProjectSource>{return JSON.parse(await this.invoke(preparedNative(() => [project, sourceJson(input), workJson(filters)] as const, args => this.native.projectsCreateSource(args[0], args[1], args[2]))));}
  async updateSourceCapabilities(project:string,sourceId:string,input:SessionProjectSourceCapabilitiesPatch,filters:SessionWorkScope):Promise<SessionProjectSource>{return JSON.parse(await this.invoke(preparedNative(() => [project, sourceId, sourceJson(input,true), workJson(filters)] as const, args => this.native.projectsUpdateSourceCapabilities(args[0], args[1], args[2], args[3]))));}
  async watchTasks(project:string,input:SessionProjectTaskWatchInput,filters:SessionWorkScope):Promise<SessionProjectTaskWatch>{
    const result=JSON.parse(await this.invoke(preparedNative(() => {
    if(!input||typeof input!=="object"||Reflect.ownKeys(input).some(k=>k!=="sourceId"&&k!=="checkpoint")||typeof input.sourceId!=="string")throw new SessionClientError("invalid_argument","Supply typed Project Task watch input.");
      return [project, JSON.stringify({source_id:input.sourceId,checkpoint:input.checkpoint??null}), workJson(filters)] as const;
    }, args => this.native.projectTaskWatchOpen(args[0], args[1], args[2]))));
    if(typeof result?.id!=="string")throw new SessionClientError("protocol","Invalid Project Task watch handle.");
    return new SessionProjectTaskWatch(this.native,this.invoke,result.id);
  }

  private readonly native: NativeClient;
  private readonly invoke: <T>(operation: () => Promise<T>) => Promise<T>;
  constructor(native: NativeClient, invoke: <T>(operation: () => Promise<T>) => Promise<T>) { this.native = native; this.invoke = invoke; }
  async list(filters: SessionProjectFilters): Promise<Array<Record<string, unknown>>> { return JSON.parse(await this.invoke(preparedNative(() => [workJson(filters)] as const, args => this.native.projectsList(args[0])))); }
  async show(id: string, filters: SessionProjectFilters): Promise<Record<string, unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, workJson(filters)] as const, args => this.native.projectsShow(args[0], args[1])))); }
  async items(id: string, filters: SessionProjectFilters): Promise<Record<string, unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, workJson(filters)] as const, args => this.native.projectsItems(args[0], args[1])))); }
  /** Remove matching Project links while retaining the underlying object. */
  async unlinkItem(id: string, input: SessionProjectUnlinkInput, filters: SessionProjectFilters): Promise<Record<string, unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, workJson(input), workJson(filters)] as const, args => this.native.projectsUnlinkItem(args[0], args[1], args[2])))); }
  async create(input: SessionProjectCreate, filters: SessionProjectFilters): Promise<Record<string, unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [workJson(input), workJson(filters)] as const, args => this.native.projectsCreate(args[0], args[1])))); }
  async update(id: string, input: SessionProjectPatch, filters: SessionProjectFilters): Promise<Record<string, unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, workJson(input), workJson(filters)] as const, args => this.native.projectsUpdate(args[0], args[1], args[2])))); }
  async delete(id: string, confirmation: { confirmed: true }, filters: SessionProjectFilters): Promise<Record<string, unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, confirmation?.confirmed === true, workJson(filters)] as const, args => this.native.projectsDelete(args[0], args[1], args[2])))); }
}
export class SessionPlans {
  private readonly native: NativeClient;
  private readonly invoke: <T>(operation: () => Promise<T>) => Promise<T>;
  constructor(native: NativeClient, invoke: <T>(operation: () => Promise<T>) => Promise<T>) { this.native = native; this.invoke = invoke; }
  async list(filters: SessionPlanFilters): Promise<Array<Record<string,unknown>>> { return JSON.parse(await this.invoke(preparedNative(() => [workJson(filters)] as const, args => this.native.plansList(args[0])))); }
  async show(id: string, filters: SessionPlanFilters): Promise<Record<string,unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, workJson(filters)] as const, args => this.native.plansShow(args[0], args[1])))); }
  async create(input: SessionPlanCreate, filters: SessionPlanFilters): Promise<Record<string,unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [workJson(input), workJson(filters)] as const, args => this.native.plansCreate(args[0], args[1])))); }
  async update(id: string, input: SessionPlanPatch, filters: SessionPlanFilters): Promise<Record<string,unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, workJson(input), workJson(filters)] as const, args => this.native.plansUpdate(args[0], args[1], args[2])))); }
  async delete(id: string, confirmation: {confirmed:true}, filters: SessionPlanFilters): Promise<Record<string,unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, confirmation?.confirmed === true, workJson(filters)] as const, args => this.native.plansDelete(args[0], args[1], args[2])))); }
}
export class SessionWorkflows {
  private readonly native: NativeClient;
  private readonly invoke: <T>(operation: () => Promise<T>) => Promise<T>;
  constructor(native: NativeClient, invoke: <T>(operation: () => Promise<T>) => Promise<T>) { this.native = native; this.invoke = invoke; }
  async list(filters: SessionWorkflowFilters): Promise<Array<Record<string,unknown>>> { return JSON.parse(await this.invoke(preparedNative(() => [workJson(filters)] as const, args => this.native.workflowsList(args[0])))); }
  async show(id: string, filters: SessionWorkflowFilters): Promise<Record<string,unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, workJson(filters)] as const, args => this.native.workflowsShow(args[0], args[1])))); }
  async create(input: SessionWorkflowCreate, filters: SessionWorkflowFilters): Promise<Record<string,unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [workJson(input), workJson(filters)] as const, args => this.native.workflowsCreate(args[0], args[1])))); }
  async update(id: string, input: SessionWorkflowPatch, filters: SessionWorkflowFilters): Promise<Record<string,unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, workJson(input), workJson(filters)] as const, args => this.native.workflowsUpdate(args[0], args[1], args[2])))); }
  async delete(id: string, confirmation: {confirmed:true}, filters: SessionWorkflowFilters): Promise<Record<string,unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, confirmation?.confirmed === true, workJson(filters)] as const, args => this.native.workflowsDelete(args[0], args[1], args[2])))); }
  async run(id: string, input: SessionWorkflowRunOptions, filters: SessionWorkflowFilters): Promise<Record<string,unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, workJson(input), workJson(filters)] as const, args => this.native.workflowsRun(args[0], args[1], args[2])))); }
  async runDetail(id: string, runId: string, filters: SessionWorkflowFilters): Promise<Record<string,unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, runId, workJson(filters)] as const, args => this.native.workflowsRunDetail(args[0], args[1], args[2])))); }
  async wait(id: string, runId: string, input: SessionWorkflowWaitOptions, filters: SessionWorkflowFilters): Promise<Record<string,unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, runId, workJson(input), workJson(filters)] as const, args => this.native.workflowsWait(args[0], args[1], args[2], args[3])))); }
  async cancelRun(id: string, runId: string, filters: SessionWorkflowFilters): Promise<Record<string,unknown>> { return JSON.parse(await this.invoke(preparedNative(() => [id, runId, workJson(filters)] as const, args => this.native.workflowsCancelRun(args[0], args[1], args[2])))); }
}
import { createRequire } from "node:module";

type NativeClient = NativeEssential & {
  accountRemindersOpen():{run():Promise<{releaseJson():string;discard():void}>;cancel():void};
  plansList(filters: string): Promise<string>;
  plansShow(id: string, filters: string): Promise<string>;
  plansCreate(input: string, filters: string): Promise<string>;
  plansUpdate(id: string, input: string, filters: string): Promise<string>;
  plansDelete(id: string, confirmed: boolean, filters: string): Promise<string>;
  workflowsList(filters: string): Promise<string>;
  workflowsShow(id: string, filters: string): Promise<string>;
  workflowsCreate(input: string, filters: string): Promise<string>;
  workflowsUpdate(id: string, input: string, filters: string): Promise<string>;
  workflowsDelete(id: string, confirmed: boolean, filters: string): Promise<string>;
  workflowsRun(id: string, input: string, filters: string): Promise<string>;
  workflowsRunDetail(id: string, run: string, filters: string): Promise<string>;
  workflowsWait(id: string, run: string, input: string, filters: string): Promise<string>;
  workflowsCancelRun(id: string, run: string, filters: string): Promise<string>;
  tasksList(filters: string): Promise<string>;
  tasksShow(id: string, filters: string): Promise<string>;
  tasksCreate(input: string, filters: string): Promise<string>;
  tasksUpdate(id: string, input: string, filters: string): Promise<string>;
  tasksDelete(id: string, confirmed: boolean, filters: string): Promise<string>;
  projectsList(filters: string): Promise<string>;
  projectsShow(id: string, filters: string): Promise<string>;
  projectsItems(id: string, filters: string): Promise<string>;
  projectsSyncWorkflowFiles(input:string,filters:string):Promise<string>;
  projectsUnlinkItem(id: string, input: string, filters: string): Promise<string>;
  projectsListSourcesRaw(project:string,filters:string):Promise<string>;
  projectsListSourcesDecodedNames(project:string,filters:string):Promise<string>;
  projectsCreateSource(project:string,input:string,filters:string):Promise<string>;
  projectsUpdateSourceCapabilities(project:string,source:string,input:string,filters:string):Promise<string>;
  projectsCreate(input: string, filters: string): Promise<string>;
  projectsUpdate(id: string, input: string, filters: string): Promise<string>;
  projectsDelete(id: string, confirmed: boolean, filters: string): Promise<string>;
  projectTaskWatchOpen(project:string,input:string,filters:string):Promise<string>;
  projectTaskWatchNext(id:string):Promise<string>;
  projectTaskWatchCommit(id:string,receipt:string):Promise<void>;
  projectTaskWatchClose(id:string):void;
  loginPassword(email: string, password: string, tfa?: string, stayLoggedIn?: boolean): Promise<string>;
  importSession(session: string): Promise<void>;
  exportSession(includeSecrets: boolean): Promise<string>;
  validateSession(): Promise<void>;
  list(workspace: string): Promise<string>;
  firstPageOpen(id:string,includeSecrets:boolean,includePrivateOutput:boolean):Promise<string>;
  firstPageNext(id:string):Promise<string>;
  firstPageReceipt(id:string,stageId:string,receipt:string):void;
  firstPageCapacity(id:string,stageId:string,accepted:boolean):void;
  firstPageClose(id:string):void;
  cacheChatStage(id:string,includeSecrets:boolean):Promise<string>;
  cacheChatCommit(stageId:string,receipt:string):Promise<string>;
  cacheChatDiscard(stageId:string):void;
  chatDetailsPrepare(id:string,optionsJson:string):Promise<{releaseJson():string;discard():void}>;
  appsInventoryPrepare(): Promise<{ releaseJson(): string; discard(): void }>;
  appsInventoryOpen(): {run():Promise<{releaseJson():string;discard():void}>;cancel():void};
  openChatPrepare(id: string): Promise<{ releaseJson(): string; discard(): void }>;
  chatMessageWindow(id:string, options:string):Promise<string>;
  savedChatRead(id:string, options:string):Promise<string>;
  savedChatExactMessage(id:string, options:string):Promise<string>;
  draftsList(options:string):Promise<string>;
  draftsListCached():Promise<string>;
  embedsVersionContent(id:string,versionJson:string):Promise<string>;
  embedsShareUrl(id:string,expiresJson:string,password:string):Promise<string>;
  draftsGet(id:string,options:string):Promise<string>;
  draftsSync():Promise<string>;
  setTeam(id?: string | null): Promise<void>;
  startSend(text: string, chatId?: string | null): Promise<string>;
  nextEvent(id: string): Promise<string>;
  runSkillPrepare(app:string,skill:string,input:string):Promise<{releaseJson():string;discard():void}>;
  nextEventPrepare(id:string):Promise<{releaseJson():string;discard():void;isTerminal():boolean}>;
  startAnonymous(anonymousId: string, text: string, options: string): Promise<string>;
  cancelStream(id: string): void;
  cancel(): void;
  consent(requestId: string, approvedIds: string[]): void;
  logout(): Promise<void>;
  close(): Promise<void>;
};
export type SessionClientOptions = {
  apiUrl: string;
  appUrl?: string;
  privacy: { enhanced: boolean };
  allowPrivateOperations: boolean;
};
/** Full read's optional authenticated metadata; legacy Chat/window/send shapes remain unchanged. */
export type SessionChatWithMetadata = SessionChat & { slug?: string };
export type SessionChat = { id: string; title: string; category: string; messages: Array<{ id: string; role: string; content: string; sender: string; thinking: string; embeds: unknown[] }> };
export type SessionStreamEvent =
  | { type: "update"; update: Record<string, unknown> }
  | { type: "completed"; chat: SessionChat };
export type SessionAnonymousOptions = { piiDetection?: boolean; responseTimeoutMs?: number; signal?: AbortSignal };
export type SessionAnonymousOutcome = {
  chat: SessionChat; status: "completed"; chatId: string; messageId: string | null; userMessageId: string; assistant: string;
  category: string | null; modelName: string | null; mateName: string | null;
  followUpSuggestions: string[]; suggestedFollowupMessage?: string | null;
  taskProposals: unknown[]; taskUpdateProposals: unknown[]; taskEvents: unknown[];
  pendingTaskUpdateJobs: unknown[]; subChatEvents: unknown[]; appSettingsMemoryRequests: unknown[];
  tokenUsage: Record<string, unknown> | null; promptBudget: Record<string, unknown> | null;
};
export type SessionAnonymousStreamEvent = { type: "update"; update: Record<string, unknown> } | { type: "completed"; outcome: SessionAnonymousOutcome };
export class SessionClientError extends Error {
  readonly code: string;
  constructor(code: string, message: string) { super(message); this.name = "SessionClientError"; this.code = code; }
}
export class SessionSettingsReadError extends SessionClientError {
  readonly httpStatus:number|null;
  constructor(code:string,message:string,httpStatus:number|null){super(code,message);this.name="SessionSettingsReadError";this.httpStatus=httpStatus;}
}
function failure(error: unknown): SessionClientError {
  if (error instanceof SessionClientError) return error;
  try {
    const value = JSON.parse(error instanceof Error ? error.message : "");
    if (typeof value.code === "string" && typeof value.message === "string") {
      if(Object.hasOwn(value,"http_status")&&(value.http_status===null||(Number.isInteger(value.http_status)&&value.http_status>=100&&value.http_status<=999)))return new SessionSettingsReadError(value.code,value.message,value.http_status);
      return new SessionClientError(value.code, value.message);
    }
  } catch { /* No raw native/loader error reaches the caller. */ }
  return new SessionClientError("native_failure", "The native session operation failed.");
}
function nativeConstructor(): new (options: string) => NativeClient {
  const require = createRequire(import.meta.url);
  try {
    if (process.platform === "linux" && process.arch === "arm64") return require("../native/linux-arm64.node").NativeSessionClient;
    if (process.platform === "linux" && process.arch === "x64") return require("../native/linux-x64.node").NativeSessionClient;
    if (process.platform === "darwin" && process.arch === "arm64") return require("../native/darwin-arm64.node").NativeSessionClient;
    if (process.platform === "darwin" && process.arch === "x64") return require("../native/darwin-x64.node").NativeSessionClient;
    if (process.platform === "win32" && process.arch === "arm64") return require("../native/win32-arm64.node").NativeSessionClient;
    if (process.platform === "win32" && process.arch === "x64") return require("../native/win32-x64.node").NativeSessionClient;
  } catch { /* Missing or incompatible native artifact must not invoke a CLI. */ }
  throw new SessionClientError("native_binding_unavailable", "Install an OpenMates build containing the native session extension for this platform.");
}
// Keep the existing invoke(op) constructor contract: an operation remains a
// callable for custom adapters, while the actual SessionClient can prepare its
// owned arguments before its final original-epoch check. No Proxy, registry,
// credential or positive admission is carried by this private descriptor.
const NATIVE_PREPARATION = Symbol('native argument preparation');
const addAbortListener=EventTarget.prototype.addEventListener,removeAbortListener=EventTarget.prototype.removeEventListener;
const abortState=Object.getOwnPropertyDescriptor(AbortSignal.prototype,"aborted")!.get!;
const appsAborted=(signal:AbortSignal|undefined):boolean=>signal!==undefined&&abortState.call(signal)===true;
function preparedNative<A extends readonly unknown[], T>(prepare:()=>A, dispatch:(args:A)=>Promise<T>):()=>Promise<T> {
  const preparation=()=>{
    let owned:A|undefined=prepare();
    return ()=>{const args=owned;if(args===undefined)throw new SessionClientError("cancelled","The prepared operation was already dispatched.");owned=undefined;return dispatch(args);};
  };
  return Object.defineProperty(()=>preparation()(),NATIVE_PREPARATION,{value:preparation});
}
export class SessionClient {
  private readonly native: NativeClient;
  readonly embeds:SessionEmbeds;
  readonly drafts:SessionDrafts;
  readonly tasks: SessionTasks;
  readonly projects: SessionProjects;
  readonly account: SessionAccount;
  readonly plans: SessionPlans;
  readonly workflows: SessionWorkflows;
  readonly completionRecovery: SessionCompletionRecovery;
  private essentialEpoch=0;
  constructor(options: SessionClientOptions) {
    if (!options || typeof options.apiUrl !== "string" || typeof options.privacy?.enhanced !== "boolean" || typeof options.allowPrivateOperations !== "boolean") throw new SessionClientError("invalid_argument", "Supply an explicit endpoint, privacy and private-operation policy.");
    const Native = nativeConstructor();
    try { this.native = new Native(JSON.stringify({ api_url: options.apiUrl, app_url: options.appUrl ?? null, enhanced_privacy: options.privacy.enhanced, allow_private_operations: options.allowPrivateOperations })); }
    catch (error) { throw failure(error); }
    this.completionRecovery = new SessionCompletionRecovery(this.native,this.essentialInvoke.bind(this));
    this.embeds=new SessionEmbeds(this.native,this.essentialInvoke.bind(this));
    this.drafts=new SessionDrafts(this.native,this.essentialInvoke.bind(this));
    this.tasks = new SessionTasks(this.native, this.invoke.bind(this));
    this.projects = new SessionProjects(this.native, this.invoke.bind(this));
    this.account = new SessionAccount(this.native,op=>this.invoke(op));
    this.plans = new SessionPlans(this.native, this.invoke.bind(this));
    this.workflows = new SessionWorkflows(this.native, this.invoke.bind(this));
  }
  private async essentialInvoke<T>(operation:()=>Promise<T>,epoch=this.essentialEpoch):Promise<T>{const output=await this.invoke(operation,epoch);if(epoch!==this.essentialEpoch)throw new SessionClientError("cancelled","Session authority changed before essential output returned.");return output;}
  async watchChats():Promise<SessionChatMonitor>{const epoch=this.essentialEpoch;const raw=await this.essentialInvoke(preparedNative(() => [] as const, () => this.native.chatMonitorOpen()));const value=JSON.parse(raw);if(typeof value.id!=="string"||!value.scope)throw new SessionClientError("protocol","Invalid chat monitor handle.");return new SessionChatMonitor(this.native,this.essentialInvoke.bind(this),()=>epoch===this.essentialEpoch,value.id,value.scope);}
  private checkEpoch(epoch:number):void{if(epoch!==this.essentialEpoch)throw new SessionClientError("cancelled","Session authority changed before native dispatch.");}
  private async invoke<T>(operation: () => Promise<T>,epoch=this.essentialEpoch): Promise<T> {
    try {
      this.checkEpoch(epoch);
      const prepare=Object.getOwnPropertyDescriptor(operation,NATIVE_PREPARATION)?.value;
      const dispatch:()=>Promise<T>=typeof prepare==="function"?prepare():operation;
      this.checkEpoch(epoch);
      return await dispatch();
    } catch (error) { throw failure(error); }
  }
  /** Server cookie lifetime only; local key storage remains caller-owned. */
  async loginPassword(email: string, password: string, tfa?: string, options: { stayLoggedIn?: boolean } = {}): Promise<Record<string, unknown>> {
    const originalEpoch=this.essentialEpoch;
    if (options === null || typeof options !== "object" || Array.isArray(options) || Object.keys(options).some(key => key !== "stayLoggedIn") || (options.stayLoggedIn !== undefined && typeof options.stayLoggedIn !== "boolean")) throw new SessionClientError("invalid_argument", "Invalid password login options.");
    this.checkEpoch(originalEpoch);
    const epoch=++this.essentialEpoch;
    return JSON.parse(await this.invoke(preparedNative(() => [email, password, tfa, options.stayLoggedIn ?? false] as const, args => this.native.loginPassword(args[0], args[1], args[2], args[3])),epoch));
  }
  async importSession(session: Record<string, unknown>): Promise<void> { this.essentialEpoch++; await this.invoke(preparedNative(() => [JSON.stringify(session)] as const, args => this.native.importSession(args[0]))); }
  /** Returns cookies/master-key material only after explicit caller consent. */
  async exportSession(options: { includeSecrets: true }): Promise<{ revision: number; session: Record<string, unknown> }> { return JSON.parse(await this.invoke(preparedNative(() => [options?.includeSecrets === true] as const, args => this.native.exportSession(args[0])))); }
  async validateSession(): Promise<void> { await this.invoke(preparedNative(() => [] as const, () => this.native.validateSession())); }
  async list(workspace: "apps",options?:{signal?:AbortSignal}):Promise<Array<Record<string,unknown>>>;
  async list(workspace: "chats"|"apps"|"projects"|"workflows"|"tasks"|"settings"):Promise<Array<Record<string,unknown>>>;
  async list(workspace: "chats" | "apps" | "projects" | "workflows" | "tasks" | "settings",options?:{signal?:AbortSignal}): Promise<Array<Record<string, unknown>>> {
    if(workspace!=="apps")return JSON.parse(await this.invoke(preparedNative(() => [workspace] as const,args=>this.native.list(args[0]))));
    const epoch=this.essentialEpoch;
    let signal:AbortSignal|undefined,operation:ReturnType<NativeClient["appsInventoryOpen"]>|undefined;
    let output:{releaseJson():string;discard():void}|undefined;
    const abort=()=>operation?.cancel();
    try {
      output=await this.invoke(preparedNative(()=>{
        signal=options?.signal;
        if(signal!==undefined&&!(signal instanceof AbortSignal))throw new SessionClientError("invalid_argument","Supply an AbortSignal for Apps inventory cancellation.");
        if(appsAborted(signal))throw new SessionClientError("cancelled","The Apps inventory operation was cancelled.");
        return [] as const;
      },()=>{
        operation=this.native.appsInventoryOpen();
        if(signal)addAbortListener.call(signal,"abort",abort,{once:true});
        if(appsAborted(signal))operation.cancel();
        return operation.run();
      }),epoch);
      this.checkEpoch(epoch);
      if(appsAborted(signal))throw new SessionClientError("cancelled","The Apps inventory operation was cancelled.");
      return JSON.parse(output.releaseJson());
    } catch(error){if(operation&&!appsAborted(signal))operation.cancel();throw failure(error);}
    finally{if(signal instanceof AbortSignal)removeAbortListener.call(signal,"abort",abort);output?.discard();}
  }
  /** Persist exact opaque checkpoint/credentials bytes before committing a real storage receipt. */
  async cacheChatStage(id:string,options:{includeSecrets:true}):Promise<SessionCacheChatStage>{
    const epoch=this.essentialEpoch;
    if(options?.includeSecrets!==true)throw new SessionClientError("invalid_argument","Explicit credential storage consent is required.");
    const raw=await this.invoke(preparedNative(() => [id, true] as const, args => this.native.cacheChatStage(args[0], args[1])),epoch);
    const value:SessionCacheChatStage=JSON.parse(raw);
    if(epoch!==this.essentialEpoch){try{this.native.cacheChatDiscard(value.id);}catch{/* Best-effort discard; the cancellation below is authoritative. */}throw new SessionClientError("cancelled","Session authority changed before essential output returned.");}
    return value;
  }
  /** Receipt fields must describe the actual durable write; DTO fields alone grant no authority. */
  async cacheChatCommit(stageId:string,receipt:SessionChatDurableReceipt):Promise<SessionCacheChatPublication>{return JSON.parse(await this.essentialInvoke(()=>this.native.cacheChatCommit(stageId,JSON.stringify(receipt))));}
  async cacheChatDiscard(stageId:string):Promise<void>{await this.invoke(async()=>{this.native.cacheChatDiscard(stageId);});}
  /** Opt-in same-read callback; explicit store, credential/private consent and callback required. */
  async readChatWithFirstPage(id:string,store:SessionFirstPageStore,options:SessionFirstPageOptions):Promise<SessionCacheChatPublication>{
    const epoch=this.essentialEpoch;
    return readChatWithFirstPage(this.native as NativeFirstPage,this.essentialInvoke.bind(this),()=>epoch===this.essentialEpoch,id,store,options);
  }
  /** Temporary structured direct result. No Apps history save or automatic file download. */
  async runSkill(app:string,skill:string,input:Record<string,unknown>):Promise<unknown>{
    const epoch=this.essentialEpoch;
    let encoded:string;
    try{encoded=JSON.stringify(input);}catch{throw new SessionClientError("invalid_argument","Invalid App input JSON.");}
    // Serialization may synchronously invoke caller-owned toJSON/getters.
    if(epoch!==this.essentialEpoch)throw new SessionClientError("cancelled","Session authority changed before App dispatch.");
    const output=await this.invoke(()=>this.native.runSkillPrepare(app,skill,encoded));
    try{
      if(epoch!==this.essentialEpoch)throw new SessionClientError("cancelled","Session authority changed before App output returned.");
      return JSON.parse(output.releaseJson());
    }catch(error){throw failure(error);}
    finally{output.discard();}
  }
  /** Shared rich read, default requested latest limit30/stored; may return fewer; never launches or discovers CLI state. */
  async chatDetails(id:string,options:SessionChatDetailsOptions={}):Promise<SessionChatDetailsRead>{
    const epoch=this.essentialEpoch;
    const output=await this.invoke(preparedNative(() => [id, JSON.stringify(options)] as const, args => this.native.chatDetailsPrepare(args[0], args[1])),epoch);
    try {
      if(epoch!==this.essentialEpoch)throw new SessionClientError("cancelled","Session authority changed before essential output returned.");
      return JSON.parse(output.releaseJson());
    } catch(error){throw failure(error);}
    finally{output.discard();}
  }
  async openChat(id: string): Promise<SessionChatWithMetadata> {
    const epoch = this.essentialEpoch;
    const output = await this.invoke(preparedNative(() => [id] as const, args => this.native.openChatPrepare(args[0])),epoch);
    try {
      if (epoch !== this.essentialEpoch) throw new SessionClientError("cancelled", "Session authority changed before essential output returned.");
      return JSON.parse(output.releaseJson());
    } catch (error) { throw failure(error); }
    finally { output.discard(); }
  }
  async chatMessageWindow(id:string, options:SessionMessageWindowOptions = {}):Promise<SessionMessageWindow> { return JSON.parse(await this.essentialInvoke(preparedNative(() => [id, JSON.stringify(options)] as const, args => this.native.chatMessageWindow(args[0], args[1])))); }
  async savedChatRead(id:string, options:SessionSavedChatReadOptions = {}):Promise<SessionSavedChatRead> { return JSON.parse(await this.essentialInvoke(preparedNative(() => [id, JSON.stringify(options)] as const, args => this.native.savedChatRead(args[0], args[1])))); }
  async savedChatExactMessage(id:string, options:SessionSavedChatExactOptions):Promise<SessionSavedChatExactMessage> { return JSON.parse(await this.essentialInvoke(preparedNative(() => [id, JSON.stringify(options)] as const, args => this.native.savedChatExactMessage(args[0], args[1])))); }
  async setTeam(id: string | null): Promise<void> { this.essentialEpoch++; await this.invoke(preparedNative(() => [id] as const, args => this.native.setTeam(args[0]))); }
  cancel(): void { this.essentialEpoch++; try { this.native.cancel(); } catch (error) { throw failure(error); } }
  respondToConsent(requestId: string, approvedIds: string[]): void { try { this.native.consent(requestId, approvedIds); } catch (error) { throw failure(error); } }
  async *stream(text: string, options: { chatId?: string; signal?: AbortSignal } = {}): AsyncGenerator<SessionStreamEvent> {
    const epoch = this.essentialEpoch;
    if (options.signal?.aborted) throw new SessionClientError("cancelled", "The operation was cancelled.");
    const id = await this.invoke(preparedNative(() => [text, options.chatId] as const, args => this.native.startSend(args[0], args[1])),epoch);
    let finished = false;
    const abort = () => {
      try { this.native.cancelStream(id); } catch { /* The exact stream may already have ended. */ }
    };
    options.signal?.addEventListener("abort", abort, { once: true });
    if (options.signal?.aborted) abort();
    try {
      if (epoch !== this.essentialEpoch) throw new SessionClientError("cancelled", "Session authority changed before stream output returned.");
      while (true) {
        const output = await this.invoke(() => this.native.nextEventPrepare(id));
        let event;
        try {
          if (epoch !== this.essentialEpoch) throw new SessionClientError("cancelled", "Session authority changed before stream output returned.");
          event = JSON.parse(output.releaseJson());
        } catch (error) { throw failure(error); }
        finally { output.discard(); }
        if (event.type === "error") { finished = true; throw new SessionClientError(event.error.code, event.error.message); }
        if (event.type === "completed") finished = true;
        yield event as SessionStreamEvent;
        if (finished) return;
      }
    } finally {
      options.signal?.removeEventListener("abort", abort);
      if (!finished) {
        abort();
        // Cooperatively finish the SDK transaction; never abandon a credential
        // rotation or ambiguously committed request when a consumer stops early.
        try { while (true) {
          const output = await this.native.nextEventPrepare(id);
          let terminal;
          try { terminal = output.isTerminal(); } finally { output.discard(); }
          if (terminal) break;
        } } catch { /* Exact native stream settled/refused; no foreign plaintext allocation. */ }
      }
    }
  }
  async send(text: string, options: { chatId?: string; signal?: AbortSignal } = {}): Promise<SessionChat> {
    for await (const event of this.stream(text, options)) if (event.type === "completed") return event.chat;
    throw new SessionClientError("protocol", "The native stream ended without a result.");
  }
  async logout(): Promise<void> { this.essentialEpoch++; await this.invoke(preparedNative(() => [] as const, () => this.native.logout())); }
  /** Public, ephemeral inference with a caller-owned ID; never uses account credentials. */
  async *streamAnonymous(anonymousId: string, text: string, options: SessionAnonymousOptions = {}): AsyncGenerator<SessionAnonymousStreamEvent> {
    const epoch=this.essentialEpoch;
    const { signal, ...nativeOptions } = options;
    if (signal?.aborted) throw new SessionClientError("cancelled", "The operation was cancelled.");
    const wire = Object.fromEntries(Object.entries(nativeOptions).map(([key,value]) => [key === "piiDetection" ? "pii_detection" : key === "responseTimeoutMs" ? "response_timeout_ms" : key,value]));
    if (Object.keys(wire).length !== Object.keys(nativeOptions).length) throw new SessionClientError("invalid_argument", "Duplicate anonymous option.");
    const id = await this.invoke(preparedNative(() => [anonymousId, text, JSON.stringify(wire)] as const, args => this.native.startAnonymous(args[0], args[1], args[2])),epoch);
    const cancel = () => { try { this.native.cancelStream(id); } catch (error) { throw failure(error); } };
    const abort = () => { try { cancel(); } catch { /* The exact stream may already have ended. */ } };
    let finished = false;
    if(signal)addAbortListener.call(signal,"abort",abort,{once:true});
    if (signal?.aborted) abort();
    try {
      while (true) {
        const event = JSON.parse(await this.invoke(() => this.native.nextEvent(id)));
        if (event.type === "error") { finished = true; throw new SessionClientError(event.error.code,event.error.message); }
        if (event.type === "completed") { finished = true; yield {type:"completed",outcome:{...event.outcome,chat:event.chat}}; return; }
        yield event as SessionAnonymousStreamEvent;
      }
    } finally {
      signal?.removeEventListener("abort",abort);
      if (!finished) {
        abort();
        try { while (true) { const event=JSON.parse(await this.native.nextEvent(id)); if (event.type==="error" || event.type==="completed") break; } } catch { /* Scoped cancellation settled. */ }
      }
    }
  }
  async sendAnonymous(anonymousId: string, text: string, options: SessionAnonymousOptions = {}): Promise<SessionAnonymousOutcome> {
    for await (const event of this.streamAnonymous(anonymousId,text,options)) if (event.type==="completed") return event.outcome;
    throw new SessionClientError("protocol","The anonymous stream ended without a result.");
  }
  async close(): Promise<void> { this.essentialEpoch++; await this.invoke(preparedNative(() => [] as const, () => this.native.close())); }
}
