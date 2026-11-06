//! Confirmed direct Apps skill execution. This is the typed provider request,
//! not natural-language Apps planning; no private memories are included implicitly.
use super::*;
use super::plaintext::{Plain, Wipe};
use super::sync_capability::AsyncCryptoScope;
#[path = "apps_input_size.rs"]
mod input_size;
#[path = "apps_metadata.rs"]
mod metadata;

// Existing accepted task-array bound, shared by validation and concurrency.
const MAX_APP_TASKS:usize=64;
/// App and skill ids as declared in backend app.yml: lowercase start, then lowercase,
/// digits, `_` or `-` (e.g. `reminder/list-reminders`, `openmates/get-docs`).
fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value.as_bytes()[0].is_ascii_lowercase()
        && value
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_' || c == b'-')
}
fn routing_field(key: &str) -> bool {
    matches!(
        key.replace('_', "").to_lowercase().as_str(),
        "model"
            | "modelid"
            | "modelname"
            | "provider"
            | "providerid"
            | "selectedmodel"
            | "selectedaimodel"
    )
}
/// Preserve automatic routing; discard only empty/Auto selectors, never select a provider.
fn automatic_input(value: &Value, depth: usize) -> Result<Value> {
    if depth > 64 {
        return Err(Error::Invalid("App input is too deeply nested."));
    }
    match value {
        Value::Object(fields) => {
            let mut output = Plain::new(Value::Object(serde_json::Map::new()));
            for (key, value) in fields {
                if routing_field(key) {
                    if value.is_null()
                        || value
                            .as_str()
                            .is_some_and(|s| s.is_empty() || s.eq_ignore_ascii_case("auto"))
                    {
                        continue;
                    }
                    return Err(Error::Invalid("Use automatic model and provider routing."));
                }
                if [
                    "piimapping",
                    "piimappings",
                    "encryptedpiimappings",
                    "restorationmappings",
                    "embedpii",
                ]
                .contains(&key.replace('_', "").to_lowercase().as_str())
                {
                    continue;
                }
                output.as_object_mut().expect("object scratch").insert(key.clone(), automatic_input(value, depth + 1)?);
            }
            Ok(output.into_inner())
        }
        Value::Array(items) => {
            let mut output = Plain::new(Vec::with_capacity(items.len()));
            for value in items { output.push(automatic_input(value, depth + 1)?); }
            Ok(Value::Array(output.into_inner()))
        },
        _ => Ok(value.clone()),
    }
}

/// Restrictive pre-IO identity/resource/privacy proof for one direct Apps
/// operation. No chat/read/freshness/durability authority and no Clone/serde.
pub struct DirectAppSkillAdmission {
    saved: saved_chat_read::SavedChatReadAdmission,
    privacy: crate::privacy::PrivacyOptions,
    original_gate: Option<std::sync::Arc<dyn Fn()->Result<()>+Send+Sync>>,
}
impl DirectAppSkillAdmission {
    // Restrictive observer for owned IO only, never current read/publication
    // authority. The full original/current Client check surrounds apply/release.
    fn check_network_negative(&self)->Result<()> {
        self.privacy.verify()?;
        if let Some(gate)=&self.original_gate{gate()?;}
        // A successful caller callback may still cancel/deny its original
        // request. Validate every captured negative before dispatch or IO.
        self.saved.check_original_operation_negative()
    }
    pub fn check(&self,client:&Client)->Result<()> {
        self.privacy.verify()?;
        if let Some(gate)=&self.original_gate {gate()?;}
        self.saved.check(client)?;
        client.verify_private_operation()?;
        self.privacy.verify()?;
        if let Some(gate)=&self.original_gate {gate()?;}
        // Preserve callback order/count, then validate the original negatives
        // without invoking another caller gate after the validation.
        self.check_after_private_gate(client)
    }
    /// Restrictive final recheck for an already captured original admission.
    /// Callers retain their original work/policy guards and run their required
    /// callbacks first. This invokes no gate, reads no data and grants no new
    /// authority; it cannot replace the positive admission/policy check.
    #[doc(hidden)]
    pub fn check_after_private_gate(&self, client: &Client) -> Result<()> {
        self.privacy.verify()?;
        self.saved.check_after_private_gate(client)
    }
}
impl Client {
    pub fn direct_app_skill_admission(&self)->Result<DirectAppSkillAdmission> {
        self.verify_private_operation()?;
        let admission=DirectAppSkillAdmission{saved:self.saved_chat_read_admission()?,
            privacy:self.options.privacy.clone(),original_gate:self.options.private_operation_gate.clone()};
        admission.check(self)?;Ok(admission)
    }
    pub async fn app_detail(&mut self, id: &str) -> Result<Item> {
        self.require_credentials()?;
        if let Some(id) = id.strip_prefix("result:") {
            return self.app_saved_result(id).await;
        }
        if let Some(id) = id.strip_prefix("skill:") {
            let (app, skill) = id
                .split_once('/')
                .ok_or(Error::Invalid("Invalid App skill."))?;
            if !identifier(app) || !identifier(skill) {
                return Err(Error::Invalid("Invalid App skill."));
            }
            let response = self
                .request(
                    Method::GET,
                    &format!(
                        "/v1/apps/{}/skills/{}/details",
                        segment(app),
                        segment(skill)
                    ),
                    None,
                )
                .await?;
            return skill_item(app, skill, response);
        }
        if !identifier(id) {
            return Err(Error::Invalid("Invalid App ID."));
        }
        let response = self
            .request(
                Method::GET,
                &format!("/v1/apps/{}/metadata?include_unavailable=true", segment(id)),
                None,
            )
            .await?;
        let row = response
            .get("app")
            .or_else(|| response.get("apps").and_then(|apps| apps.get(id)))
            .unwrap_or(&response);
        if row
            .get("id")
            .or_else(|| row.get("app_id"))
            .and_then(Value::as_str)
            .is_some_and(|app| app != id)
        {
            return Err(Error::Protocol);
        }
        let mut fields = row.clone();
        if !fields.is_object() {
            return Err(Error::Protocol);
        }
        fields["app_id"] = json!(id);
        fields["app"] = json!(id);
        let skills = fields
            .get("skills")
            .and_then(Value::as_array)
            .ok_or(Error::Protocol)?;
        if skills.len() > 256 || skills.iter().any(|s| !identifier(text(s, "id"))) {
            return Err(Error::Protocol);
        }
        Ok(Item {
            id: id.into(),
            title: if text(row, "name").is_empty() {
                id
            } else {
                text(row, "name")
            }
            .into(),
            description: text(row, "description").into(),
            category: "Apps".into(),
            fields,
            ..Item::default()
        })
    }

    /// UI confirmation authorizes this explicit typed request and its potential charge.
    pub(super) async fn run_app_skill(&mut self, fields: Value) -> Result<Option<Item>> {
        let fields = Plain::new(fields);
        self.verify_private_operation()?;
        self.run_app_skill_with_gate(fields.into_inner(), || Ok(()))
            .await
    }
    async fn run_app_skill_with_gate(
        &mut self,
        fields: Value,
        privacy_gate: fn() -> Result<()>,
    ) -> Result<Option<Item>> {
        match self
            .execute_app_skill_mode(fields, privacy_gate, true, &mut |_: &[String]| {})
            .await?
        {
            AppSkillExecution::Retained(item) => Ok(Some(item)),
            AppSkillExecution::Direct(_) => Err(Error::Protocol),
        }
    }

    /// Existing direct-skill capability for an explicitly authenticated Personal
    /// session. Returns the resolved server envelope, without creating saved
    /// Apps embeds or a chat. Interactive Apps retains its separate opt-in path.
    /// npm/Python equivalents are the existing session runSkill/run_skill APIs.
    pub async fn run_direct_app_skill(
        &mut self,
        app: &str,
        skill: &str,
        input: Value,
    ) -> Result<Value> {
        self.run_direct_app_skill_with_task_receipt(app, skill, input, |_| {}).await
    }

    /// The receipt contains only validated original task IDs. It runs before
    /// polling, never authorizes a retry or performs durable result retention.
    /// A host may keep these IDs transiently for an actionable timeout notice.
    pub async fn run_direct_app_skill_with_task_receipt<F>(
        &mut self, app:&str, skill:&str, input:Value, mut on_tasks:F,
    )->Result<Value> where F:FnMut(&[String])+Send {
        let input=Plain::new(input);
        self.verify_private_operation()?;
        match self.execute_app_skill_mode(json!({"app":app,"skill":skill,"input":input.into_inner()}),
            ||Ok(()),false,&mut on_tasks).await? {
            AppSkillExecution::Direct(value)=>Ok(value),
            AppSkillExecution::Retained(_)=>Err(Error::Protocol),
        }
    }

    /// Stream an explicit generated-file result. Only the fixed relative embed
    /// file route receives account credentials; provider URLs never do. The
    /// caller owns private atomic file publication, not session discovery.
    pub async fn stream_generated_app_file<F>(
        &mut self,
        reference: &str,
        mut consume: F,
    ) -> Result<()>
    where
        F: FnMut(&[u8]) -> Result<()>,
    {
        self.verify_private_operation()?;
        self.require_canonical_read_profile()?;
        let original=self.direct_app_skill_admission()?;
        let scope = AsyncCryptoScope::begin(self)?;
        let authenticated = reference.starts_with('/') && !reference.starts_with("//");
        let url = if authenticated {
            let url = self.url(reference)?;
            let route_path=self.request_route_path(&url)?;
            let parts = route_path.split('/').collect::<Vec<_>>();
            if parts.len() != 5
                || parts[1] != "v1"
                || parts[2] != "embeds"
                || parts[4] != "file"
                || !uuid::Uuid::parse_str(parts[3]).is_ok_and(|id| id.to_string() == parts[3])
                || url.query_pairs().any(|(k, v)| {
                    k != "format"
                        || v.is_empty()
                        || v.len() > 32
                        || !v
                            .bytes()
                            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
                })
            {
                return Err(Error::Invalid("Unsupported generated-file route."));
            }
            url
        } else {
            url::Url::parse(reference).map_err(|_| Error::Invalid("Invalid generated-file URL."))?
        };
        if !url.username().is_empty()
            || url.password().is_some()
            || url.fragment().is_some()
            || !(url.scheme() == "https"
                || url.scheme() == "http"
                    && matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "[::1]")))
        {
            return Err(Error::Invalid("Unsupported generated-file URL."));
        }
        let mut request = self
            .http
            .request(Method::GET, url)
            .timeout(Duration::from_secs(300));
        if authenticated {
            request = crate::platform::http::browser_credentials(request, self.browser_cookies())
                .header("Origin", self.app_url())
                .header("X-OpenMates-SDK", self.options.identity.header());
            if let Some(principal) = self.expected_request_principal()? {
                request = request.header("X-OpenMates-Expected-Principal", principal);
            }
            let cookies = zeroize::Zeroizing::new(super::transport::cookie_header(&self.cookies)?);
            if !cookies.is_empty() {
                request = request.header("Cookie", cookies.as_str());
            }
        }
        let cancel = self.operation_cancel.clone();
        let mut response = tokio::select! { biased; _=cancel.cancelled()=>return Err(Error::Cancelled), r=request.send()=>r.map_err(|_|Error::Offline)? };
        if authenticated && response.status().as_u16() == 401 {
            self.forget_session();
            return Err(Error::Expired);
        }
        if authenticated && response.status().as_u16() == 403 {
            return Err(Error::Forbidden);
        }
        if !response.status().is_success() {
            return Err(Error::Protocol);
        }
        // Shared ordinary/owned header merge retains actual rotation before a
        // body truncation or stop. No cloned Session or fresh authority is made.
        if authenticated {self.apply_owned_response_cookies(response.headers(),self.generation)?;}
        scope.check(self)?;
        let mut nonempty = false;
        loop {
            let chunk = tokio::select! {biased;_=cancel.cancelled()=>return Err(Error::Cancelled),r=response.chunk()=>r.map_err(|_|Error::Offline)?};
            let Some(chunk) = chunk else { break };
            original.check(self)?;
            scope.check(self)?;
            self.verify_private_operation()?;
            if !chunk.is_empty() {
                consume(&chunk)?;
                nonempty = true;
            }
        }
        original.check(self)?;
        scope.check(self)?;
        self.verify_private_operation()?;
        if !nonempty {
            return Err(Error::Protocol);
        }
        Ok(())
    }

    async fn execute_app_skill_mode(
        &mut self,
        fields: Value,
        privacy_gate: fn() -> Result<()>,
        retain: bool,
        on_tasks: &mut (dyn FnMut(&[String]) + Send),
    ) -> Result<AppSkillExecution> {
        let fields = Plain::new(fields);
        let original=self.direct_app_skill_admission()?;
        self.require_credentials()?;
        if self.team()?.is_some() {
            return Err(Error::Invalid("Switch to Personal to run App skills."));
        }
        let cancel = self.operation_cancel.clone();
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        privacy_gate()?;
        let app = required(&fields, "app")?.to_owned();
        let skill = required(&fields, "skill")?.to_owned();
        if !identifier(&app) || !identifier(&skill) {
            return Err(Error::Invalid("Invalid App skill."));
        }
        let supplied = fields
            .get("input")
            .filter(|v| v.is_object())
            .ok_or(Error::Invalid("App input must be an object."))?;
        input_size::validate(supplied)?;
        let details = Plain::new(self.app_detail(&format!("skill:{app}/{skill}")).await?);
        if details.fields["execution_available"] != true {
            return Err(Error::Invalid("This App skill is currently unavailable."));
        }
        let input = Plain::new(automatic_input(supplied, 0)?);
        if !validate_schema(&details.fields["input_schema"], &input) {
            return Err(Error::Invalid(
                "Check the required App input fields and their types.",
            ));
        }
        self.validate_session_for_request().await?;
        let scope = AsyncCryptoScope::begin(self)?;
        let owner = Plain::new(required_owner(&self.user)?.to_owned());
        let generation = self.generation;
        // Direct CLI/SDK execution has no encrypted result graph. Do not mint a
        // result key or contact retained storage for that existing capability.
        let result_id = if retain {
            uuid::Uuid::new_v4().to_string()
        } else {
            String::new()
        };
        let key = retain.then(crypto::random_key);
        let wrapped = match &key {
            Some(key) => self.wrap_app_key(key).await?,
            None => String::new(),
        };
        let request = AppRun {
            app,
            skill,
            input: input.into_inner(),
            owner: owner.into_inner(),
            result_id,
            key,
            wrapped,
        };
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        original.check(self)?;
        self.save_app_run(&request, &json!({}), "processing")
            .await?;
        // Recheck account and local privacy immediately before the billable POST.
        self.validate_session_for_request().await?;
        self.app_owner(&request, generation)?;
        original.check(self)?;
        scope.check(self)?;
        self.verify_private_operation()?;
        privacy_gate()?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        // Do not drop an in-flight mutation: receipt/task IDs must be retained.
        let dispatched = self
            .request(
                Method::POST,
                &format!(
                    "/v1/apps/{}/skills/{}",
                    segment(&request.app),
                    segment(&request.skill)
                ),
                Some(request.input.clone()),
            )
            .await;
        let envelope = match dispatched {
            Ok(value) => Plain::new(value),
            Err(error) => {
                if !matches!(error, Error::Offline | Error::Expired) {
                    let _ = self
                        .save_app_run(
                            &request,
                            &json!({"error":"Skill execution failed."}),
                            "error",
                        )
                        .await;
                }
                return Err(error);
            }
        };
        self.app_owner(&request, generation)?;
        if failed(&envelope) {
            self.save_app_run(
                &request,
                &json!({"error":"Skill execution failed."}),
                "error",
            )
            .await?;
            return Err(Error::Invalid("App skill execution failed."));
        }
        let tasks = task_ids(&envelope)?;
        if !tasks.is_empty() {
            // Deliver only under the same original live operation/owner. This
            // does not publish skill content, claim completion or re-dispatch.
            if !retain {
                scope.check(self)?;
                self.verify_private_operation()?;
                original.check(self)?;
                on_tasks(&tasks);
            }
            // Retained Apps must still save the ORIGINAL accepted task receipt
            // after local stop, before observing cancellation at the poll gate.
            // This completes existing ciphertext durability, never a resend.
            self.save_app_run(&request, &json!({"task_ids":tasks}), "processing")
                .await?;
        }
        let result = if tasks.is_empty() {
            envelope
        } else if !retain {
            let results=self.poll_direct_app_tasks(&tasks,&cancel,&request,generation,&original).await?;
            let data=envelope.get("data").unwrap_or(&envelope);
            let merged=if data["task_id"].as_str().is_some() {
                results.into_iter().next().ok_or(Error::Protocol)?
            } else { merge_task_array_results(results) };
            if envelope.as_object().is_some_and(|row|row.contains_key("success")) {
                let mut resolved=envelope.into_inner();resolved["data"]=merged;Plain::new(resolved)
            }else{Plain::new(merged)}
        } else {
            let mut results = Plain::new(Vec::new());
            let deadline = crate::platform::time::Instant::now() + Duration::from_secs(1200);
            for task in &tasks {
                match self
                    .poll_app_task(task, deadline, &cancel, &request, generation, &original)
                    .await
                {
                    Ok(result) => results.push(result),
                    Err(error @ Error::Invalid("App task execution failed.")) => {
                        self.save_app_run(
                            &request,
                            &json!({"task_ids":tasks,"error":"App task execution failed."}),
                            "error",
                        )
                        .await?;
                        return Err(error);
                    }
                    Err(error) => return Err(error),
                }
            }
            Plain::new(merge_results(results.into_inner()))
        };
        self.app_owner(&request, generation)?;
        if failed(&result) {
            self.save_app_run(
                &request,
                &json!({"error":"Skill execution failed."}),
                "error",
            )
            .await?;
            return Err(Error::Invalid("App skill execution failed."));
        }
        if !retain {
            original.check(self)?;
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            self.app_owner(&request, generation)?;
            self.verify_private_operation()?;
            scope.check(self)?;
            return Ok(AppSkillExecution::Direct(result.into_inner()));
        }
        if self
            .save_app_run(&request, &result, "finished")
            .await
            .is_err()
        {
            self.app_owner(&request, generation)?;
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            scope.check(self)?;
            original.check(self)?;
            let mut item = Plain::new(result_item(&request, &result, "unsaved"));
            item.fields["retention_error"] = json!(
                "The skill completed, but its result could not be saved. Copy the result before leaving this view."
            );
            scope.check(self)?;
            return Ok(AppSkillExecution::Retained(item.into_inner()));
        }
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        scope.check(self)?;
        original.check(self)?;
        let item = Plain::new(result_item(&request, &result, "finished"));
        scope.check(self)?;
        Ok(AppSkillExecution::Retained(item.into_inner()))
    }

    fn app_owner(&self, request: &AppRun, generation: u64) -> Result<()> {
        self.require_credentials()?;
        if self.generation != generation
            || self.team()?.is_some()
            || required_owner(&self.user)? != request.owner
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    async fn save_app_run(
        &mut self,
        request: &AppRun,
        response: &Value,
        status: &str,
    ) -> Result<()> {
        if self.team()?.is_some() || required_owner(&self.user)? != request.owner {
            return Err(Error::Forbidden);
        }
        if request.key.is_none() {
            return Ok(());
        }
        let payload = app_run_payload(request, response, status)?;
        let receipt = self
            .request(Method::POST, "/v1/apps/workspace/results", Some(payload))
            .await?;
        if receipt
            .get("root_embed_id")
            .and_then(Value::as_str)
            .is_some_and(|id| id != request.result_id)
            || receipt.get("success") == Some(&json!(false))
        {
            return Err(Error::Protocol);
        }
        Ok(())
    }
    /// Every validated original task (existing maximum 64) can read concurrently
    /// under this SAME Client and
    /// original operation. Header/body futures own transport, never Client.
    /// Completion order cannot reorder task output or admit another skill POST.
    async fn poll_direct_app_tasks(&mut self,ids:&[String],cancel:&CancellationToken,
        request:&AppRun,generation:u64,original:&DirectAppSkillAdmission)->Result<Vec<Value>> {
        use futures_util::{StreamExt,stream::FuturesUnordered};
        const MAX_READS:usize=MAX_APP_TASKS;
        let deadline=crate::platform::time::Instant::now()+Duration::from_secs(1200);
        let budget=transport::OwnedReadByteBudget::new(MAX_APP_TASKS*transport::MAX_BODY);
        let mut result_holds=(0..ids.len()).map(|_|None::<transport::OwnedReadByteHold>).collect::<Vec<_>>();
        let mut results=Plain::new(vec![None::<Value>;ids.len()]);
        let mut pending=(0..ids.len()).collect::<std::collections::VecDeque<_>>();
        let mut reads=FuturesUnordered::new();
        let mut network=0usize;
        loop {
            original.check(self)?;self.app_owner(request,generation)?;
            if cancel.is_cancelled(){return Err(Error::Cancelled);}
            while network<MAX_READS {
                let Some(index)=pending.pop_front()else{break};original.check(self)?;
                let prepared=self.prepare_owned_read(transport::OwnedReadRoute::AppTask(&ids[index]))?;
                reads.push(drive_app_poll_read(AppPollReadStep::Headers{index,prepared},cancel,original,&budget));
                network+=1;
            }
            if results.iter().all(Option::is_some){
                original.check(self)?;
                return results.into_inner().into_iter().map(|v|v.ok_or(Error::Protocol)).collect();
            }
            let event=tokio::select!{biased;_=cancel.cancelled()=>return Err(Error::Cancelled),event=crate::platform::time::timeout_at(deadline,reads.next())=>event.map_err(|_|Error::Invalid("The App task is still pending. Generation was not retried; retain the original task ID for recovery."))?.ok_or(Error::Protocol)?};
            match event {
                AppPollReadEvent::Headers{index,result}=>match result {
                    Ok(head)=>{
                        // Actual received cookie rotation is applied on the
                        // original Client BEFORE another body/network await.
                        let body=self.apply_owned_read_headers(head)?;
                        original.check(self)?;
                        reads.push(drive_app_poll_read(AppPollReadStep::Body{index,body},cancel,original,&budget));
                    }
                    Err(Error::Offline)=>{network-=1;reads.push(drive_app_poll_read(AppPollReadStep::Delay{index},cancel,original,&budget));},
                    Err(error)=>return Err(error),
                },
                AppPollReadEvent::Body{index,result}=>{
                    network-=1;original.check(self)?;self.app_owner(request,generation)?;
                    match result {
                        Err(Error::Offline)=>{},Err(error)=>return Err(error),
                        Ok(mut done)=>{
                            let hold=done.take_byte_hold();
                            match self.finish_owned_read(done) {
                                Err(Error::Offline)=>{},Err(error)=>return Err(error),
                                Ok(value)=>{
                                    results[index]=app_task_result(&ids[index],value.ok_or(Error::Protocol)?)?;
                                    if results[index].is_some(){result_holds[index]=hold;}
                                    #[cfg(test)]
                                    if results[index].is_some(){direct_poll_observation::completed(index);}
                                }
                            }
                            original.check(self)?;
                        }
                    }
                    if results[index].is_none(){reads.push(drive_app_poll_read(AppPollReadStep::Delay{index},cancel,original,&budget));}
                }
                AppPollReadEvent::RetryReady{index,result}=>{result?;pending.push_back(index);}
            }
        }
    }
    async fn poll_app_task(&mut self,id:&str,deadline:crate::platform::time::Instant,
        cancel:&CancellationToken,request:&AppRun,generation:u64,original:&DirectAppSkillAdmission)->Result<Value> {
        loop {
            if let Some(value)=self.poll_app_task_once(id,deadline,cancel,request,generation,original).await?{return Ok(value);}
            tokio::select!{biased;_=cancel.cancelled()=>return Err(Error::Cancelled),_=crate::platform::time::sleep(Duration::from_secs(2))=>{}}
        }
    }
    async fn poll_app_task_once(&mut self,id:&str,deadline:crate::platform::time::Instant,
        cancel:&CancellationToken,request:&AppRun,generation:u64,original:&DirectAppSkillAdmission)->Result<Option<Value>> {
        self.app_owner(request,generation)?;
        original.check(self)?;
        if cancel.is_cancelled(){return Err(Error::Cancelled);}
        if crate::platform::time::Instant::now()>=deadline {
            return Err(Error::Invalid(if request.key.is_some(){
                "The App task is still pending. Its encrypted Apps result retains the task ID."
            }else{"The App task is still pending. Generation was not retried; retain the original task ID for recovery."}));
        }
        let path=format!("/v1/tasks/{}",segment(id));
        let response=tokio::select!{biased;_=cancel.cancelled()=>return Err(Error::Cancelled),result=self.request(Method::GET,&path,None)=>result};
        self.app_owner(request,generation)?;
        if request.key.is_none() {
            original.check(self)?;
            if cancel.is_cancelled(){return Err(Error::Cancelled);}
        }
        // Retained inline completion keeps the old save-before-cancel ordering;
        // no plaintext is published until the final scope/cancel check.
        app_task_result(id,match response{Err(Error::Offline)=>return Ok(None),Err(error)=>return Err(error),Ok(value)=>value})
    }
    async fn wrap_app_key(&self, key: &Key) -> Result<String> {
        let scope = AsyncCryptoScope::begin(self)?;
        if self.team()?.is_some() {
            return Err(Error::Forbidden);
        }
        let master = self.master_capability()?;
        scope.check(self)?;
        let wrapped = master.encrypt_server_bytes(key.as_ref()).await;
        scope.check(self)?;
        wrapped
    }
    async fn app_saved_result(&mut self, id: &str) -> Result<Item> {
        let scope = AsyncCryptoScope::begin(self)?;
        if self.team()?.is_some() {
            return Err(Error::Forbidden);
        }
        uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("Invalid Apps result ID."))?;
        let response = self
            .request(
                Method::GET,
                &format!("/v1/apps/workspace/results/{}", segment(id)),
                None,
            )
            .await?;
        scope.check(self)?;
        self.decode_app_saved_result(id, &response).await
    }
    async fn decode_app_saved_result(&self, id: &str, response: &Value) -> Result<Item> {
        let scope = AsyncCryptoScope::begin(self)?;
        if self.team()?.is_some() {
            return Err(Error::Forbidden);
        }
        let root = &response["root"];
        if required(root, "embed_id")? != id || text(&response["key"], "key_type") != "master" {
            return Err(Error::Forbidden);
        }
        let master = self.master_capability()?;
        scope.check(self)?;
        let decrypted = master
            .decrypt_bytes(required(&response["key"], "encrypted_embed_key")?)
            .await;
        scope.check(self)?;
        let key = key_from_bytes(&decrypted?)?;
        let plain = Plain::new(crypto::decrypt_combined(
            required(root, "encrypted_content")?,
            &key,
        )?);
        let mut content = Plain::new(super::toon::decode(&plain)?);
        let app = required(root, "app_id")?;
        let skill = required(root, "skill_id")?;
        let item = Plain::new(Item {
            id: format!("result:{id}"),
            title: format!("{app} / {skill}"),
            status: text(root, "status").into(),
            category: "Apps result".into(),
            fields: json!({"app_id":app,"skill_id":skill,"app":app,"skill":skill,"content":std::mem::take(&mut *content),"result_id":id}),
            ..Item::default()
        });
        scope.check(self)?;
        Ok(item.into_inner())
    }
}

#[cfg(test)]
mod direct_poll_observation {
    use std::{cell::RefCell,sync::Arc};
    thread_local!{static OBSERVER:RefCell<Option<Arc<dyn Fn(usize)+Send+Sync>>>=RefCell::new(None);}
    pub(super) struct Guard;
    impl Drop for Guard{fn drop(&mut self){OBSERVER.with(|slot|{slot.borrow_mut().take();});}}
    pub(super) fn install(observe:impl Fn(usize)+Send+Sync+'static)->Guard {
        OBSERVER.with(|slot|assert!(slot.borrow_mut().replace(Arc::new(observe)).is_none()));Guard
    }
    pub(super) fn completed(index:usize){OBSERVER.with(|slot|if let Some(observe)=slot.borrow().as_ref(){observe(index)});}
}
enum AppPollReadStep {
    Headers{index:usize,prepared:transport::PreparedOwnedRead},
    Body{index:usize,body:transport::OwnedReadBody},
    Delay{index:usize},
}
enum AppPollReadEvent {
    Headers{index:usize,result:Result<transport::OwnedReadHeaders>},
    Body{index:usize,result:Result<transport::CompletedOwnedRead>},
    RetryReady{index:usize,result:Result<()>},
}
async fn drive_app_poll_read(step:AppPollReadStep,cancel:&CancellationToken,original:&DirectAppSkillAdmission,budget:&transport::OwnedReadByteBudget)->AppPollReadEvent {
    match step {
        AppPollReadStep::Headers{index,prepared}=>AppPollReadEvent::Headers{index,result:transport::send_owned_read_headers(prepared,cancel,||original.check_network_negative()).await},
        AppPollReadStep::Body{index,body}=>AppPollReadEvent::Body{index,result:transport::drive_owned_read_body_with_budget(body,cancel,||original.check_network_negative(),Some(budget)).await},
        AppPollReadStep::Delay{index}=>{
            let result=async {
                original.check_network_negative()?;
                tokio::select!{biased;_=cancel.cancelled()=>return Err(Error::Cancelled),_=crate::platform::time::sleep(Duration::from_secs(2))=>{}}
                original.check_network_negative()
            }.await;
            AppPollReadEvent::RetryReady{index,result}
        },
    }
}
fn app_task_result(id:&str,value:Value)->Result<Option<Value>> {
    let mut value=Plain::new(value);
    if required(&value,"task_id")?!=id{return Err(Error::Protocol);}
    match required(&value,"status")?{
        "completed"=>Ok(Some(value.get_mut("result").ok_or(Error::Protocol)?.take())),
        "failed"=>Err(Error::Invalid("App task execution failed.")),
        "pending"|"processing"=>Ok(None),_=>Err(Error::Protocol),
    }
}
enum AppSkillExecution {
    Retained(Item),
    Direct(Value),
}

struct AppRun {
    app: String,
    skill: String,
    input: Value,
    owner: String,
    result_id: String,
    key: Option<Key>,
    wrapped: String,
}
impl Drop for AppRun {
    fn drop(&mut self) {
        // Key is already Zeroizing; typed input stays guarded across every
        // request, partial result, rejection and dropped future.
        self.app.wipe();
        self.skill.wipe();
        self.input.wipe();
        self.owner.wipe();
        self.result_id.wipe();
        self.wrapped.wipe();
    }
}

fn app_run_payload(request: &AppRun, response: &Value, status: &str) -> Result<Value> {
    let key = request.key.as_ref().ok_or(Error::Protocol)?;
    let content = Plain::new(result_content(request, response, status));
    let serialized = Plain::new(serde_json::to_string(&*content)?);
    Ok(
        json!({"app_id":request.app,"skill_id":request.skill,"root_embed_id":request.result_id,"expected_user_id":request.owner,
        "encrypted_embed_key":request.wrapped,"linked_embed_ids":[],"embeds":[{"embed_id":request.result_id,
        "encrypted_type":crypto::server_fields::encrypt_text("app_skill_use",key,&[])?,
        "encrypted_content":crypto::server_fields::encrypt_text(&serialized,key,&[])?,"status":status,"embed_ids":[]}]}),
    )
}

fn required_owner(user: &Value) -> Result<&str> {
    user.get("id")
        .or_else(|| user.get("user_id"))
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty())
        .ok_or(Error::Protocol)
}
fn skill_item(app: &str, skill: &str, mut response: Value) -> Result<Item> {
    if response["app_id"] != app
        || response["skill_id"] != skill
        || !response["input_schema"].is_object()
        || response["execution_available"].as_bool().is_none()
    {
        return Err(Error::Protocol);
    }
    response["app"] = json!(app);
    response["skill"] = json!(skill);
    response["confirmation_required"] = json!(true);
    if response["execution_mode"] == "sandbox" {
        response["execution_available"] = json!(false);
        response["unavailable_reason"] =
            json!("Native Apps sandbox output streaming is not available yet.");
    }
    if response.get("defaults").is_none() {
        response["defaults"] = json!({})
    }
    // Routing selectors are never prefilled by the native client.
    response["defaults"] = remove_routing_defaults(&response["defaults"]);
    if response.get("output_schema").is_none() {
        response["output_schema"] = json!({})
    }
    Ok(Item {
        id: format!("skill:{app}/{skill}"),
        title: if text(&response, "name").is_empty() {
            skill
        } else {
            text(&response, "name")
        }
        .into(),
        description: text(&response, "description").into(),
        category: "App skill".into(),
        fields: response,
        ..Item::default()
    })
}
fn remove_routing_defaults(value: &Value) -> Value {
    match value {
        Value::Object(fields) => Value::Object(
            fields
                .iter()
                .filter(|(key, _)| !routing_field(key))
                .map(|(key, value)| (key.clone(), remove_routing_defaults(value)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(remove_routing_defaults).collect()),
        _ => value.clone(),
    }
}
/// Skill failure detection shared with the web Apps unit (`web_apps::skill_failure`,
/// proven against `appsWorkspaceService.ts` by `web_apps_ts_vectors.json`).
fn failed(value: &Value) -> bool {
    crate::web_apps::skill_failure(value).is_some()
}
/// Accepted task ids selected exactly like the web Apps unit
/// (`web_apps::accepted_task_ids`). The native client additionally refuses an
/// envelope it could not poll safely: a non-string `task_id`/`task_ids` entry,
/// more than the accepted bound, duplicates, empty or over-long ids and any
/// character outside `[A-Za-z0-9_-]`.
fn task_ids(envelope: &Value) -> Result<Vec<String>> {
    let value = envelope.get("data").filter(|data| data.is_object()).unwrap_or(envelope);
    let malformed = match (value.get("task_id"), value.get("task_ids")) {
        (Some(id), _) => !id.is_string(),
        (None, Some(ids)) => !ids.as_array().is_some_and(|ids| ids.iter().all(Value::is_string)),
        (None, None) => false,
    };
    if malformed {
        return Err(Error::Protocol);
    }
    let ids = crate::web_apps::accepted_task_ids(envelope);
    let mut seen = std::collections::HashSet::new();
    if ids.len() > MAX_APP_TASKS
        || ids.iter().any(|id| {
            id.is_empty()
                || id.len() > 128
                || !id
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || b"_-".contains(&c))
                || !seen.insert(id.clone())
        })
    {
        return Err(Error::Protocol);
    }
    Ok(ids)
}
/// Multi-task result merge. Stays CLI-owned: it is part of the cross-SDK
/// direct-skill conformance contract (tests/sdk-conformance/fixtures/
/// direct-skill-retention.json); the web resolves tasks through
/// `web_apps::assemble_tasks_json`, which keeps the TS envelope shape instead.
fn merge_results(results: Vec<Value>) -> Value {
    let results = Plain::new(results);
    if results.len() == 1 {
        return results.into_inner().into_iter().next().unwrap_or(Value::Null);
    }
    merge_task_array_results(results.into_inner())
}
fn merge_task_array_results(results:Vec<Value>)->Value {
    let results=Plain::new(results);
    let grouped: Vec<Value> = results
        .iter()
        .flat_map(|v| {
            v.get("results")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .cloned()
        })
        .collect();
    if grouped.is_empty() {
        return json!({"results":results.into_inner()});
    }
    let mut result = results
        .first()
        .cloned()
        .filter(Value::is_object)
        .unwrap_or_else(|| json!({}));
    result["result_count"] = json!(grouped.len());
    result["results"] = json!(grouped);
    result["items"] = json!(
        results
            .iter()
            .flat_map(|v| v
                .get("items")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .cloned())
            .collect::<Vec<_>>()
    );
    for field in ["post_count", "request_count"] {
        result[field] = json!(results.iter().fold(0u64, |count, value| {
            count.saturating_add(value[field].as_u64().unwrap_or(0))
        }));
    }
    result
}
fn result_content(request: &AppRun, response: &Value, status: &str) -> Value {
    let mut content = response.get("data").unwrap_or(response).clone();
    if !content.is_object() {
        content = json!({"response":content})
    }
    content["app_id"] = json!(request.app);
    content["skill_id"] = json!(request.skill);
    content["input"] = request.input.clone();
    content["status"] = json!(status);
    content
}
fn result_item(request: &AppRun, response: &Value, status: &str) -> Item {
    Item {
        id: format!("result:{}", request.result_id),
        title: format!("{} / {}", request.app, request.skill),
        status: status.into(),
        category: "Apps result".into(),
        fields: json!({"app_id":request.app,"skill_id":request.skill,"app":request.app,"skill":request.skill,"input":request.input,"content":result_content(request,response,status),"result_id":request.result_id}),
        ..Item::default()
    }
}

/// Pre-dispatch input validation shared with the web Apps request flow
/// (`web_apps::schema`, the web form's semantics, proven by
/// `schema_ts_vectors.json`). The backend stays authoritative.
fn validate_schema(schema: &Value, value: &Value) -> bool {
    crate::web_apps::schema::validate_skill_input(schema, value).is_empty()
}

#[cfg(test)]
#[path = "../../tests/apps_unit/mod.rs"]
mod tests;

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "apps_opaque_tests.rs"]
mod opaque_tests;

#[cfg(test)]
#[path = "apps_post_gate_tests.rs"]
mod post_gate_tests;

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "apps_network_negative_tests.rs"]
mod network_negative_tests;
