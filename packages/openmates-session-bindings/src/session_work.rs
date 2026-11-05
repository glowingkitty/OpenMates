//! Named, typed workspace operations. No HTTP routes cross the language boundary.
use super::*;
use openmates_sdk::work::{
    PlanCreate, PlanFilters, PlanPatch, ProjectCreate, ProjectFilters, ProjectItemType,
    ProjectPatch, ProjectSourceCapabilitiesPatch, ProjectSourceCreate, TaskCreate, TaskFilters,
    TaskPatch, WorkflowCreate, WorkflowFilters, WorkflowPatch, WorkflowRunOptions,
    WorkflowWaitOptions,
};
use zeroize::Zeroize;

#[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProjectUnlinkInput {
    pub(crate) item_type: ProjectItemType,
    pub(crate) target_id: String,
    pub(crate) confirmed: bool,
}

pub(super) struct WorkGuard {
    state: std::sync::Weak<State>,
    id: String,
    token: CancellationToken,
    epoch: u64,
}
impl WorkGuard {
    pub(super) fn token(&self) -> CancellationToken {
        self.token.clone()
    }
    pub(super) fn cancel(&self) {
        self.token.cancel();
    }
}
impl Drop for WorkGuard {
    fn drop(&mut self) {
        if let Some(state) = self.state.upgrade() {
            if let Ok(mut operations) = state.work_operations.lock() {
                operations.remove(&self.id);
            }
            if let Ok(mut waits) = state.workflow_waits.lock() {
                waits.remove(&self.id);
            }
        }
    }
}
// Every work operation retains admission authority and a wiping result through
// the caller-side join boundary. Canonical HTTP completion remains detached.
#[cfg(test)]
#[derive(Default)]
pub(super) struct WorkReturnBarrier {
    completed_success: AtomicBool,
    expected_private_marker: Mutex<Option<String>>,
    completed_private_marker: AtomicBool,
    rejected_output_wiped: AtomicBool,
    completed: tokio::sync::Notify,
    resume: tokio::sync::Notify,
}
pub(super) fn work_authority(guard: &WorkGuard) -> Result<()> {
    let state = guard
        .state
        .upgrade()
        .ok_or(Error::Cancelled)
        .map_err(BindingError::from)?;
    if guard.token.is_cancelled()
        || guard.epoch != state.identity_epoch.load(Ordering::Acquire)
        || state.closed.load(Ordering::Acquire)
    {
        Err(Error::Cancelled.into())
    } else {
        Ok(())
    }
}
pub(super) fn release_work_output(guard: &WorkGuard, encoded: &mut String) -> Result<String> {
    if let Err(error) = work_authority(guard) {
        encoded.zeroize();
        return Err(error);
    }
    Ok(std::mem::take(encoded))
}
pub(crate) enum Request {
    TasksList(TaskFilters),
    TaskShow(String, TaskFilters),
    TaskCreate(TaskCreate, TaskFilters),
    TaskUpdate(String, TaskPatch, TaskFilters),
    TaskDelete(String, bool, TaskFilters),
    ProjectsList(ProjectFilters),
    ProjectShow(String, ProjectFilters),
    ProjectSourcesRaw(String, ProjectFilters),
    ProjectSourceDecodedNames(String, ProjectFilters),
    ProjectSourceCreate(String, Box<ProjectSourceCreate>, ProjectFilters),
    ProjectSourceCapabilities(
        String,
        String,
        ProjectSourceCapabilitiesPatch,
        ProjectFilters,
    ),
    ProjectItems(String, ProjectFilters),
    ProjectSyncWorkflowFiles(super::WorkflowFileSyncInput,ProjectFilters),
    ProjectUnlinkItem(String, ProjectItemType, String, bool, ProjectFilters),
    ProjectCreate(ProjectCreate, ProjectFilters),
    ProjectUpdate(String, ProjectPatch, ProjectFilters),
    ProjectDelete(String, bool, ProjectFilters),
    PlansList(PlanFilters),
    PlanShow(String, PlanFilters),
    PlanCreate(Box<PlanCreate>, PlanFilters),
    PlanUpdate(String, Box<PlanPatch>, PlanFilters),
    PlanDelete(String, bool, PlanFilters),
    WorkflowsList(WorkflowFilters),
    WorkflowShow(String, WorkflowFilters),
    WorkflowCreate(Box<WorkflowCreate>, WorkflowFilters),
    WorkflowUpdate(String, WorkflowPatch, WorkflowFilters),
    WorkflowDelete(String, bool, WorkflowFilters),
    WorkflowRun(String, WorkflowRunOptions, WorkflowFilters),
    WorkflowRunDetail(String, String, WorkflowFilters),
    WorkflowWait(String, String, WorkflowWaitOptions, WorkflowFilters),
    WorkflowCancelRun(String, String, WorkflowFilters),
}
// Owns genuine original admission across the foreign scheduler boundary.
// Dropping an unpolled call retires this exact guard; no replacement admission.
pub(crate) struct PreparedWork {
    bridge: SessionBridge,
    request: Request,
    guard: Arc<WorkGuard>,
}
impl PreparedWork {
    pub(crate) async fn run(self) -> Result<String> {
        let Self { bridge, request, guard } = self;
        bridge.work_transaction_admitted(request, guard).await
    }
}
pub(super) fn scope(personal: bool, team: Option<&str>) -> Result<()> {
    if personal == team.is_some() {
        return Err(Error::Invalid("Choose an explicit Personal or Team scope.").into());
    }
    Ok(())
}
impl SessionBridge {
    fn work_preflight(&self, request: &Request) -> Result<std::sync::MutexGuard<'_, super::auth_transition::IdentityTransitions>> {
        match request {
            Request::ProjectSyncWorkflowFiles(input,f)=>{scope(f.personal,f.team_id.as_deref())?;input.validate()?;},
            Request::TasksList(f) | Request::TaskShow(_, f) | Request::TaskCreate(_, f)
            | Request::TaskUpdate(_, _, f) | Request::TaskDelete(_, _, f) => scope(f.personal, f.team_id.as_deref())?,
            Request::ProjectsList(f) | Request::ProjectShow(_, f) | Request::ProjectItems(_, f)
            | Request::ProjectSourcesRaw(_, f) | Request::ProjectSourceDecodedNames(_, f)
            | Request::ProjectUnlinkItem(_, _, _, _, f) | Request::ProjectSourceCreate(_, _, f)
            | Request::ProjectSourceCapabilities(_, _, _, f) | Request::ProjectCreate(_, f)
            | Request::ProjectUpdate(_, _, f) | Request::ProjectDelete(_, _, f) => scope(f.personal, f.team_id.as_deref())?,
            Request::PlansList(f) | Request::PlanShow(_, f) | Request::PlanCreate(_, f)
            | Request::PlanUpdate(_, _, f) | Request::PlanDelete(_, _, f) => scope(f.personal, f.team_id.as_deref())?,
            Request::WorkflowsList(f) | Request::WorkflowShow(_, f) | Request::WorkflowCreate(_, f)
            | Request::WorkflowUpdate(_, _, f) | Request::WorkflowDelete(_, _, f)
            | Request::WorkflowRun(_, _, f) | Request::WorkflowRunDetail(_, _, f)
            | Request::WorkflowWait(_, _, _, f) | Request::WorkflowCancelRun(_, _, f) => scope(f.personal, f.team_id.as_deref())?,
        }
        match request {
            Request::TaskDelete(_, false, _) | Request::ProjectDelete(_, false, _)
            | Request::PlanDelete(_, false, _) | Request::WorkflowDelete(_, false, _) =>
                return Err(Error::Invalid("Explicit deletion confirmation is required.").into()),
            Request::ProjectUnlinkItem(_, _, _, false, _) =>
                return Err(Error::Invalid("Explicit unlink confirmation is required.").into()),
            Request::WorkflowWait(_, _, options, _) => options.validate().map_err(BindingError::from)?,
            _ => {}
        }
        // Capture availability and original identity once, before any observer
        // cancellation or registration. No successor transition may interleave.
        let identity = self.identity_admission()?;
        match request {
            Request::WorkflowCancelRun(_, run, filters) => {
                if filters.team_id.is_some() {
                    return Err(Error::Unavailable {
                        code: "workflow_unavailable",
                        reason: "TEAM_WORKFLOW_OPERATION_UNAVAILABLE",
                    }.into());
                }
                // Preserve exact-run observer cancellation before its canonical request.
                for wait in self.state.workflow_waits.lock()
                    .map_err(|_| BindingError::from(Error::Protocol))?.values() {
                    if &wait.run == run { wait.cancel.cancel(); }
                }
            }
            _ => {}
        }
        Ok(identity)
    }
    pub(super) fn admit_work(&self) -> Result<WorkGuard> {
        let identity = self.identity_admission()?;
        self.admit_work_locked(&identity)
    }
    fn admit_work_locked(&self, _identity: &std::sync::MutexGuard<'_, super::auth_transition::IdentityTransitions>) -> Result<WorkGuard> {
        let mut operations = self
            .state
            .work_operations
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?;
        if operations.len() >= 32 {
            return Err(Error::Conflict.into());
        }
        let id = uuid::Uuid::new_v4().to_string();
        let token = CancellationToken::new();
        operations.insert(id.clone(), token.clone());
        Ok(WorkGuard {
            state: Arc::downgrade(&self.state),
            id,
            token,
            epoch: self.state.identity_epoch.load(Ordering::Acquire),
        })
    }
    // The native adapter calls this BEFORE returning/scheduling its foreign future.
    // Public Rust async methods retain ordinary lazy-future semantics.
    pub(crate) fn prepare_work(&self, request: Request) -> Result<PreparedWork> {
        let identity = self.work_preflight(&request)?;
        let guard = Arc::new(self.admit_work_locked(&identity)?);
        drop(identity);
        Ok(PreparedWork { bridge: self.clone(), request, guard })
    }
    pub(super) async fn work_transaction(&self, request: Request) -> Result<String> {
        self.prepare_work(request)?.run().await
    }
    async fn work_transaction_admitted(&self, request: Request, guard: Arc<WorkGuard>) -> Result<String> {
        // Refuse the captured original operation before any registry/client/IO work.
        work_authority(&guard)?;
        let transaction_guard = guard.clone();
        let state = self.state.clone();
        if let Request::WorkflowWait(_, run, _, _) = &request {
            state
                .workflow_waits
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?
                .insert(
                    guard.id.clone(),
                    WorkflowWait {
                        run: run.clone(),
                        cancel: guard.token.clone(),
                    },
                );
        }
        let joined = self
            .transaction(async move {
                let guard = transaction_guard;
                let mut client = Self::live_client(&state).await?;
                if guard.token.is_cancelled()
                    || guard.epoch != state.identity_epoch.load(Ordering::Acquire)
                {
                    return Err(Error::Cancelled.into());
                }
                client.set_operation_cancel(guard.token.clone());
                // Await the complete SDK transaction even after cancellation: headers
                // may rotate credentials and a write may already have committed.
                let result = async {
                    match request {
                        Request::PlansList(f) => client
                            .plans()
                            .with_filters(f)
                            .list()
                            .await
                            .map(Value::Array),
                        Request::PlanShow(id, f) => client.plans().with_filters(f).show(&id).await,
                        Request::PlanCreate(input, f) => {
                            client.plans().with_filters(f).create(*input).await
                        }
                        Request::PlanUpdate(id, input, f) => {
                            client.plans().with_filters(f).update(&id, *input).await
                        }
                        Request::PlanDelete(id, confirmed, f) => {
                            client.plans().with_filters(f).delete(&id, confirmed).await
                        }
                        Request::WorkflowsList(f) => client
                            .workflows()
                            .with_filters(f)
                            .list()
                            .await
                            .map(Value::Array),
                        Request::WorkflowShow(id, f) => {
                            client.workflows().with_filters(f).show(&id).await
                        }
                        Request::WorkflowCreate(input, f) => {
                            client.workflows().with_filters(f).create(*input).await
                        }
                        Request::WorkflowUpdate(id, input, f) => {
                            client.workflows().with_filters(f).update(&id, input).await
                        }
                        Request::WorkflowDelete(id, confirmed, f) => {
                            client
                                .workflows()
                                .with_filters(f)
                                .delete(&id, confirmed)
                                .await
                        }
                        Request::WorkflowRun(id, input, f) => {
                            client.workflows().with_filters(f).run(&id, input).await
                        }
                        Request::WorkflowRunDetail(id, run, f) => {
                            client
                                .workflows()
                                .with_filters(f)
                                .run_detail(&id, &run)
                                .await
                        }
                        Request::WorkflowWait(id, run, options, f) => {
                            client
                                .workflows()
                                .with_filters(f)
                                .wait_run(
                                    &id,
                                    &json!({"id":run,"status":"queued"}),
                                    options,
                                    guard.token.clone(),
                                )
                                .await
                        }
                        Request::WorkflowCancelRun(id, run, f) => {
                            client
                                .workflows()
                                .with_filters(f)
                                .cancel_run(&id, &run)
                                .await
                        }
                        Request::TasksList(f) => client
                            .tasks()
                            .with_filters(f)
                            .list()
                            .await
                            .map(Value::Array),
                        Request::TaskShow(id, f) => client.tasks().with_filters(f).show(&id).await,
                        Request::TaskCreate(input, f) => {
                            client.tasks().with_filters(f).create(input).await
                        }
                        Request::TaskUpdate(id, input, f) => {
                            client.tasks().with_filters(f).update(&id, input).await
                        }
                        Request::TaskDelete(id, confirmed, f) => {
                            client.tasks().with_filters(f).delete(&id, confirmed).await
                        }
                        Request::ProjectSourcesRaw(project, f) => client.projects().with_filters(f)
                            .list_sources_raw(&project).await.map(Value::Array),
                        Request::ProjectSourceDecodedNames(project, f) => client.projects().with_filters(f)
                            .list_sources_decoded_names(&project).await.and_then(|value| serde_json::to_value(value).map_err(Error::from)),
                        Request::ProjectSourceCreate(project, input, f) => serde_json::to_value(
                            client
                                .projects()
                                .with_filters(f)
                                .create_source(&project, *input)
                                .await?,
                        )
                        .map_err(Error::from),
                        Request::ProjectSourceCapabilities(project, source, input, f) => {
                            serde_json::to_value(
                                client
                                    .projects()
                                    .with_filters(f)
                                    .update_source_capabilities(&project, &source, input)
                                    .await?,
                            )
                            .map_err(Error::from)
                        }
                        Request::ProjectsList(f) => client
                            .projects()
                            .with_filters(f)
                            .list()
                            .await
                            .map(Value::Array),
                        Request::ProjectShow(id, f) => {
                            client.projects().with_filters(f).show(&id).await
                        }
                        Request::ProjectSyncWorkflowFiles(input,f)=>input.sync(&mut client,f).await,
                        Request::ProjectItems(id, f) => {
                            client.projects().with_filters(f).items(&id).await
                        }
                        Request::ProjectUnlinkItem(id, kind, target, confirmed, f) => {
                            client
                                .projects()
                                .with_filters(f)
                                .unlink_item(&id, kind, &target, confirmed)
                                .await
                        }
                        Request::ProjectCreate(input, f) => {
                            client.projects().with_filters(f).create(input).await
                        }
                        Request::ProjectUpdate(id, input, f) => {
                            client.projects().with_filters(f).update(&id, input).await
                        }
                        Request::ProjectDelete(id, confirmed, f) => {
                            client
                                .projects()
                                .with_filters(f)
                                .delete(&id, confirmed)
                                .await
                        }
                    }
                }
                .await;
                client.set_operation_cancel(CancellationToken::new());
                let value = result.map_err(BindingError::from)?;
                work_authority(&guard)?;
                let encoded = Zeroizing::new(
                    serde_json::to_string(&value)
                        .map_err(|_| BindingError::from(Error::Protocol))?,
                );
                work_authority(&guard)?;
                Ok(encoded)
            })
            .await;
        #[cfg(test)]
        let return_barrier = self
            .state
            .work_return_barrier
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .take();
        #[cfg(test)]
        if let Some(barrier) = &return_barrier {
            barrier
                .completed_success
                .store(joined.is_ok(), Ordering::Release);
            let expected = barrier
                .expected_private_marker
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?
                .clone();
            barrier.completed_private_marker.store(
                joined.as_ref().is_ok_and(|encoded| {
                    expected
                        .as_ref()
                        .is_some_and(|marker| encoded.contains(marker))
                }),
                Ordering::Release,
            );
            barrier.completed.notify_one();
            barrier.resume.notified().await;
        }
        // Keep admission registered across this await: cancel_pending, reset,
        // logout and identity replacement can invalidate a completed result.
        // Mask stale errors too, so an old failure cannot clear a newer session.
        if work_authority(&guard).is_err() {
            if let Ok(mut encoded) = joined {
                encoded.zeroize();
                #[cfg(test)]
                if let Some(barrier) = &return_barrier {
                    barrier
                        .rejected_output_wiped
                        .store(encoded.is_empty(), Ordering::Release);
                }
            }
            return Err(Error::Cancelled.into());
        }
        let mut encoded = joined?;
        release_work_output(&guard, &mut encoded)
    }
    pub async fn tasks_list(&self, filters: TaskFilters) -> Result<String> {
        self.work_transaction(Request::TasksList(filters)).await
    }
    pub async fn tasks_show(&self, id: String, filters: TaskFilters) -> Result<String> {
        self.work_transaction(Request::TaskShow(id, filters)).await
    }
    pub async fn tasks_create(&self, input: TaskCreate, filters: TaskFilters) -> Result<String> {
        self.work_transaction(Request::TaskCreate(input, filters))
            .await
    }
    pub async fn tasks_update(
        &self,
        id: String,
        input: TaskPatch,
        filters: TaskFilters,
    ) -> Result<String> {
        self.work_transaction(Request::TaskUpdate(id, input, filters))
            .await
    }
    pub async fn tasks_delete(
        &self,
        id: String,
        confirmed: bool,
        filters: TaskFilters,
    ) -> Result<String> {
        self.work_transaction(Request::TaskDelete(id, confirmed, filters))
            .await
    }
    pub async fn projects_list(&self, filters: ProjectFilters) -> Result<String> {
        self.work_transaction(Request::ProjectsList(filters)).await
    }
    pub async fn projects_show(&self, id: String, filters: ProjectFilters) -> Result<String> {
        self.work_transaction(Request::ProjectShow(id, filters))
            .await
    }
    pub async fn projects_items(&self, id: String, filters: ProjectFilters) -> Result<String> {
        self.work_transaction(Request::ProjectItems(id, filters))
            .await
    }
    pub async fn projects_unlink_item(
        &self,
        id: String,
        item_type: ProjectItemType,
        target_id: String,
        confirmed: bool,
        filters: ProjectFilters,
    ) -> Result<String> {
        self.work_transaction(Request::ProjectUnlinkItem(
            id, item_type, target_id, confirmed, filters,
        ))
        .await
    }
    /// Existing encrypted bindings only. Paths express local approval intent
    /// across the explicit scope; real focus/settings/server approval still run.
    pub async fn projects_sync_workflow_files(&self,workflow_id:String,expected_version:String,source_chat:Option<String>,approved_paths:Vec<String>,filters:ProjectFilters)->Result<String>{
        self.work_transaction(Request::ProjectSyncWorkflowFiles(super::WorkflowFileSyncInput{workflow_id,expected_version,source_chat,approved_paths},filters)).await
    }
    pub async fn projects_list_sources_raw(&self, project: String, filters: ProjectFilters) -> Result<String> {
        self.work_transaction(Request::ProjectSourcesRaw(project, filters)).await
    }
    pub async fn projects_list_sources_decoded_names(&self, project: String, filters: ProjectFilters) -> Result<String> {
        self.work_transaction(Request::ProjectSourceDecodedNames(project, filters)).await
    }
    pub async fn projects_create_source(
        &self,
        project: String,
        input: ProjectSourceCreate,
        filters: ProjectFilters,
    ) -> Result<String> {
        self.work_transaction(Request::ProjectSourceCreate(
            project,
            Box::new(input),
            filters,
        ))
        .await
    }
    pub async fn projects_update_source_capabilities(
        &self,
        project: String,
        source: String,
        input: ProjectSourceCapabilitiesPatch,
        filters: ProjectFilters,
    ) -> Result<String> {
        self.work_transaction(Request::ProjectSourceCapabilities(
            project, source, input, filters,
        ))
        .await
    }
    pub async fn projects_create(
        &self,
        input: ProjectCreate,
        filters: ProjectFilters,
    ) -> Result<String> {
        self.work_transaction(Request::ProjectCreate(input, filters))
            .await
    }
    pub async fn projects_update(
        &self,
        id: String,
        input: ProjectPatch,
        filters: ProjectFilters,
    ) -> Result<String> {
        self.work_transaction(Request::ProjectUpdate(id, input, filters))
            .await
    }
    pub async fn projects_delete(
        &self,
        id: String,
        confirmed: bool,
        filters: ProjectFilters,
    ) -> Result<String> {
        self.work_transaction(Request::ProjectDelete(id, confirmed, filters))
            .await
    }
}
#[cfg(test)]
mod tests {
    // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
    use super::*;
    fn bridge() -> SessionBridge {
        SessionBridge::new(r#"{"api_url":"http://127.0.0.1:1","app_url":null,"enhanced_privacy":false,"allow_private_operations":false}"#).unwrap_or_else(|_| panic!("bridge"))
    }
    #[tokio::test]
    async fn project_item_inputs_are_strict_and_confirmation_is_boolean() {
        let good = json!({"item_type":"chat","target_id":"exact","confirmed":true});
        let input = decode_input::<ProjectUnlinkInput>(good.to_string())
            .unwrap_or_else(|_| panic!("typed unlink"));
        assert!(matches!(input.item_type, ProjectItemType::Chat));
        assert_eq!(input.target_id, "exact");
        assert!(input.confirmed);
        for bad in [json!("true"), json!(1), Value::Null] {
            let mut input = good.clone();
            input["confirmed"] = bad;
            assert!(decode_input::<ProjectUnlinkInput>(input.to_string()).is_err());
        }
        for (field, bad) in [("item_type", json!("upload")), ("unknown", json!(true))] {
            let mut input = good.clone();
            input[field] = bad;
            assert!(decode_input::<ProjectUnlinkInput>(input.to_string()).is_err());
        }
        let bridge = bridge();
        assert_eq!(
            bridge
                .projects_unlink_item(
                    "id".into(),
                    ProjectItemType::Chat,
                    "exact".into(),
                    false,
                    ProjectFilters {
                        personal: true,
                        ..Default::default()
                    }
                )
                .await
                .err()
                .map(|e| e.code),
            Some("invalid_argument")
        );
        assert!(bridge.state.work_operations.lock().unwrap().is_empty());
    }
    #[tokio::test]
    async fn scope_confirmation_and_strict_inputs_fail_before_network() {
        let bridge = bridge();
        assert_eq!(
            bridge
                .tasks_list(TaskFilters::default())
                .await
                .err()
                .map(|e| e.code),
            Some("invalid_argument")
        );
        let f = TaskFilters {
            personal: true,
            ..Default::default()
        };
        assert_eq!(
            bridge
                .tasks_delete("x".into(), false, f)
                .await
                .err()
                .map(|e| e.code),
            Some("invalid_argument")
        );
        assert!(
            decode_input::<TaskCreate>(r#"{"title":"synthetic","model":"override"}"#.into())
                .is_err()
        );
        assert!(
            decode_input::<TaskPatch>(r#"{"due_at":null}"#.into())
                .unwrap_or_else(|_| panic!("patch"))
                .due_at
                == Some(None)
        );
        assert!(decode_input::<TaskCreate>(" ".repeat(1024 * 1024 + 1)).is_err());
        assert!(bridge.state.work_operations.lock().unwrap().is_empty());
    }
    #[tokio::test]
    async fn queued_work_cancellation_and_identity_epoch_are_fenced() {
        let bridge = bridge();
        let held = bridge.state.client.lock().await;
        let queued_bridge = bridge.clone();
        let queued = tokio::spawn(async move {
            queued_bridge
                .tasks_list(TaskFilters {
                    personal: true,
                    ..Default::default()
                })
                .await
        });
        tokio::time::timeout(std::time::Duration::from_secs(1), async {
            while bridge.state.work_operations.lock().unwrap().is_empty() {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        bridge.cancel().unwrap_or_else(|_| panic!("cancel"));
        drop(held);
        assert_eq!(
            queued.await.unwrap().err().map(|e| e.code),
            Some("cancelled")
        );
        assert!(bridge.state.work_operations.lock().unwrap().is_empty());
        let held = bridge.state.client.lock().await;
        let queued_bridge = bridge.clone();
        let queued = tokio::spawn(async move {
            queued_bridge
                .projects_list(ProjectFilters {
                    personal: true,
                    ..Default::default()
                })
                .await
        });
        tokio::time::timeout(std::time::Duration::from_secs(1), async {
            while bridge.state.work_operations.lock().unwrap().is_empty() {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        bridge.state.identity_epoch.fetch_add(1, Ordering::AcqRel);
        drop(held);
        assert_eq!(
            queued.await.unwrap().err().map(|e| e.code),
            Some("cancelled")
        );
        assert!(bridge.state.work_operations.lock().unwrap().is_empty());
    }
}

#[cfg(test)]
mod source_binding_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
    #[test]
    fn source_input_deserialization_preserves_complete_metadata_and_legacy_create_caps() {
        let raw = json!({"source_id":"source","source_type":"local_folder","display_name":"Synthetic","metadata":{"teamId":{"updatedAt":1},"__proto__":{"keep":true},"root":"/synthetic","binding_root":"/synthetic"},"capabilities":["read","read"],"status":"offline","created_at":1,"updated_at":2,"last_indexed_at":null});
        let input: ProjectSourceCreate =
            decode_input(raw.to_string()).unwrap_or_else(|_| panic!("typed create"));
        assert_eq!(input.metadata, raw["metadata"].as_object().unwrap().clone());
        assert_eq!(input.capabilities.len(), 2);
        let oversized = " ".repeat(1024 * 1024 + 1);
        assert_eq!(
            decode_input::<ProjectSourceCreate>(oversized)
                .err()
                .unwrap()
                .message,
            "Work input exceeds the supported size."
        );
        let deep = format!("{}0{}", "[".repeat(130), "]".repeat(130));
        let mut deep_input = raw.clone();
        deep_input["metadata"] = json!({"value":"__DEEP__"});
        let deep_input = deep_input.to_string().replace(r#""__DEEP__""#, &deep);
        assert_eq!(
            decode_input::<ProjectSourceCreate>(deep_input)
                .err()
                .unwrap()
                .message,
            "Invalid typed work input."
        );
        let mut unknown = raw;
        unknown["private-secret"] = json!(true);
        assert_eq!(
            decode_input::<ProjectSourceCreate>(unknown.to_string())
                .err()
                .unwrap()
                .message,
            "Invalid typed work input."
        );
        assert_eq!(
            decode_input::<ProjectSourceCapabilitiesPatch>(
                r#"{"capabilities":["unsupported-private"],"updated_at":1}"#.into()
            )
            .err()
            .unwrap()
            .message,
            "Invalid typed work input."
        );
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
    #[tokio::test]
    async fn source_work_scope_rejects_before_session_or_transport() {
        let bridge=SessionBridge::new(r#"{"api_url":"http://127.0.0.1:1","app_url":null,"enhanced_privacy":false,"allow_private_operations":false}"#).unwrap_or_else(|_|panic!("bridge"));
        let input = ProjectSourceCapabilitiesPatch {
            capabilities: vec![],
            updated_at: 1,
        };
        let error = bridge
            .projects_update_source_capabilities(
                "project".into(),
                "source".into(),
                input,
                ProjectFilters::default(),
            )
            .await
            .err()
            .unwrap();
        assert_eq!(error.code, "invalid_argument");
    }
}

#[cfg(test)]
#[path = "session_project_sources_tests.rs"]
mod source_lifecycle_tests;

#[cfg(test)]
#[path = "session_work_return_tests.rs"]
mod work_return_tests;

#[cfg(test)]
#[path = "session_work_pre_poll_tests.rs"]
mod pre_poll_tests;
