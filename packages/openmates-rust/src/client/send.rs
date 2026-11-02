//! Encrypted turn admission and fenced recovery-backed reply persistence.
use super::send_observations::SendObservations;
use super::sync::decrypt_optional;
use super::transport::{Socket, receive, send, wait};
use super::*;
use super::sync_capability::AsyncCryptoScope;
use super::plaintext::{Plain,Wipe,replace_text};
use crate::crypto::master::MasterCapability;
#[path="send_prepared_turn.rs"]
pub(in crate::client) mod prepared_turn;
#[path="send_prepared_transport.rs"]
pub(in crate::client) mod prepared_transport;
#[path="send_turn_runtime.rs"]
pub(in crate::client) mod turn_runtime;
impl Wipe for crate::privacy::PreparedPrivacy {
    fn wipe(&mut self){let Self{text,mappings}=self;text.wipe();mappings.wipe();}
}

impl<A:Wipe,B:Wipe> Wipe for (A,B){fn wipe(&mut self){self.0.wipe();self.1.wipe();}}
impl<T:Wipe> Wipe for std::collections::VecDeque<T>{fn wipe(&mut self){for value in self{value.wipe();}}}
impl Wipe for StreamUpdate{fn wipe(&mut self){zeroize::Zeroize::zeroize(self);}}
impl Wipe for SendMemoryRequest{
    fn wipe(&mut self){let Self{request_id,requested_keys,approved_keys,entry_count}=self;request_id.wipe();requested_keys.wipe();approved_keys.wipe();*entry_count=0;}
}
impl Wipe for SendOutcome{
    fn wipe(&mut self){
        let Self{chat,status:_,chat_id,message_id,user_message_id,queue_mode:_,queue_revision,assistant,category,model_name,mate_name,follow_up_suggestions,suggested_followup_message,task_proposals,task_update_proposals,task_events,pending_task_update_jobs,sub_chat_events,app_settings_memory_requests,token_usage,prompt_budget}=self;
        chat.wipe();chat_id.wipe();message_id.wipe();user_message_id.wipe();*queue_revision=None;assistant.wipe();category.wipe();model_name.wipe();mate_name.wipe();follow_up_suggestions.wipe();suggested_followup_message.wipe();task_proposals.wipe();task_update_proposals.wipe();task_events.wipe();pending_task_update_jobs.wipe();sub_chat_events.wipe();app_settings_memory_requests.wipe();token_usage.wipe();prompt_budget.wipe();
    }
}
impl Wipe for SendObservations{
    fn wipe(&mut self){let Self{category,model,mate,suggestions,suggested,proposals,updates,events,jobs,subchats,memories,usage,budget}=self;category.wipe();model.wipe();mate.wipe();suggestions.wipe();suggested.wipe();proposals.wipe();updates.wipe();events.wipe();jobs.wipe();subchats.wipe();memories.wipe();usage.wipe();budget.wipe();}
}
// Private, opt-in test attribution. No turn/account/payload value is printable.
#[derive(Clone, Copy, PartialEq, Eq)]
enum SendPhase {
    Preparation,
    StreamReceive,
    FrameValidation,
    Discovery,
    DiscoveryFailed,
    TrailingFrames,
    Claim,
    Decode,
    Metadata,
    Persist,
    ReplayArtifacts,
    TaskFinalize,
}
impl SendPhase {
    fn label(self) -> &'static str {
        match self {
            Self::Preparation => "preparation",
            Self::StreamReceive => "stream_receive",
            Self::FrameValidation => "frame_validation",
            Self::Discovery => "discovery",
            Self::DiscoveryFailed => "discovery_failed",
            Self::TrailingFrames => "trailing_frames",
            Self::Claim => "claim",
            Self::Decode => "decode",
            Self::Metadata => "metadata",
            Self::Persist => "persist",
            Self::ReplayArtifacts => "replay_artifacts",
            Self::TaskFinalize => "task_finalize",
        }
    }
}
#[derive(Clone, Copy, PartialEq, Eq)]
enum DiscoveryStatus {
    None,
    Completed,
    Disabled,
    Failed,
    Unclassified,
}
impl DiscoveryStatus {
    fn label(self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Completed => "completed",
            Self::Disabled => "disabled",
            Self::Failed => "failed",
            Self::Unclassified => "unclassified",
        }
    }
}
pub(in crate::client) struct SendTrace {
    phase: SendPhase,
    discovery: DiscoveryStatus,
    final_seen: bool,
}
impl SendTrace {
    pub(in crate::client) fn new() -> Self {
        Self {
            phase: SendPhase::Preparation,
            discovery: DiscoveryStatus::None,
            final_seen: false,
        }
    }
    pub(in crate::client) fn report_protocol_error(&self) {
        let enabled = std::env::var_os("OPENMATES_TEST_SEND_PHASE_DIAGNOSTIC").as_deref()
            == Some(std::ffi::OsStr::new("1"));
        write_protocol_phase(Error::Protocol,self,enabled,&mut std::io::stderr().lock());
    }
    fn observe_discovery(&mut self, kind: &str, payload: &Value) {
        if kind == "recovery_outputs_discovery_complete" {
            self.discovery = match payload["status"].as_str() {
                Some("completed") => DiscoveryStatus::Completed,
                Some("disabled") => DiscoveryStatus::Disabled,
                Some("failed") => DiscoveryStatus::Failed,
                _ => DiscoveryStatus::Unclassified,
            };
        }
        self.phase = discovery_phase(kind, payload);
    }
}
fn discovery_phase(kind: &str, payload: &Value) -> SendPhase {
    if kind == "recovery_outputs_discovery_complete" && payload["status"] == "failed" {
        SendPhase::DiscoveryFailed
    } else {
        SendPhase::Discovery
    }
}
fn write_protocol_phase(
    error: Error,
    trace: &SendTrace,
    enabled: bool,
    writer: &mut impl std::io::Write,
) {
    if error == Error::Protocol && enabled {
        // Diagnostic output cannot replace the original send error.
        let _ = writeln!(
            writer,
            "OpenMates-Test-Send-Phase: {} discovery={} final_seen={}",
            trace.phase.label(),
            trace.discovery.label(),
            trace.final_seen
        );
    }
}
#[cfg(test)]
mod send_phase_tests {
    use super::*;

    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
    #[test]
    fn diagnostic_is_opt_in_protocol_only_and_writer_failure_cannot_replace_error() {
        let trace = SendTrace::new();
        for error in [
            Error::Invalid("private-static-input"),
            Error::Crypto,
            Error::Authentication,
            Error::TwoFactorRequired,
            Error::SignupRequired,
            Error::Unavailable {
                code: "private-code",
                reason: "private-reason",
            },
            Error::Locked,
            Error::Offline,
            Error::Forbidden,
            Error::Expired,
            Error::Cancelled,
            Error::Io,
            Error::Conflict,
            Error::Protocol,
        ] {
            for enabled in [false, true] {
                let mut bytes = vec![];
                write_protocol_phase(error, &trace, enabled, &mut bytes);
                assert_eq!(bytes.is_empty(), error != Error::Protocol || !enabled);
                if !bytes.is_empty() {
                    assert_eq!(
                        bytes,
                        b"OpenMates-Test-Send-Phase: preparation discovery=none final_seen=false\n"
                    );
                }
            }
        }
        struct Broken;
        impl std::io::Write for Broken {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                Err(std::io::Error::new(
                    std::io::ErrorKind::Other,
                    "inert writer failure",
                ))
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        write_protocol_phase(Error::Protocol, &trace, true, &mut Broken);
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation

    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn discovery_context_and_failed_phase_require_exact_canonical_type_and_status() {
        let mut trace = SendTrace::new();
        trace.observe_discovery("other", &json!({"status":"failed"}));
        assert!(trace.discovery == DiscoveryStatus::None);
        assert!(trace.phase == SendPhase::Discovery);
        for (status, expected) in [
            (json!("completed"), DiscoveryStatus::Completed),
            (json!("disabled"), DiscoveryStatus::Disabled),
            (json!("failed"), DiscoveryStatus::Failed),
            (json!("FAILED"), DiscoveryStatus::Unclassified),
            (json!(" failed"), DiscoveryStatus::Unclassified),
            (json!("private-server-text"), DiscoveryStatus::Unclassified),
            (Value::Null, DiscoveryStatus::Unclassified),
            (json!(false), DiscoveryStatus::Unclassified),
        ] {
            let payload = json!({"status":status});
            trace.observe_discovery("recovery_outputs_discovery_complete", &payload);
            assert!(trace.discovery == expected);
            assert_eq!(
                trace.phase == SendPhase::DiscoveryFailed,
                expected == DiscoveryStatus::Failed
            );
            let result = super::super::recovery::capture(
                "recovery_outputs_discovery_complete",
                &payload,
                &mut BTreeMap::new(),
            );
            assert_eq!(
                matches!(result, Err(Error::Protocol)),
                !matches!(
                    expected,
                    DiscoveryStatus::Completed | DiscoveryStatus::Disabled
                )
            );
        }
        trace.observe_discovery("recovery_outputs_discovery_complete", &json!({}));
        assert!(trace.discovery == DiscoveryStatus::Unclassified);
        trace.observe_discovery("recovery_outputs_available", &json!({"status":"failed"}));
        assert!(trace.discovery == DiscoveryStatus::Unclassified);
        assert!(trace.phase == SendPhase::Discovery);
        assert!(!trace.final_seen);
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation

    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn diagnostic_serializes_only_finite_phase_status_and_boolean_labels() {
        for (phase, label) in [
            (SendPhase::Preparation, "preparation"),
            (SendPhase::StreamReceive, "stream_receive"),
            (SendPhase::FrameValidation, "frame_validation"),
            (SendPhase::Discovery, "discovery"),
            (SendPhase::DiscoveryFailed, "discovery_failed"),
            (SendPhase::TrailingFrames, "trailing_frames"),
            (SendPhase::Claim, "claim"),
            (SendPhase::Decode, "decode"),
            (SendPhase::Metadata, "metadata"),
            (SendPhase::Persist, "persist"),
            (SendPhase::ReplayArtifacts, "replay_artifacts"),
            (SendPhase::TaskFinalize, "task_finalize"),
        ] {
            for (discovery, status) in [
                (DiscoveryStatus::None, "none"),
                (DiscoveryStatus::Completed, "completed"),
                (DiscoveryStatus::Disabled, "disabled"),
                (DiscoveryStatus::Failed, "failed"),
                (DiscoveryStatus::Unclassified, "unclassified"),
            ] {
                for final_seen in [false, true] {
                    let trace = SendTrace {
                        phase,
                        discovery,
                        final_seen,
                    };
                    let mut bytes = vec![];
                    write_protocol_phase(Error::Protocol, &trace, true, &mut bytes);
                    assert_eq!(bytes, format!("OpenMates-Test-Send-Phase: {label} discovery={status} final_seen={final_seen}\n").as_bytes());
                }
            }
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation

    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[tokio::test]
    async fn independent_send_traces_keep_their_values_across_interleaved_awaits() {
        async fn observed(phase: SendPhase, final_seen: bool) -> Vec<u8> {
            let mut trace = SendTrace::new();
            trace.phase = phase;
            trace.final_seen = final_seen;
            tokio::task::yield_now().await;
            let mut bytes = vec![];
            write_protocol_phase(Error::Protocol, &trace, true, &mut bytes);
            bytes
        }
        let (first, second) = tokio::join!(
            observed(SendPhase::Claim, true),
            observed(SendPhase::Decode, false)
        );
        assert_eq!(
            first,
            b"OpenMates-Test-Send-Phase: claim discovery=none final_seen=true\n"
        );
        assert_eq!(
            second,
            b"OpenMates-Test-Send-Phase: decode discovery=none final_seen=false\n"
        );
    }
}
impl Client {
    pub async fn send_message(
        &mut self,
        chat_id: Option<&str>,
        text_input: &str,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> Result<Chat> {
        self.send(chat_id, text_input, SendOptions::default(), updates, cancel)
            .await
            .map(|result| result.chat)
    }
    /// Submit one encrypted turn and return metadata observed for that turn.
    /// Unsupported execution modes are rejected before authenticated transport.
    pub async fn send(
        &mut self,
        chat_id: Option<&str>,
        text_input: &str,
        options: SendOptions,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> Result<SendOutcome> {
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        options.validate()?;
        if options.incognito {
            return self
                .send_incognito(chat_id, text_input, options, updates, cancel)
                .await;
        }
        self.validate_saved_send_request(chat_id,text_input,&options,&cancel)?;
        let prepared=self.prepare_saved_turn_transport(chat_id,text_input,&options,&cancel).await?;
        let prepared_transport::PreparedTurnTransport{generation,id,turn,message,mut chat,new_chat,key,wrapped,baseline,existing,team_preparation,mut ws,release_scope}=prepared;
        let mut trace = SendTrace::new();
        let result = self
            .send_on_socket(
                &mut ws,
                &id,
                &turn,
                &message,
                text_input,
                &key,
                &wrapped,
                baseline,
                new_chat,
                &existing,
                &mut chat,
                &updates,
                &cancel,
                generation,
                team_preparation.into_inner(),
                &options,
                &mut trace,
            )
            .await.map(Plain::new);
        let _ = ws.close(None).await;
        let result=match result{Ok(outcome)=>self.release_send_outcome(&release_scope,&id,&cancel,outcome),Err(error)=>Err(error)};
        // Read the opt-in flag only for the original Protocol failure, after
        // the existing socket close; normal output and errors are unchanged.
        if matches!(&result, Err(Error::Protocol)) {
            trace.report_protocol_error();
        }
        result
    }
    pub(in crate::client) fn validate_saved_send_request(&self,chat_id:Option<&str>,text_input:&str,
        options:&SendOptions,cancel:&CancellationToken)->Result<()>{
        if chat_id.is_some_and(|id| self.is_ephemeral_chat(id)) {
            return Err(Error::Invalid(
                "A volatile chat cannot become a saved chat.",
            ));
        }
        if options.project_id.is_some() {
            return Err(Error::Invalid(
                "Explicit Project chat binding is unavailable in native send; no message was submitted.",
            ));
        }
        if let Some(slug) = &options.slug {
            crypto::normalize_object_slug(slug)?;
            if chat_id.is_some() {
                return Err(Error::Invalid(
                    "A chat slug may only be supplied when creating a new chat.",
                ));
            }
        }
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if text_input.trim().is_empty() || text_input.len() > 1_000_000 {
            return Err(Error::Invalid("Enter a message of at most 1 MB."));
        }
        Ok(())
    }
    fn turn_chat_key(&self, details: Option<&Value>, wrapping: &[u8; 32]) -> Result<Key> {
        match details {
            Some(row) if !super::sync::draft_only(row) => self.chat_key(row, wrapping),
            _ => Ok(crypto::random_key()),
        }
    }
    fn turn_chat_material(&self,details:Option<&Value>,wrapping:&[u8;32])->Result<(Key,String)>{
        let key=self.turn_chat_key(details,wrapping)?;
        let wrapped=match self.selected_turn_wrapper(details)?{Some(wrapped)=>wrapped,None=>crypto::server_fields::encrypt_bytes(key.as_ref(),wrapping,&[])?};
        Ok((key,wrapped))
    }
    fn selected_turn_wrapper(&self,details:Option<&Value>)->Result<Option<String>>{
        let wrapped = match details.filter(|row| !super::sync::draft_only(row)) {
            Some(row) if text(row, "chat_visibility") == "direct" => {
                // The validated OMDM1 recipient envelope is already canonical.
                required(row, "encrypted_chat_key")?.to_owned()
            }
            Some(row) => {
                let selected = self.chat_key_ciphertext(row, true)?;
                if selected.ambiguous {
                    return Err(Error::Conflict);
                }
                if let Some(canonical) = row
                    .get("encrypted_chat_key")
                    .filter(|value| !value.is_null())
                {
                    let canonical = canonical
                        .as_str()
                        .filter(|value| !value.is_empty())
                        .ok_or(Error::Protocol)?;
                    if canonical != selected.ciphertext {
                        return Err(Error::Conflict);
                    }
                }
                selected.ciphertext.to_owned()
            }
            None => return Ok(None),
        };
        Ok(Some(wrapped))
    }
    async fn turn_chat_material_with_capability(&self,details:Option<&Value>,wrapping:&MasterCapability)->Result<(Key,String)>{
        match wrapping.native_key(){
            Ok(key)=>return self.turn_chat_material(details,key),
            Err(Error::Unavailable{code:"master_key_extraction_unavailable",..})=>{},
            Err(error)=>return Err(error),
        }
        let scope=AsyncCryptoScope::begin(self)?;
        let key=match details{Some(row)if !super::sync::draft_only(row)=>self.chat_key_with_capability(row,wrapping).await?,_=>crypto::random_key()};
        scope.check(self)?;
        let wrapped=match self.selected_turn_wrapper(details)?{Some(wrapped)=>wrapped,None=>wrapping.encrypt_server_bytes(key.as_ref()).await?};
        scope.check(self)?;
        Ok((key,wrapped))
    }
    fn select_turn_outputs(mut outputs:Plain<BTreeMap<String,Value>>,id:&str,turn:&str)->Plain<BTreeMap<String,Value>> {
        let mut selected=Plain::new(BTreeMap::new());
        while let Some((mut output_id,mut output))=outputs.pop_first(){
            if text(&output,"root_chat_id")==id&&text(&output,"turn_id")==turn{selected.insert(output_id,output);}else{output_id.wipe();output.wipe();}
        }
        selected
    }
    fn release_send_outcome(&self,scope:&AsyncCryptoScope,chat:&str,cancel:&CancellationToken,outcome:Plain<SendOutcome>)->Result<SendOutcome>{scope.check_chat(self,chat)?;if cancel.is_cancelled(){return Err(Error::Cancelled);}Ok(outcome.into_inner())}
    fn require_turn_slug_index(wrapping:&MasterCapability,explicit:bool)->Result<()> {
        match wrapping.native_key(){
            Ok(_)=>Ok(()),
            Err(Error::Unavailable{code:"master_key_extraction_unavailable",..})if !explicit=>Ok(()),
            Err(Error::Unavailable{code:"master_key_extraction_unavailable",..})=>Err(Error::Unavailable{code:"opaque_slug_index_unavailable",reason:"EXPLICIT_SLUG_REQUIRES_EXISTING_HKDF_INDEX_CAPABILITY"}),
            Err(error)=>Err(error),
        }
    }
    pub(in crate::client) fn deliver_turn_update<'a>(&'a self,scope:&'a AsyncCryptoScope,chat:&'a str,updates:&'a mpsc::Sender<StreamUpdate>,cancel:&'a CancellationToken,update:StreamUpdate)->impl std::future::Future<Output=Result<()>>+'a {
        let update=Plain::new(update);
        let marker=matches!(&*update,StreamUpdate::Started{..}|StreamUpdate::Submitted{..}|StreamUpdate::Admitted{..}|StreamUpdate::Status(_));
        async move {
            if !marker&&cancel.is_cancelled(){return Err(Error::Cancelled);}
            scope.check_chat(self,chat)?;
            match updates.try_reserve(){
                Ok(permit)=>{if !marker&&cancel.is_cancelled(){return Err(Error::Cancelled);}scope.check_chat(self,chat)?;permit.send(update.into_inner());return Ok(());}
                Err(tokio::sync::mpsc::error::TrySendError::Closed(_))=>{if cancel.is_cancelled(){return Err(Error::Cancelled);}return scope.check_chat(self,chat);},
                Err(tokio::sync::mpsc::error::TrySendError::Full(_))=>{},
            }
            let master=self.browser_credentials.as_ref().map(|credentials|credentials.master.clone());
            let expiry=self.require_credentials()?.paired_session_expires_at;
            let master_revoked=async{if let Some(master)=&master{master.cancelled().await}else{std::future::pending::<()>().await}};
            let expired=async{if let Some(deadline)=expiry{loop{let remaining=deadline.saturating_sub(now_ms());if remaining==0{break;}crate::platform::time::sleep(Duration::from_millis(remaining)).await;}}else{std::future::pending::<()>().await}};
            // Historical metadata marker contract permits a ready Submitted
            // after caller cancel+drain; it never admits a saved/inference effect.
            // Actual authority revocation always precedes either ready permit.
            let permit=if marker{tokio::select!{biased;
                _=self.operation_cancel.cancelled()=>return Err(Error::Cancelled),
                _=self.task_watch_authority.cancel.cancelled()=>return Err(Error::Cancelled),
                _=master_revoked=>{scope.check_chat(self,chat)?;return Err(Error::Cancelled);},
                _=expired=>{self.require_credentials()?;return Err(Error::Expired);},
                permit=updates.reserve()=>permit,
                _=cancel.cancelled()=>return Err(Error::Cancelled),
            }}else{tokio::select!{biased;
                _=cancel.cancelled()=>return Err(Error::Cancelled),
                _=self.operation_cancel.cancelled()=>return Err(Error::Cancelled),
                _=self.task_watch_authority.cancel.cancelled()=>return Err(Error::Cancelled),
                _=master_revoked=>{scope.check_chat(self,chat)?;return Err(Error::Cancelled);},
                _=expired=>{self.require_credentials()?;return Err(Error::Expired);},
                permit=updates.reserve()=>permit,
            }};
            if !marker&&cancel.is_cancelled(){return Err(Error::Cancelled);}
            scope.check_chat(self,chat)?;
            if let Ok(permit)=permit{permit.send(update.into_inner());}
            Ok(())
        }
    }
    #[allow(clippy::too_many_arguments)]
    async fn turn_chat_metadata(&mut self,id:&str,input:&str,key:&[u8;32],wrapped:&str,created:u64,team:Option<&str>,wait_ai:bool,options:&SendOptions)->Result<Value>{
        let wrapping=self.wrapping_capability().await?;
        Self::require_turn_slug_index(&wrapping,options.slug.is_some())?;
        let scope=AsyncCryptoScope::begin(self)?;scope.check_chat(self,id)?;
        let mut metadata=json!({"encrypted_title":crypto::encrypt_combined(if team.is_some()&&!wait_ai{input}else{""},key)?,"encrypted_chat_key":wrapped,"created_at":created,"updated_at":created});
        match wrapping.native_key(){
            Ok(raw)=>{
                let slug=match options.slug.as_deref(){Some(slug)=>crypto::normalize_object_slug(slug)?,None=>crypto::normalize_object_slug(input).unwrap_or_else(|_|format!("chat-{}",&id[..8]))};
                metadata["encrypted_slug"]=json!(crypto::encrypt_combined(&slug,key)?);
                metadata["slug_lookup_hash"]=json!(crypto::object_slug_lookup_hash(&slug,raw)?);
            }
            Err(Error::Unavailable{code:"master_key_extraction_unavailable",..})=>{},
            Err(error)=>return Err(error),
        }
        scope.check_chat(self,id)?;Ok(metadata)
    }
    #[allow(clippy::too_many_arguments)]
    async fn send_on_socket(
        &mut self,
        ws: &mut Socket,
        id: &str,
        turn: &str,
        message: &str,
        input: &str,
        key: &[u8; 32],
        wrapped: &str,
        baseline: u64,
        new_chat: bool,
        existing: &[Value],
        chat: &mut Chat,
        updates: &mpsc::Sender<StreamUpdate>,
        cancel: &CancellationToken,
        generation: u64,
        team_preparation: Option<Value>,
        options: &SendOptions,
        trace: &mut SendTrace,
    ) -> Result<SendOutcome> {
        let turn_scope=AsyncCryptoScope::begin(self)?;
        turn_scope.check_chat(self,id)?;
        let original_parent=self.operation_parent.clone();
        let original_child=self.current_operation_child();
        let original_epoch=self.fresh_auth.operation_epoch();
        let original_gate=self.options.private_operation_gate.clone();
        // The exact original socket/task survives every local cancellation
        // exit, including a post-Content scope check before the next receive.
        // One cleanup site prevents duplicate withdrawal on a ready cancel.
        let mut task_id=String::new();
        let result=async {
        let prepared_turn=self.prepare_turn_on_socket(ws,id,turn,message,input,key,wrapped,baseline,new_chat,
            existing,chat,updates,cancel,generation,team_preparation,options,&turn_scope).await?;
        let mut phases=turn_runtime::BorrowedTurnPhases{client:self};
        turn_runtime::receive_turn(&mut phases,ws,prepared_turn,&turn_scope,id,turn,message,input,key,wrapped,baseline,
            new_chat,chat,updates,cancel,generation,options,trace,&mut task_id).await
        }.await;
        // This is an authenticated negative request on the SAME live socket,
        // not an ACK, remote-cancel claim, retry, or terminal-rearm grant. Root,
        // account, policy, resource, denial and TTL fences remain mandatory;
        // only this actual local child's/request's cancellation is ignored.
        if result.is_err() && !task_id.is_empty()
            && (cancel.is_cancelled()||original_child.is_cancelled())
            && !original_parent.is_cancelled() && original_parent==self.operation_parent
            && original_epoch==self.fresh_auth.operation_epoch()
            && same_private_gate(&original_gate,&self.options.private_operation_gate)
            && self.verify_private_operation().is_ok()
            && turn_scope.check_terminated_child_context(self).is_ok()
            && self.task_watch_authority.cached_chat_allowed(id)
            // The caller gate above may synchronously revoke while returning
            // Ok; original-parent observation must also follow that callback.
            && !original_parent.is_cancelled() && original_parent==self.operation_parent {
            let _=send(ws,"cancel_ai_task",json!({"task_id":task_id,"chat_id":id})).await;
        }
        result
    }
    #[allow(clippy::too_many_arguments)]
    async fn finish_task_jobs(
        &mut self,
        ws: &mut Socket,
        observed: &mut SendObservations,
        id: &str,
        message: &str,
        key: &[u8; 32],
        cancel: &CancellationToken,
        options: &SendOptions,
    ) -> Result<()> {
        if options.task_update_jobs {
            let done = self
                .persist_task_jobs(
                    ws,
                    &observed.jobs,
                    &observed.events,
                    Some((id, key, message)),
                    cancel,
                )
                .await?;
            observed.jobs.retain(|id, _| !done.contains(id));
        }
        Ok(())
    }
}
async fn wait_terminal_persisted(ws: &mut Socket, job: &str) -> Result<()> {
    let persisted = wait(ws, "recovery_job_persisted", "job_id", job).await?;
    // All canonical success branches, including idempotent retries, carry this
    // state. The idempotent terminal branch may omit committed_messages_v.
    if persisted["state"] != "TERMINAL" {
        return Err(Error::Protocol);
    }
    Ok(())
}
fn owns_metadata(p: &Value, chat: &str, user: &str, turn: &str, task: &str) -> bool {
    text(p, "chat_id") == chat
        && ["turn_id", "recovery_turn_id"].iter().all(|key| {
            p.get(*key)
                .and_then(Value::as_str)
                .is_none_or(|id| id == turn)
        })
        && p.get("user_message_id")
            .and_then(Value::as_str)
            .is_none_or(|id| id == user)
        && (belongs_to_turn(p, chat, user, turn)
            || (text(p, "message_id") == user
                && p.get("turn_id")
                    .and_then(Value::as_str)
                    .is_none_or(|id| id == turn))
            || (!task.is_empty()
                && text(p, "task_id") == task
                && p.get("user_message_id")
                    .and_then(Value::as_str)
                    .is_none_or(|id| id == user)
                && p.get("turn_id")
                    .and_then(Value::as_str)
                    .is_none_or(|id| id == turn)))
}
fn belongs_to_turn(p: &Value, chat: &str, user: &str, turn: &str) -> bool {
    text(p, "chat_id") == chat
        && text(p, "user_message_id") == user
        && p.get("recovery_turn_id")
            .and_then(Value::as_str)
            .is_none_or(|v| v == turn)
}
fn has_continuation(p: &Value) -> bool {
    [
        "waiting_for_skill_completion",
        "awaiting_async_skill_continuation",
        "awaiting_focus_mode_continuation",
        "awaiting_sub_chats_completion",
        "is_project_operation_pending",
    ]
    .into_iter()
    .any(|k| p[k] == true)
}
#[cfg(test)]
#[path = "../../tests/continuation_wrapper/mod.rs"]
mod continuation_wrapper_tests;
#[cfg(test)]
#[path = "../../tests/send_admission_backpressure/mod.rs"]
mod admission_backpressure_tests;
#[cfg(all(test,not(target_arch="wasm32")))]
#[path="../../tests/send_original_task_withdrawal/mod.rs"]
mod original_task_withdrawal_tests;
#[cfg(test)]
#[path = "../../tests/recovery_final_order/mod.rs"]
mod final_order_tests;
#[cfg(test)]
#[path = "../../tests/recovery_terminal_receipts/mod.rs"]
mod terminal_receipt_tests;
#[cfg(test)]
mod tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn first_draft_turn_generates_an_independent_chat_key() {
        let master = [7; 32];
        let session = crate::session::Session {
            api_url: "https://api.example.org".into(),
            session_id: "s".into(),
            cookies: BTreeMap::new(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new(master),
            hashed_email: "e".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        let client = Client::new("https://api.example.org", Some(session)).unwrap();
        let row = json!({"id":"draft","encrypted_draft_md":crypto::encrypt_combined("draft",&master).unwrap(),"encrypted_draft_preview":crypto::encrypt_combined("draft preview",&master).unwrap()});
        assert!(
            client.chat_key(&row, &master).is_err(),
            "Drafts must never export the account master as their object key"
        );
        assert_eq!(
            client.chat_item(&row, &master).unwrap().title,
            "draft preview"
        );
        let (actual_key,actual_wrapper)=client.turn_chat_material(Some(&row),&master).unwrap();
        assert_ne!(*actual_key,master);
        assert_eq!(&*super::super::workspaces::server_field_tests::strict_legacy(&actual_wrapper,&master),actual_key.as_ref());
        let key = client.turn_chat_key(Some(&row), &master).unwrap();
        assert_ne!(*key, master);
        let wrapped = crypto::encrypt_bytes(key.as_ref(), &master).unwrap();
        assert_eq!(
            &*crypto::decrypt_bytes(&wrapped, &master).unwrap(),
            key.as_ref()
        );
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn stale_streams_are_rejected() {
        let p = json!({"chat_id":"c","user_message_id":"u","recovery_turn_id":"old"});
        assert!(!belongs_to_turn(&p, "c", "u", "new"));
        assert!(!belongs_to_turn(&p, "c", "different", "old"));
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn observations_bind_broadcast_task_events_and_metadata_to_the_current_turn() {
        let p = json!({"chat_id":"chat","message_id":"human","task_id":"durable-task","event_id":"event"});
        assert!(owns_metadata(&p, "chat", "human", "turn", "ai-task"));
        assert!(!owns_metadata(&p, "chat", "other-human", "turn", "ai-task"));
        assert!(!owns_metadata(&p, "other-chat", "human", "turn", "ai-task"));
        for field in ["turn_id", "recovery_turn_id", "user_message_id"] {
            let mut wrong = p.clone();
            wrong[field] = json!("stale");
            assert!(!owns_metadata(&wrong, "chat", "human", "turn", "ai-task"));
        }
        assert!(!owns_metadata(
            &json!({"chat_id":"chat","category":"foreign"}),
            "chat",
            "human",
            "turn",
            "ai-task"
        ));
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[tokio::test]
    async fn unsupported_send_options_fail_before_authentication_or_transport() {
        for options in [
            SendOptions {
                task_update_jobs: false,
                incognito: true,
                slug: Some("saved-slug".into()),
                ..Default::default()
            },
            SendOptions {
                task_update_jobs: false,
                project_id: Some("11111111-1111-4111-8111-111111111111".into()),
                ..Default::default()
            },
        ] {
            let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
            let (updates, _) = mpsc::channel(1);
            assert!(matches!(
                client
                    .send(None, "private", options, updates, CancellationToken::new())
                    .await,
                Err(Error::Invalid(_))
            ));
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[tokio::test]
    async fn default_task_job_send_is_supported_and_requires_explicit_credentials() {
        let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
        let (updates, _) = mpsc::channel(1);
        assert!(matches!(
            client
                .send(
                    None,
                    "private",
                    SendOptions::default(),
                    updates,
                    CancellationToken::new()
                )
                .await,
            Err(Error::Authentication)
        ));
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn interim_skill_final_is_not_terminal() {
        assert!(has_continuation(
            &json!({"is_final_chunk":true,"awaiting_async_skill_continuation":true})
        ));
    }
}

fn should_wait_for_ai(message: &str, team: Option<&str>) -> bool {
    if team.is_none() {
        return true;
    }
    let re = regex::Regex::new(r"(?i)(?:^|[^\w@])@(openmates|mate:([a-z0-9_-]+))")
        .expect("static expression");
    re.captures_iter(message).any(|c| {
        let full = c.get(0).unwrap();
        if message[full.end()..]
            .chars()
            .next()
            .is_some_and(|c| c.is_alphanumeric() || c == '_' || c == '-')
        {
            return false;
        }
        if c[1].eq_ignore_ascii_case("openmates") {
            return true;
        }
        c.get(2).is_some_and(|id| {
            [
                "software_development",
                "business_development",
                "life_coach_psychology",
                "medical_health",
                "legal_law",
                "finance",
                "design",
                "marketing_sales",
                "science",
                "history",
                "cooking_food",
                "electrical_engineering",
                "maker_prototyping",
                "movies_tv",
                "activism",
                "general_knowledge",
            ]
            .contains(&id.as_str().to_ascii_lowercase().as_str())
        })
    })
}

fn capture_artifact(
    kind: &str,
    p: &Value,
    chat: &str,
    task: &str,
    embeds: &mut BTreeMap<String, Value>,
    checkpoints: &mut Vec<Value>,
) -> Result<()> {
    let row = p.get("payload").unwrap_or(p);
    if kind == "send_embed_data"
        && row["already_encrypted"] != true
        && text(row, "chat_id") == chat
        && (text(row, "task_id").is_empty() || task.is_empty() || text(row, "task_id") == task)
        && row.get("content").and_then(Value::as_str).is_some()
        && row.get("type").and_then(Value::as_str).is_some()
    {
        let id = required(row, "embed_id")?;
        if embeds.len() >= 100 && !embeds.contains_key(id) {
            return Err(Error::Protocol);
        }
        embeds.insert(id.into(), row.clone());
    }
    if kind == "chat_compression_completed"
        && text(row, "chat_id") == chat
        && (text(row, "task_id").is_empty() || text(row, "task_id") == task)
    {
        if checkpoints.len() >= 100 {
            return Err(Error::Protocol);
        }
        let mut checkpoint = row.clone();
        checkpoint["checkpoint_id"] = row["summary_message_id"].clone();
        checkpoints.push(checkpoint)
    }
    Ok(())
}

fn admit_memory_request(
    event: &Value,
    chat: &str,
    user_message: &str,
    seen: &mut std::collections::HashSet<String>,
) -> bool {
    let request = text(event, "request_id");
    text(event, "chat_id") == chat
        && text(event, "message_id") == user_message
        && !request.is_empty()
        && request.len() <= 128
        && seen.insert(request.into())
}
#[cfg(test)]
mod consent_fence_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn consent_is_bound_to_original_human_turn_and_deduplicated() {
        let mut seen = std::collections::HashSet::new();
        for event in [
            json!({"chat_id":"chat","message_id":"old","request_id":"old-request"}),
            json!({"chat_id":"other","message_id":"human","request_id":"other-request"}),
            json!({"chat_id":"chat","request_id":"unfenced"}),
        ] {
            assert!(!admit_memory_request(&event, "chat", "human", &mut seen));
        }
        let valid = json!({"chat_id":"chat","message_id":"human","request_id":"current"});
        assert!(admit_memory_request(&valid, "chat", "human", &mut seen));
        assert!(!admit_memory_request(&valid, "chat", "human", &mut seen));
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="send_opaque_tests.rs"]
mod opaque_tests;
