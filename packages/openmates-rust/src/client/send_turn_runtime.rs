//! The one saved-turn stream/recovery algorithm. Network/socket state belongs
//! to its caller. Concrete typed phases distinguish Client work from the owned
//! driver; receive_turn itself takes no Client. The compatibility adapter below
//! retains the old borrow; the separate owned adapter uses exact typed phases.
use super::*;
use std::{future::Future,pin::Pin};
#[cfg(not(target_arch="wasm32"))]
pub(in crate::client) type TurnPhaseFuture<'a,T>=Pin<Box<dyn Future<Output=Result<T>>+Send+'a>>;
#[cfg(target_arch="wasm32")]
pub(in crate::client) type TurnPhaseFuture<'a,T>=Pin<Box<dyn Future<Output=Result<T>>+'a>>;
#[cfg(not(target_arch="wasm32"))]
pub(in crate::client) trait PhasePlatform:Send{}
#[cfg(not(target_arch="wasm32"))]
impl<T:Send> PhasePlatform for T{}
#[cfg(target_arch="wasm32")]
pub(in crate::client) trait PhasePlatform{}
#[cfg(target_arch="wasm32")]
impl<T> PhasePlatform for T{}
/// Private typed Rust phases, never a generic callback/URL/payload grant. Only
/// actual core implementations can provide them. No serde/foreign constructor.
pub(in crate::client) trait SavedTurnClientPhases:PhasePlatform {
    fn check<'a>(&'a mut self,scope:&'a AsyncCryptoScope,chat:&'a str,generation:u64)->TurnPhaseFuture<'a,()>;
    fn deliver_update<'a>(&'a mut self,scope:&'a AsyncCryptoScope,chat:&'a str,updates:&'a mpsc::Sender<StreamUpdate>,cancel:&'a CancellationToken,update:StreamUpdate)->TurnPhaseFuture<'a,()>;
    fn persist_focus_event<'a>(&'a mut self,ws:&'a mut Socket,kind:&'a str,event:&'a Value,chat:&'a str,key:&'a [u8;32],previous:&'a mut Value)->TurnPhaseFuture<'a,()>;
    fn project_routing_catalog<'a>(&'a mut self,id:&'a str)->TurnPhaseFuture<'a,Vec<Value>>;
    fn subchat_consent<'a>(&'a mut self,ws:&'a mut Socket,event:&'a Value,chat:&'a str,task:&'a str,updates:&'a mpsc::Sender<StreamUpdate>,cancel:&'a CancellationToken,policy:SendConsentPolicy)->TurnPhaseFuture<'a,Vec<(String,Value)>>;
    fn memory_consent<'a>(&'a mut self,ws:&'a mut Socket,event:&'a Value,chat:&'a str,message:&'a str,key:&'a [u8;32],memories:&'a [Value],mappings:&'a [Value],updates:&'a mpsc::Sender<StreamUpdate>,cancel:&'a CancellationToken,policy:SendConsentPolicy)->TurnPhaseFuture<'a,(Vec<(String,Value)>,SendMemoryRequest,Vec<Value>)>;
    fn replay_outputs<'a>(&'a mut self,ws:&'a mut Socket,outputs:&'a BTreeMap<String,Value>,root:Option<(&'a str,&'a [u8;32])>)->TurnPhaseFuture<'a,usize>;
    fn persist_stream_artifacts<'a>(&'a mut self,ws:&'a mut Socket,chat:&'a str,message:&'a str,key:&'a [u8;32],task:&'a str,embeds:&'a BTreeMap<String,Value>,checkpoints:&'a [Value])->TurnPhaseFuture<'a,Vec<Item>>;
    fn open_chat_live<'a>(&'a mut self,id:&'a str)->TurnPhaseFuture<'a,Chat>;
    fn finish_task_jobs<'a>(&'a mut self,ws:&'a mut Socket,observed:&'a mut SendObservations,id:&'a str,message:&'a str,key:&'a [u8;32],cancel:&'a CancellationToken,options:&'a SendOptions)->TurnPhaseFuture<'a,()>;
    fn project_create<'a>(&'a mut self,ws:&'a mut Socket,kind:&'a str,event:&'a Value,chat:&'a str,state:&'a mut project_create_request::ProjectCreateState)->TurnPhaseFuture<'a,()>;
    fn owner_id(&mut self)->TurnPhaseFuture<'_,String>;
    fn current_messages_version<'a>(&'a mut self,id:&'a str,key:&'a [u8;32],version:u64)->TurnPhaseFuture<'a,u64>;
}
/// Compatibility implementation only. The owned implementation must use
/// original-resource typed steps, never expose this borrowed Client to its IO.
pub(in crate::client) struct BorrowedTurnPhases<'a>{pub(in crate::client) client:&'a mut Client}
impl SavedTurnClientPhases for BorrowedTurnPhases<'_>{
    fn check<'a>(&'a mut self,scope:&'a AsyncCryptoScope,chat:&'a str,generation:u64)->TurnPhaseFuture<'a,()>{Box::pin(async move{scope.check_chat(self.client,chat)?;if self.client.generation!=generation{return Err(Error::Cancelled)}Ok(())})}
    fn deliver_update<'a>(&'a mut self,scope:&'a AsyncCryptoScope,chat:&'a str,updates:&'a mpsc::Sender<StreamUpdate>,cancel:&'a CancellationToken,update:StreamUpdate)->TurnPhaseFuture<'a,()>{Box::pin(self.client.deliver_turn_update(scope,chat,updates,cancel,update))}
    fn persist_focus_event<'a>(&'a mut self,ws:&'a mut Socket,kind:&'a str,event:&'a Value,chat:&'a str,key:&'a [u8;32],previous:&'a mut Value)->TurnPhaseFuture<'a,()>{Box::pin(self.client.persist_focus_event(ws,kind,event,chat,key,previous))}
    fn project_routing_catalog<'a>(&'a mut self,id:&'a str)->TurnPhaseFuture<'a,Vec<Value>>{Box::pin(self.client.project_routing_catalog(id))}
    fn subchat_consent<'a>(&'a mut self,ws:&'a mut Socket,event:&'a Value,chat:&'a str,task:&'a str,updates:&'a mpsc::Sender<StreamUpdate>,cancel:&'a CancellationToken,policy:SendConsentPolicy)->TurnPhaseFuture<'a,Vec<(String,Value)>>{Box::pin(self.client.subchat_consent(ws,event,chat,task,updates,cancel,policy))}
    fn memory_consent<'a>(&'a mut self,ws:&'a mut Socket,event:&'a Value,chat:&'a str,message:&'a str,key:&'a [u8;32],memories:&'a [Value],mappings:&'a [Value],updates:&'a mpsc::Sender<StreamUpdate>,cancel:&'a CancellationToken,policy:SendConsentPolicy)->TurnPhaseFuture<'a,(Vec<(String,Value)>,SendMemoryRequest,Vec<Value>)>{Box::pin(self.client.memory_consent(ws,event,chat,message,key,memories,mappings,updates,cancel,policy))}
    fn replay_outputs<'a>(&'a mut self,ws:&'a mut Socket,outputs:&'a BTreeMap<String,Value>,root:Option<(&'a str,&'a [u8;32])>)->TurnPhaseFuture<'a,usize>{Box::pin(self.client.replay_outputs(ws,outputs,root))}
    fn persist_stream_artifacts<'a>(&'a mut self,ws:&'a mut Socket,chat:&'a str,message:&'a str,key:&'a [u8;32],task:&'a str,embeds:&'a BTreeMap<String,Value>,checkpoints:&'a [Value])->TurnPhaseFuture<'a,Vec<Item>>{Box::pin(self.client.persist_stream_artifacts(ws,chat,message,key,task,embeds,checkpoints))}
    fn open_chat_live<'a>(&'a mut self,id:&'a str)->TurnPhaseFuture<'a,Chat>{Box::pin(self.client.open_chat_live(id))}
    fn finish_task_jobs<'a>(&'a mut self,ws:&'a mut Socket,observed:&'a mut SendObservations,id:&'a str,message:&'a str,key:&'a [u8;32],cancel:&'a CancellationToken,options:&'a SendOptions)->TurnPhaseFuture<'a,()>{Box::pin(self.client.finish_task_jobs(ws,observed,id,message,key,cancel,options))}
    fn project_create<'a>(&'a mut self,ws:&'a mut Socket,kind:&'a str,event:&'a Value,chat:&'a str,state:&'a mut project_create_request::ProjectCreateState)->TurnPhaseFuture<'a,()>{Box::pin(self.client.project_create_event(ws,kind,event,chat,state))}
    fn owner_id(&mut self)->TurnPhaseFuture<'_,String>{Box::pin(async move{let owner=text(&self.client.user,"id");Ok(if owner.is_empty(){required(&self.client.user,"user_id")?.into()}else{owner.into()})})}
    fn current_messages_version<'a>(&'a mut self,id:&'a str,key:&'a [u8;32],version:u64)->TurnPhaseFuture<'a,u64>{Box::pin(async move{
        let path = self.client.scoped("/v1/chats/metadata/batch")?;
        let current = self.client
            .request(Method::POST, &path, Some(json!({"chat_ids":[id]})))
            .await?;
        let row = current["chats"]
            .as_array()
            .ok_or_else(|| super::send::refusal_trace::protocol_at!())?
            .iter()
            .find(|r| text(r, "id") == id)
            .ok_or(Error::Forbidden)?
            .clone();
        let wrapping = self.client.wrapping_capability().await?;
        if self.client.chat_key_with_capability(&row,&wrapping).await?.as_ref() != key {
            return Err(Error::Crypto);
        }
        let latest = row["messages_v"].as_u64().ok_or_else(|| super::send::refusal_trace::protocol_at!())?;
        if latest < version {
            return Err(super::send::refusal_trace::protocol_at!());
        }
        self.client.insert_chat_row(id.into(), row);
        Ok(latest)
    })}
}
/// P11: after the turn's artifacts are persisted, adopt its application files,
/// application and test results into the chat's focused Project (the phase is
/// a no-op without a focus). Failures are report rows on the outcome; only
/// cancellation and phase faults propagate.
// Targets without the hosted writer (wasm, non-unix) compile an empty body.
#[allow(unused_variables)]
async fn adopt_turn_embeds<P: SavedTurnClientPhases>(
    phases: &mut P,
    ws: &mut Socket,
    chat: &str,
    rows: &BTreeMap<String, Value>,
    observed: &mut SendObservations,
) -> Result<()> {
    #[cfg(all(feature = "workflow-yaml", unix))]
    match crate::client::project_embed_adoption::turn_adoption_event(rows) {
        Ok(Some(event)) => {
            phases
                .project_create(
                    ws,
                    crate::client::project_embed_adoption::TURN_ADOPTION_KIND,
                    &event,
                    chat,
                    &mut observed.project_create,
                )
                .await?
        }
        Ok(None) => {}
        Err(Error::Cancelled) => return Err(Error::Cancelled),
        Err(_) => observed
            .project_create
            .push_adoption(json!({"status":"failed","code":"invalid_request"})),
    }
    Ok(())
}
/// True for a Memory write job frame of this turn's chat that this send handles,
/// in the stream and among the trailing frames alike.
fn routes_memory_job_frame(options: &SendOptions, kind: &str, frame: &Value, chat: &str) -> bool {
    options.memory_write_jobs
        && crate::client::memory_write_jobs::is_job_frame(kind)
        && text(frame, "chat_id") == chat
}
/// Replays this turn's sealed outputs until they settle. Another device of the
/// same owner (a web tab showing the chat, or the device that completed the
/// job) may replay the same outputs at the same time; the loser of that race
/// gets a refused write (`Protocol`, e.g. `embed_revision_conflict`) or a
/// version fence (`Conflict`). A new replay re-reads each output's status and
/// skips, after verifying, what the other device acknowledged, so a lost race
/// is retried within the turn deadline. The server fences still decide every
/// write; any other error ends the turn.
#[allow(clippy::too_many_arguments)] // One turn's replay context; grouping it adds no meaning.
async fn replay_until_settled<P: SavedTurnClientPhases>(
    phases: &mut P,
    ws: &mut Socket,
    outputs: &BTreeMap<String, Value>,
    root: (&str, &[u8; 32]),
    turn_scope: &AsyncCryptoScope,
    generation: u64,
    deadline: crate::platform::time::Instant,
    cancel: &CancellationToken,
    step: &'static str,
) -> Result<()> {
    let mut replays = 0u32;
    loop {
        match phases
            .replay_outputs(ws, outputs, Some(root))
            .await
            .inspect_err(|_| super::send::refusal_trace::note_step(step))
        {
            Ok(_) => {
                if replays > 0 {
                    // The lost race was settled; drop its diagnostic site.
                    let _ = super::send::refusal_trace::take();
                }
                return Ok(());
            }
            Err(error)
                if super::recovery::terminal_replay_retry(&error, replays)
                    && crate::platform::time::Instant::now() + super::recovery::TERMINAL_REPLAY_RETRY
                        < deadline =>
            {
                replays += 1;
                tokio::select! {
                    biased;
                    _ = cancel.cancelled() => return Err(Error::Cancelled),
                    _ = crate::platform::time::sleep(super::recovery::TERMINAL_REPLAY_RETRY) => {}
                }
                phases.check(turn_scope, root.0, generation).await?;
            }
            Err(error) => return Err(error),
        }
    }
}
/// Delay between claims while another device of the same owner holds the lease.
const CLAIM_CONFLICT_RETRY: Duration = Duration::from_millis(500);
#[allow(clippy::too_many_arguments)]
pub(in crate::client) async fn receive_turn<P:SavedTurnClientPhases>(phases:&mut P,ws:&mut Socket,
    prepared_turn:prepared_turn::PreparedTurnContext,turn_scope:&AsyncCryptoScope,
    id:&str,turn:&str,message:&str,input:&str,key:&[u8;32],wrapped:&str,baseline:u64,new_chat:bool,
    chat:&mut Chat,updates:&mpsc::Sender<StreamUpdate>,cancel:&CancellationToken,generation:u64,
    options:&SendOptions,trace:&mut SendTrace,task_id:&mut String)->Result<SendOutcome>{
        let prepared_turn::PreparedTurnContext{team,projects,sender,memories,mut prepared,wait_ai,mut focus_state}=prepared_turn;
        let mut observed=Plain::new(SendObservations::default());
        let mut confirmed = false;
        let mut admitted = false;
        let mut admission_notified = false;
        let mut version = baseline + 1;
        let mut content = Plain::new(String::new());
        let mut thinking = Plain::new(String::new());
        let mut final_frame=Plain::new(None::<Value>);
        // Idle limit: each received frame restarts it (long coding turns keep streaming).
        let mut turn_deadline = super::turn_deadline::TurnDeadline::start(crate::platform::time::Instant::now(),
            Duration::from_millis(options.response_timeout_ms.unwrap_or(600_000)));
        let mut queued=Plain::new(None::<Value>);
        let mut deferred=Plain::new(std::collections::VecDeque::new());
        let mut consent_requests = std::collections::HashSet::new();
        let mut streamed_embeds=Plain::new(BTreeMap::new());
        // Tasks this turn handed over from (focus continuation); they still own their embeds.
        let mut earlier_tasks: Vec<String> = Vec::new();
        let mut checkpoints=Plain::new(vec![]);
        let mut generated_header=Plain::new(Value::Null);
        let mut recovery_outputs=Plain::new(BTreeMap::new());
        loop {
            trace.phase = SendPhase::StreamReceive;
            let event = if let Some(event) = deferred.pop_front() {
                event
            } else {
                let received=tokio::select! {biased;_=cancel.cancelled()=>return Err(Error::Cancelled),r=crate::platform::time::timeout_at(turn_deadline.at(),receive(ws))=>r.map_err(|_|Error::Offline)??};
                turn_deadline.on_frame(crate::platform::time::Instant::now());
                received
            };
            let (kind,p)=event;let p=Plain::new(p);
            trace.observe_frame(&kind);
            trace.phase = SendPhase::FrameValidation;
            phases.check(turn_scope,id,generation).await?;
            if kind == "chat_turn_preflight_ack" && text(&p, "turn_id") == turn {
                required(&p, "preflight_id")?;
                admitted = true;
                if let Some(v) = p["committed_messages_v"].as_u64() {
                    version = v
                }
            }
            if kind == "chat_message_confirmed"
                && text(&p, "chat_id") == id
                && text(&p, "message_id") == message
            {
                confirmed = true;
                if let Some(v) = p["new_messages_v"].as_u64() {
                    version = v
                }
            }
            if (admitted || confirmed) && !admission_notified {
                admission_notified = true;
                phases.deliver_update(&turn_scope,id,updates,cancel,StreamUpdate::Admitted {
                        chat_id: id.into(),
                        message_id: message.into(),
                    }).await?;
            }
            let same = belongs_to_turn(&p, id, message, turn);
            if same {
                let known = task_id.clone();
                adopt_turn_task(task_id, text(&p, "task_id"), &mut earlier_tasks)?;
                if *task_id != known {
                    phases.deliver_update(&turn_scope,id,updates,cancel,StreamUpdate::TaskAssigned {
                        chat_id: id.into(),
                        message_id: message.into(),
                        task_id: task_id.clone(),
                    }).await?;
                }
            }
            if owns_metadata(&p, id, message, turn, &task_id) {
                observed.capture_owned(&kind, &p)?;
            }
            if kind == "task_update_jobs_available"
                && owns_metadata(&p, id, message, turn, &task_id)
            {
                observed.capture_jobs(&p, id)?;
            }
            if kind == "message_queued" && same {
                queued.wipe();*queued=Some(p.clone());
            }
            if let Some(frame) = &*queued
                && admitted
                && confirmed
            {
                let mode = match frame["queue_mode"].as_str() {
                    Some("follow_up") => SendQueueMode::FollowUp,
                    Some("steer") => SendQueueMode::Steer,
                    _ => return Err(super::send::refusal_trace::protocol_at!()),
                };
                let revision = frame["queue_revision"]
                    .as_u64()
                    .filter(|v| *v > 0)
                    .ok_or_else(|| super::send::refusal_trace::protocol_at!())?;
                chat.messages.push(Message {
                    id: message.into(),
                    role: "user".into(),
                    content: crate::privacy::restore(&prepared.text, &prepared.mappings)?,
                    sender: sender.clone(),
                    ..Message::default()
                });
                phases.deliver_update(&turn_scope,id,updates,cancel,StreamUpdate::Status(
                        "Message saved and queued for the active assistant turn.".into(),
                    )).await?;
                let mut outcome = Plain::new(observed.into_inner().finish(chat.clone(), message, None, SendStatus::Queued));
                outcome.queue_mode = Some(mode);
                outcome.queue_revision = Some(revision);
                phases.check(turn_scope,id,generation).await?;
                return Ok(outcome.into_inner());
            }
            trace.observe_discovery(&kind, &p);
            // Discovery is owner-global and can precede the final frame. It is
            // still validated, but never authorizes this turn's completion.
            crate::client::recovery::capture(&kind, &p, &mut recovery_outputs)?;
            trace.phase = SendPhase::FrameValidation;
            capture_artifact(
                &kind,
                &p,
                id,
                &task_id,
                &mut streamed_embeds,
                &mut checkpoints,
            )?;
            if kind == "ai_typing_started" && same {
                generated_header.wipe();*generated_header=p.clone();
            }
            if ["focus_mode_activated", "focus_phases_updated"].contains(&kind.as_str())
                && text(&p, "chat_id") == id
                && (text(&p, "task_id").is_empty() || text(&p, "task_id") == task_id.as_str())
            {
                trace.phase = SendPhase::FocusPersist;
                phases.persist_focus_event(ws, &kind, &p, id, key, &mut focus_state)
                    .await?;
                if kind == "focus_mode_activated" {
                    observed.project_create.mark_focus_persisted(text(&p, "focus_id"));
                }
                trace.phase = SendPhase::FrameValidation;
            }
            if kind == "project_focus_catalog_requested"
                && text(&p, "chat_id") == id
                && p.get("team_id").and_then(Value::as_str) == team.as_deref()
            {
                trace.phase = SendPhase::ProjectCatalog;
                let project = required(&p, "project_id")?;
                if !projects.iter().any(|v| text(v, "project_id") == project) {
                    trace.observe_frame("catalog_project_not_candidate");
                    return Err(Error::Forbidden);
                }
                let focuses=Plain::new(match phases.project_routing_catalog(project).await{Ok(focuses)=>Some(focuses),Err(error @ (Error::Cancelled|Error::Expired|Error::Authentication|Error::Forbidden))=>{trace.observe_frame("catalog_lookup_refused");return Err(error)},Err(_)=>None});
                phases.check(turn_scope,id,generation).await?;
                transport::send_plaintext(ws,"project_focus_catalog_result",json!({"chat_id":id,"request_id":required(&p,"request_id")?,"project_id":project,"focuses":&*focuses})).await?;
                trace.phase = SendPhase::FrameValidation;
            }
            if options.project_create_requests
                && matches!(kind.as_str(), "project_create_requested" | "project_create_confirmed" | "project_create_error")
                && text(&p, "chat_id") == id
            {
                // The turn waits for our report; creation and its reply frames are
                // handled here and the stream resumes afterwards in this same loop.
                trace.phase = SendPhase::ProjectPhase;
                observed.project_create.machine_decision = options.machine_project.clone();
                phases.project_create(ws, &kind, &p, id, &mut observed.project_create).await?;
                trace.phase = SendPhase::FrameValidation;
            }
            if options.project_file_jobs
                && PROJECT_FILE_JOBS_AVAILABLE
                && matches!(kind.as_str(), "project_file_operation_available" | "project_file_operation_request")
                && text(&p, "chat_id") == id
            {
                // Hosted Project file tool calls run here; the turn resumes afterwards.
                observed.project_create.file_jobs.approve_writes = options.approve_project_file_writes;
                observed.project_create.file_jobs.set_mappings(&prepared.mappings);
                trace.phase = SendPhase::ProjectPhase;
                phases.project_create(ws, &kind, &p, id, &mut observed.project_create).await?;
                trace.phase = SendPhase::FrameValidation;
                for notice in observed.project_create.file_jobs.take_notices() {
                    phases.deliver_update(&turn_scope,id,updates,cancel,StreamUpdate::Status(notice)).await?;
                }
            }
            if routes_memory_job_frame(options, &kind, &p, id) {
                // save_memory waits for our claim and result; the turn resumes afterwards.
                observed.project_create.memory_jobs.set_chat_key(key);
                observed.project_create.memory_jobs.set_mappings(&prepared.mappings);
                phases.project_create(ws, &kind, &p, id, &mut observed.project_create).await?;
                for notice in observed.project_create.memory_jobs.take_notices() {
                    phases.deliver_update(&turn_scope,id,updates,cancel,StreamUpdate::Status(notice)).await?;
                }
            }
            if kind == "sub_chat_confirmation_required"
                && text(&p, "chat_id") == id
                && !task_id.is_empty()
                && text(&p, "task_id") == task_id.as_str()
                && consent_requests.insert(format!("subchat:{task_id}"))
            {
                deferred.extend(
                    phases.subchat_consent(
                        ws,
                        &p,
                        id,
                        &task_id,
                        updates,
                        cancel,
                        options.sub_chat_consent,
                    )
                    .await?,
                );
            }
            if kind == "request_app_settings_memories"
                && admit_memory_request(&p, id, message, &mut consent_requests)
            {
                let (frames, record, added) = phases
                    .memory_consent(
                        ws,
                        &p,
                        id,
                        message,
                        key,
                        &memories,
                        &prepared.mappings,
                        updates,
                        cancel,
                        options.memory_consent,
                    )
                    .await?;
                // Placeholders minted for Memory bodies must restore the answer.
                prepared.mappings.extend(added);
                deferred.extend(frames);
                if observed.memories.len() >= 64 {
                    return Err(super::send::refusal_trace::protocol_at!());
                }
                observed.memories.push(record);
            }
            if kind == "ai_task_initiated"
                && text(&p, "chat_id") == id
                && text(&p, "user_message_id") == message
            {
                let known = task_id.clone();
                adopt_turn_task(task_id, text(&p, "task_id"), &mut earlier_tasks)?;
                if *task_id != known {
                    phases.deliver_update(&turn_scope,id,updates,cancel,StreamUpdate::TaskAssigned {
                        chat_id: id.into(),
                        message_id: message.into(),
                        task_id: task_id.clone(),
                    }).await?;
                }
            }
            if kind == "thinking_chunk"
                && text(&p, "chat_id") == id
                && !task_id.is_empty()
                && text(&p, "task_id") == task_id.as_str()
            {
                thinking.push_str(text(&p, "content"));
                phases.deliver_update(&turn_scope,id,updates,cancel,StreamUpdate::Content {
                        content: content.clone(),
                        thinking: thinking.clone(),
                        mate: String::new(),
                    }).await?;
            }
            if same && (kind == "ai_message_update" || kind == "ai_background_response_completed") {
                if let Some(full) = p
                    .get("full_content_so_far")
                    .or_else(|| p.get("full_content"))
                    .and_then(Value::as_str)
                {
                    replace_text(&mut content,full.into())
                }
                phases.deliver_update(&turn_scope,id,updates,cancel,StreamUpdate::Content {
                        content: content.clone(),
                        thinking: thinking.clone(),
                        mate: text(&p, "category").into(),
                    }).await?;
                if (p["is_final_chunk"] == true || kind == "ai_background_response_completed")
                    && !has_continuation(&p)
                {
                    trace.final_seen = true;
                    // Name the failing final-frame check in the opt-in test
                    // diagnostic (fixed labels only, never payload content).
                    if p["recovery_protocol_version"] != 1 {
                        trace.observe_frame("final_without_recovery_protocol");
                        return Err(super::send::refusal_trace::protocol_at!());
                    }
                    if text(&p, "recovery_turn_id") != turn {
                        trace.observe_frame("final_for_other_recovery_turn");
                        return Err(super::send::refusal_trace::protocol_at!());
                    }
                    if text(&p, "recovery_job_id").is_empty() {
                        trace.observe_frame("final_without_recovery_job");
                    }
                    required(&p, "recovery_job_id")?;
                    if text(&p, "message_id").is_empty() {
                        trace.observe_frame("final_without_message_id");
                    }
                    required(&p, "message_id")?;
                    final_frame.wipe();*final_frame=Some(p.clone());
                }
            }
            if same
                && ["ai_task_error", "ai_error", "queued_handoff_paused"].contains(&kind.as_str())
            {
                return Err(super::send::refusal_trace::protocol_at!());
            }
            if let Some(refusal) = terminal_refusal(&kind, &p, id, message, &task_id, &earlier_tasks) {
                return Err(refusal);
            }
            if !wait_ai && admitted && confirmed {
                chat.messages.push(Message {
                    id: message.into(),
                    role: "user".into(),
                    content: input.into(),
                    sender: sender.clone(),
                    ..Message::default()
                });
                phases.deliver_update(&turn_scope,id,updates,cancel,StreamUpdate::Completed {
                        chat_id: id.into(),
                        message_id: message.into(),
                        content: String::new(),
                    }).await?;
                phases.check(turn_scope,id,generation).await?;
                let outcome=Plain::new(observed.into_inner().finish(chat.clone(),message,None,SendStatus::Completed));phases.check(turn_scope,id,generation).await?;return Ok(outcome.into_inner());
            }
            // Only the admitted current-turn final frame opens the existing
            // authoritative claim path. Claim identity, sealed owner/turn/key
            // binding and durable terminal ACK remain the success authority.
            if final_frame.is_some() && admitted && confirmed {
                break;
            }
        }
        // Finish the trailing artifact frames before committing success.
        let drain_deadline = crate::platform::time::Instant::now() + Duration::from_secs(2);
        while crate::platform::time::Instant::now() < drain_deadline {
            trace.phase = SendPhase::TrailingFrames;
            let event = if let Some(event) = deferred.pop_front() {
                Some(Ok(event))
            } else {
                crate::platform::time::timeout(Duration::from_millis(250), receive(ws))
                    .await
                    .ok()
            };
            match event {
                Some(Ok((kind, p))) => {
                    trace.observe_frame(&kind);
                    let p=Plain::new(p);phases.check(turn_scope,id,generation).await?;
                    if owns_metadata(&p, id, message, turn, &task_id) {
                        observed.capture_owned(&kind, &p)?;
                    }
                    if kind == "task_update_jobs_available"
                        && owns_metadata(&p, id, message, turn, &task_id)
                    {
                        observed.capture_jobs(&p, id)?;
                    }
                    trace.observe_discovery(&kind, &p);
                    crate::client::recovery::capture(&kind, &p, &mut recovery_outputs)?;
                    trace.phase = SendPhase::TrailingFrames;
                    capture_artifact(
                        &kind,
                        &p,
                        id,
                        &task_id,
                        &mut streamed_embeds,
                        &mut checkpoints,
                    )?;
                    // `memory_write_job_result_ack` answers our result on the
                    // socket directly and can overtake the final chunk, which
                    // travels through the stream relay. Late job frames take
                    // the in-stream path so the job record is complete.
                    if routes_memory_job_frame(options, &kind, &p, id) {
                        observed.project_create.memory_jobs.set_chat_key(key);
                observed.project_create.memory_jobs.set_mappings(&prepared.mappings);
                        phases.project_create(ws, &kind, &p, id, &mut observed.project_create).await?;
                        for notice in observed.project_create.memory_jobs.take_notices() {
                            phases.deliver_update(&turn_scope,id,updates,cancel,StreamUpdate::Status(notice)).await?;
                        }
                    }
                }
                Some(Err(e)) => return Err(e),
                None => break,
            }
        }
        trace.phase = SendPhase::FrameValidation;
        let final_frame=Plain::new(final_frame.take().ok_or_else(|| super::send::refusal_trace::protocol_at!())?);
        let job = required(&final_frame, "recovery_job_id")?;
        let assistant_id = required(&final_frame, "message_id")?;
        trace.phase = SendPhase::Claim;
        let claim=Plain::new(loop {
            phases.check(turn_scope,id,generation).await?;
            let request=uuid::Uuid::new_v4().to_string();
            send(ws,"recovery_job_claim",json!({"protocol_version":1,"job_id":job,"request_id":request})).await?;
            let (kind,value)=tokio::select! {biased;_=cancel.cancelled()=>return Err(Error::Cancelled),r=transport::wait_recovery_claim(ws,job,&request)=>r?};
            if kind=="recovery_job_claimed" {break value;}
            // The final discovery is announced to every foreground device of
            // this owner, so another one (e.g. an open browser) may lease the
            // job first. Re-claim until it is TERMINAL (read canonically below)
            // or its lease lapses; the claim fences still decide success.
            let retry=crate::platform::time::Instant::now()+CLAIM_CONFLICT_RETRY;
            if retry>=turn_deadline.at() {return Err(Error::Conflict);}
            tokio::select! {biased;_=cancel.cancelled()=>return Err(Error::Cancelled),_=crate::platform::time::sleep(CLAIM_CONFLICT_RETRY)=>{}}
        });
        phases.check(turn_scope,id,generation).await?;
        if text(&claim, "chat_id") != id
            || text(&claim, "turn_id") != turn
            || text(&claim, "assistant_message_id") != assistant_id
            || claim["chat_key_version"] != 1
        {
            return Err(super::send::refusal_trace::protocol_at!());
        }
        if text(&claim, "state") == "TERMINAL" {
            // Read the canonical ciphertext rather than treating transient text
            // as proof that another device completed the same job.
            let selected_outputs=Client::select_turn_outputs(recovery_outputs,id,turn);
            trace.phase = SendPhase::ReplayArtifacts;
            // The device that completed the job replays the same outputs now;
            // replay again until its acknowledgements settle (see the policy).
            replay_until_settled(phases, ws, &selected_outputs, (id, key), turn_scope, generation,
                turn_deadline.at(), cancel, "terminal_replay_outputs").await?;
            phases.persist_stream_artifacts(
                ws,
                id,
                assistant_id,
                key,
                &task_id,
                &bind_turn_embeds(&streamed_embeds, message, &task_id, &earlier_tasks),
                &checkpoints,
            )
            .await
            .inspect_err(|_| super::send::refusal_trace::note_step("terminal_persist_stream_artifacts"))?;
            trace.phase = SendPhase::ProjectPhase;
            adopt_turn_embeds(
                phases,
                ws,
                id,
                &bind_turn_embeds(&streamed_embeds, message, &task_id, &earlier_tasks),
                &mut observed,
            )
            .await?;
            trace.phase = SendPhase::Metadata;
            let chat = Plain::new(phases.open_chat_live(id).await?);
            if !chat.messages.iter().any(|m| m.id == assistant_id) {
                return Err(super::send::refusal_trace::protocol_at!());
            }
            let content=Plain::new(chat.messages.iter().find(|m|m.id==assistant_id).ok_or_else(|| super::send::refusal_trace::protocol_at!())?.content.clone());
            trace.phase = SendPhase::TaskFinalize;
            phases.finish_task_jobs(ws, &mut observed, id, message, key, cancel, options)
                .await?;
            phases.deliver_update(&turn_scope,id,updates,cancel,StreamUpdate::Completed {
                    chat_id: id.into(),
                    message_id: assistant_id.into(),
                    content:content.into_inner(),
                }).await?;
            phases.check(turn_scope,id,generation).await?;
            let outcome=Plain::new(observed.into_inner().finish(chat.into_inner(),message,Some(assistant_id),SendStatus::Completed));phases.check(turn_scope,id,generation).await?;return Ok(outcome.into_inner());
        }
        if text(&claim, "state") != "LEASED"
            || claim["lease_generation"].as_u64().is_none_or(|v| v < 1)
        {
            return Err(super::send::refusal_trace::protocol_at!());
        }
        trace.phase = SendPhase::Decode;
        let envelope=Plain::new(serde_json::from_str::<Value>(required(&claim,"sealed_payload")?)?);
        let owner=phases.owner_id().await?;
        let identity = crypto::RecoveryIdentity {
            owner_id: owner.into(),
            chat_id: id.into(),
            turn_id: turn.into(),
            job_id: job.into(),
            assistant_message_id: assistant_id.into(),
            key_version: 1,
        };
        let recovered=Plain::new(crate::client::completion_recovery::decode_main_completion(&envelope,key,&identity)?);
        observed.capture_owned("recovered_completion", &recovered)?;
        replace_text(&mut content,required(&recovered,"content")?.into());
        let created = final_frame["created_at"].as_u64().ok_or_else(|| super::send::refusal_trace::protocol_at!())?;
        let encrypted = crate::client::completion_recovery::encrypt_main_assistant(
            &recovered,
            &identity,
            created,
            Some(message),
            key,
        )?;
        // Consent/system writes and other Team members can advance history
        // after admission. Read the current authorized key/version before the
        // terminal transaction; never guess its expected version.
        trace.phase = SendPhase::Metadata;
        version=phases.current_messages_version(id,key,version).await?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        trace.phase = SendPhase::Persist;
        phases.check(turn_scope,id,generation).await?;
        transport::send_plaintext(ws,"recovery_job_persist",json!({"protocol_version":1,"job_id":job,"lease_token":required(&claim,"lease_token")?,"lease_generation":claim["lease_generation"],"expected_messages_v":version,"encrypted_assistant_message":encrypted})).await?;
        wait_terminal_persisted(ws, job).await?;
        phases.check(turn_scope,id,generation).await?;
        let selected_outputs=Client::select_turn_outputs(recovery_outputs,id,turn);
        trace.phase = SendPhase::ReplayArtifacts;
        // A device showing this chat replays the same sealed outputs as soon
        // as the job is persisted; settle a lost race like the terminal path.
        replay_until_settled(phases, ws, &selected_outputs, (id, key), turn_scope, generation,
            turn_deadline.at(), cancel, "leased_replay_outputs").await?;
        let artifacts = phases
            .persist_stream_artifacts(
                ws,
                id,
                assistant_id,
                key,
                &task_id,
                &bind_turn_embeds(&streamed_embeds, message, &task_id, &earlier_tasks),
                &checkpoints,
            )
            .await
            .inspect_err(|_| super::send::refusal_trace::note_step("leased_persist_stream_artifacts"))?;
        trace.phase = SendPhase::ProjectPhase;
        adopt_turn_embeds(
            phases,
            ws,
            id,
            &bind_turn_embeds(&streamed_embeds, message, &task_id, &earlier_tasks),
            &mut observed,
        )
        .await?;
        if new_chat && !text(&generated_header, "chat_title").is_empty() {
            trace.phase = SendPhase::Metadata;
            let title = text(&generated_header, "chat_title");
            let mut metadata = json!({"chat_id":id,"encrypted_chat_key":wrapped,"encrypted_title":crypto::encrypt_combined(title,key)?});
            if let Some(team) = &team {
                metadata["team_id"] = json!(team)
            }
            send(ws, "encrypted_chat_metadata", metadata).await?;
            wait(ws, "encrypted_metadata_stored", "chat_id", id).await?;
            chat.title = title.into();
        }
        trace.phase = SendPhase::TaskFinalize;
        chat.messages.push(Message {
            id: message.into(),
            role: "user".into(),
            content: crate::privacy::restore(&prepared.text, &prepared.mappings)?,
            sender: sender.clone(),
            ..Message::default()
        });
        chat.messages.push(Message {
            id: assistant_id.into(),
            role: "assistant".into(),
            content: crate::privacy::restore(&content, &prepared.mappings)?,
            thinking: crate::privacy::restore(
                recovered["thinking_content"].as_str().unwrap_or(""),
                &prepared.mappings,
            )?,
            sender: "Assistant".into(),
            embeds: artifacts,
        });
        chat.category = text(&recovered, "category").into();
        phases.finish_task_jobs(ws, &mut observed, id, message, key, cancel, options)
            .await?;
        let content = crate::privacy::restore(&content, &prepared.mappings)?;
        phases.deliver_update(&turn_scope,id,updates,cancel,StreamUpdate::Completed {
                chat_id: id.into(),
                message_id: assistant_id.into(),
                content,
            }).await?;
        phases.check(turn_scope,id,generation).await?;
        let outcome=Plain::new(observed.into_inner().finish(chat.clone(),message,Some(assistant_id),SendStatus::Completed));
        phases.check(turn_scope,id,generation).await?;
        Ok(outcome.into_inner())

}
/// Error for an `ai_typing_ended` frame that carries `terminal_failure_code`
/// and belongs to this turn: same chat and either the user message id or one of
/// the turn's task ids (a continuation task has its own id, and the frame
/// carries no `user_message_id`). A refused focus-mode continuation is
/// `Unavailable`; any other terminal code is a protocol failure.
fn terminal_refusal(
    kind: &str,
    p: &Value,
    chat: &str,
    message: &str,
    task_id: &str,
    earlier_tasks: &[String],
) -> Option<Error> {
    let code = text(p, "terminal_failure_code");
    if kind != "ai_typing_ended" || code.is_empty() || text(p, "chat_id") != chat {
        return None;
    }
    let frame_task = text(p, "task_id");
    let ours = text(p, "message_id") == message
        || (!frame_task.is_empty()
            && (frame_task == task_id || earlier_tasks.iter().any(|t| t == frame_task)));
    if !ours {
        return None;
    }
    Some(if code == "focus_continuation_unavailable" {
        Error::Unavailable {
            code: "focus_continuation_unavailable",
            reason: "focus continuation refused",
        }
    } else {
        Error::Protocol
    })
}
#[cfg(test)]
#[path = "send_turn_runtime_tests.rs"]
mod tests;
