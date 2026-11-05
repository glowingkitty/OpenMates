use crate::{BindingError, SessionBridge};
use napi_derive::napi;
fn error(error: BindingError) -> napi::Error {
    napi::Error::new(napi::Status::GenericFailure, error.json())
}
#[napi(js_name = "reconstructEmbedVersion")]
pub fn reconstruct_embed_version(input_json: String) -> napi::Result<String> {
    crate::reconstruct_embed_version_json(input_json).map_err(error)
}
#[napi(js_name = "privacy")]
pub fn privacy(input_json: String) -> napi::Result<String> {
    crate::privacy_json(input_json).map_err(error)
}
#[napi(js_name = "taskOrder")]
pub fn task_order(input_json: String) -> napi::Result<String> {
    crate::sort_tasks_json(input_json).map_err(error)
}
#[napi(js_name = "NativeInitialSyncOperation")]
pub struct NodeInitialSyncOperation {
    prepared: std::sync::Mutex<Option<crate::PreparedInitialSyncOperation>>,
    control: crate::InitialSyncOperationControl,
}
impl Drop for NodeInitialSyncOperation { fn drop(&mut self) { self.control.cancel(); } }
#[napi]
impl NodeInitialSyncOperation {
    #[napi]
    pub async fn run(&self) -> napi::Result<NodeInitialSyncMetadata> {
        let prepared = self.prepared.try_lock().map_err(|_| error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(|| error(openmates_sdk::Error::Conflict.into()))?;
        Ok(NodeInitialSyncMetadata { value: prepared.run().await.map_err(error)? })
    }
    #[napi]
    pub fn cancel(&self) { self.control.cancel(); }
}
#[napi(js_name = "NativeInitialSyncMetadata")]
pub struct NodeInitialSyncMetadata { value: crate::InitialSyncMetadata }
#[napi]
impl NodeInitialSyncMetadata {
    #[napi]
    pub async fn received_metadata_count(&self) -> napi::Result<u32> {
        self.value.received_metadata_count().await.map_err(error)
    }
    #[napi]
    pub fn cancel(&self) { self.value.cancel(); }
}
#[napi(js_name = "NativeSessionClient")]
pub struct NodeSessionClient {
    bridge: SessionBridge,
}
impl Drop for NodeSessionClient {
    fn drop(&mut self) {
        let _ = self.bridge.cancel();
    }
}
#[napi]
impl NodeSessionClient {
    #[napi]
    pub fn initial_sync_open(&self, id: String) -> napi::Result<NodeInitialSyncOperation> {
        let prepared = self.bridge.prepare_initial_sync(id).map_err(error)?;
        let control = prepared.control();
        Ok(NodeInitialSyncOperation { prepared: std::sync::Mutex::new(Some(prepared)), control })
    }
    #[napi]
    pub fn account_reminders_open(&self) -> napi::Result<NodeSettingsRemindersOperation> {
        let prepared = self.bridge.prepare_account_reminders().map_err(error)?;
        let control = prepared.control();
        Ok(NodeSettingsRemindersOperation { prepared: std::sync::Mutex::new(Some(prepared)), control })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn first_page_open<'env>(&self, env:&'env napi::Env, id: String, include_secrets: bool, include_private_output: bool) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_first_page_open(id,include_secrets,include_private_output);
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi]
    pub async fn first_page_next(&self,id:String)->napi::Result<String>{self.bridge.first_page_next(id).await.map_err(error)}
    #[napi]
    pub fn first_page_receipt(&self,id:String,stage_id:String,receipt:String)->napi::Result<()>{self.bridge.first_page_receipt(id,stage_id,receipt).map_err(error)}
    #[napi]
    pub fn first_page_capacity(&self,id:String,stage_id:String,accepted:bool)->napi::Result<()>{self.bridge.first_page_capacity(id,stage_id,accepted).map_err(error)}
    #[napi]
    pub fn first_page_close(&self,id:String)->napi::Result<()>{self.bridge.first_page_close(id).map_err(error)}
    #[napi(ts_return_type = "Promise<string>")]
    pub fn cache_chat_stage<'env>(&self, env:&'env napi::Env, id: String, include_secrets: bool) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_cache_chat_stage(id,include_secrets);
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi]
    pub async fn cache_chat_commit(&self, stage_id: String, receipt: String) -> napi::Result<String> {
        self.bridge.cache_chat_commit(stage_id, receipt).await.map_err(error)
    }
    #[napi]
    pub fn cache_chat_discard(&self, stage_id: String) -> napi::Result<()> {
        self.bridge.cache_chat_discard(stage_id).map_err(error)
    }
    #[napi]
    pub async fn chat_monitor_stage_prefer_cache(&self, id: String, include_secrets: bool, selected: Option<String>) -> napi::Result<String> {
        self.bridge.chat_monitor_stage_prefer_cache(id, selected, include_secrets).await.map_err(error)
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn embeds_share_url<'env>(&self, env:&'env napi::Env, id: String, expires_json: String, password: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_embeds_share_url(id, expires_json, password);
        env.spawn_future(async move { prepared.await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn embeds_version_content<'env>(&self, env:&'env napi::Env, id: String, version_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_embeds_version_content(id,version_json);
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn drafts_list_cached<'env>(&self, env:&'env napi::Env) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_drafts_list_cached();
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn drafts_list<'env>(&self, env:&'env napi::Env, options: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_drafts_list(options);
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn drafts_get<'env>(&self, env:&'env napi::Env, id: String, options: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_drafts_get(id,options);
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn drafts_sync<'env>(&self, env:&'env napi::Env) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_drafts_sync();
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }

    #[napi]
    pub async fn chat_monitor_validate(&self, id: String) -> napi::Result<()> {
        self.bridge.chat_monitor_validate(id).await.map_err(error)
    }
    #[napi]
    pub fn completion_recovery_discard(&self, id: String) -> napi::Result<()> {
        self.bridge.completion_recovery_discard(id).map_err(error)
    }
    #[napi]
    pub fn chat_monitor_access_denial(&self, id: String) -> napi::Result<String> {
        self.bridge.chat_monitor_access_denial(id).map_err(error)
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn chat_monitor_open<'env>(&self, env:&'env napi::Env) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_chat_monitor_open();
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi]
    pub async fn chat_monitor_next(&self, id: String) -> napi::Result<String> {
        self.bridge.chat_monitor_next(id).await.map_err(error)
    }
    #[napi]
    pub async fn chat_monitor_stage(
        &self,
        id: String,
        include_secrets: bool,
        selected: Option<String>,
    ) -> napi::Result<String> {
        self.bridge
            .chat_monitor_stage(id, selected, include_secrets)
            .await
            .map_err(error)
    }
    #[napi]
    pub async fn chat_monitor_commit(
        &self,
        id: String,
        stage_id: String,
        receipt: String,
    ) -> napi::Result<String> {
        self.bridge
            .chat_monitor_commit(id, stage_id, receipt)
            .await
            .map_err(error)
    }
    #[napi]
    pub fn chat_monitor_discard(&self, id: String, stage_id: String) -> napi::Result<()> {
        self.bridge
            .chat_monitor_discard(id, stage_id)
            .map_err(error)
    }
    #[napi]
    pub fn chat_monitor_close(&self, id: String) -> napi::Result<()> {
        self.bridge.chat_monitor_close(id).map_err(error)
    }
    #[napi(ts_return_type = "Promise<void>")]
    pub fn completion_recovery_enable<'env>(&self, env:&'env napi::Env, enabled: bool) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,()>> {
        let prepared = self.bridge.capture_completion_recovery_enable(enabled);
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn completion_recovery_jobs<'env>(&self, env:&'env napi::Env) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_completion_recovery_discover(None);
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn completion_recovery_jobs_for_chat<'env>(&self, env:&'env napi::Env, chat_id: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_completion_recovery_discover(Some(chat_id));
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi]
    pub async fn completion_recovery_stage(&self, id: String) -> napi::Result<String> {
        self.bridge
            .completion_recovery_stage(id)
            .await
            .map_err(error)
    }
    #[napi]
    pub async fn completion_recovery_resume(&self, checkpoint: String) -> napi::Result<String> {
        self.bridge
            .completion_recovery_resume(checkpoint)
            .await
            .map_err(error)
    }
    #[napi]
    pub async fn completion_recovery_commit(
        &self,
        id: String,
        receipt: String,
    ) -> napi::Result<String> {
        self.bridge
            .completion_recovery_commit(id, receipt)
            .await
            .map_err(error)
    }
    #[napi(constructor)]
    pub fn new(options_json: String) -> napi::Result<Self> {
        Ok(Self {
            bridge: SessionBridge::with_identity(&options_json, openmates_sdk::ClientIdentity::Npm)
                .map_err(error)?,
        })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn project_task_watch_open<'env>(&self, env:&'env napi::Env, project: String, input_json: String, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_project_task_watch_open(project,input_json,filters_json);
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi]
    pub async fn project_task_watch_next(&self, id: String) -> napi::Result<String> {
        self.bridge.project_task_watch_next(id).await.map_err(error)
    }
    #[napi]
    pub async fn project_task_watch_commit(
        &self,
        id: String,
        receipt_json: String,
    ) -> napi::Result<()> {
        self.bridge
            .project_task_watch_commit(id, receipt_json)
            .await
            .map_err(error)
    }
    #[napi]
    pub fn project_task_watch_close(&self, id: String) -> napi::Result<()> {
        self.bridge.project_task_watch_close(id).map_err(error)
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn login_password<'env>(
        &self, env: &'env napi::Env,
        email: String,
        password: String,
        tfa: Option<String>,
        stay_logged_in: Option<bool>,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_login_password(email, password, tfa, openmates_sdk::PasswordLoginOptions { stay_logged_in: stay_logged_in.unwrap_or(false) }).map_err(error)?;
        env.spawn_future(async move { prepared.run_string().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<void>")]
    pub fn import_session<'env>(&self, env: &'env napi::Env, session_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, ()>> {
        let prepared = self.bridge.prepare_import_session(session_json).map_err(error)?;
        env.spawn_future(async move { prepared.run_unit().await.map_err(error) })
    }
    #[napi]
    pub async fn export_session(&self, include_secrets: bool) -> napi::Result<String> {
        self.bridge
            .export_session(include_secrets)
            .await
            .map_err(error)
    }
    #[napi]
    pub async fn validate_session(&self) -> napi::Result<()> {
        self.bridge.validate_session().await.map_err(error)
    }
    #[napi]
    pub fn apps_inventory_open(&self)->napi::Result<NodeAppsInventoryOperation>{
        let prepared=self.bridge.prepare_apps_inventory().map_err(error)?;
        let cancel=prepared.cancellation_request();
        Ok(NodeAppsInventoryOperation{prepared:std::sync::Mutex::new(Some(prepared)),cancel})
    }
    #[napi(ts_return_type = "Promise<NativeAppsInventoryOutput>")]
    pub fn apps_inventory_prepare<'env>(&self,env:&'env napi::Env)->napi::Result<napi::bindgen_prelude::PromiseRaw<'env,NodeAppsInventoryOutput>>{
        let prepared=self.bridge.capture_apps_inventory_prepare();
        env.spawn_future(async move {prepared.await.map(|output|NodeAppsInventoryOutput{output:std::sync::Mutex::new(Some(output))}).map_err(error)})
    }
    #[napi]
    pub async fn list(&self, workspace: String) -> napi::Result<String> {
        self.bridge.list(workspace).await.map_err(error)
    }
    #[napi(ts_return_type = "Promise<NativeChatDetailsOutput>")]
    pub fn chat_details_prepare<'env>(&self, env:&'env napi::Env, id: String, options_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,NodeChatDetailsOutput>> {
        let prepared = self.bridge.capture_chat_details_prepare(id,options_json);
        env.spawn_future(async move {
            prepared.await.map(|output| NodeChatDetailsOutput { output: std::sync::Mutex::new(Some(output)) }).map_err(error)
        })
    }
    #[napi(ts_return_type = "Promise<NativeFullChatOutput>")]
    pub fn open_chat_prepare<'env>(&self, env:&'env napi::Env, id: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,NodeFullChatOutput>> {
        let prepared = self.bridge.capture_full_chat_read_prepare(id);
        env.spawn_future(async move {
            prepared.await.map(|output| NodeFullChatOutput { output: std::sync::Mutex::new(Some(output)) }).map_err(error)
        })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn chat_message_window<'env>(&self, env:&'env napi::Env, id: String, options: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_chat_message_window(id,options);
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn saved_chat_read<'env>(&self, env:&'env napi::Env, id: String, options: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_saved_chat_read(id,options);
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn saved_chat_exact_message<'env>(&self, env:&'env napi::Env, id: String, options: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_saved_chat_exact_message(id,options);
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi(ts_return_type = "Promise<void>")]
    pub fn set_team<'env>(&self, env: &'env napi::Env, id: Option<String>) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, ()>> {
        let prepared = self.bridge.prepare_set_team(id).map_err(error)?;
        env.spawn_future(async move { prepared.run_unit().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn start_send<'env>(&self, env:&'env napi::Env, text: String, chat_id: Option<String>) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>> {
        let prepared = self.bridge.capture_start_saved_stream(text,chat_id);
        env.spawn_future(async move {
            prepared.await.map_err(error)
        })
    }
    #[napi(ts_return_type = "Promise<NativeDirectSkillOutput>")]
    pub fn run_skill_prepare<'env>(&self, env:&'env napi::Env, app:String, skill:String, input:String)->napi::Result<napi::bindgen_prelude::PromiseRaw<'env,NodeDirectSkillOutput>> {
        let prepared = self.bridge.run_skill_prepare(app,skill,input);
        env.spawn_future(async move {
            prepared.await
                .map(|output|NodeDirectSkillOutput{output:std::sync::Mutex::new(Some(output))}).map_err(error)
        })
    }
    #[napi]
    pub async fn next_event_prepare(&self, id: String) -> napi::Result<NodeSavedStreamOutput> {
        self.bridge.next_event_prepare(id).await
            .map(|output| NodeSavedStreamOutput { output: std::sync::Mutex::new(Some(output)) })
            .map_err(error)
    }
    #[napi]
    pub async fn next_event(&self, id: String) -> napi::Result<String> {
        self.bridge.next_anonymous_event(id).await.map_err(error)
    }
    #[napi]
    pub async fn start_anonymous(
        &self,
        anonymous_id: String,
        text: String,
        options_json: String,
    ) -> napi::Result<String> {
        self.bridge
            .start_anonymous(
                anonymous_id,
                text,
                crate::session::anonymous::options(options_json).map_err(error)?,
            )
            .await
            .map_err(error)
    }
    #[napi]
    pub fn cancel_stream(&self, id: String) -> napi::Result<()> {
        self.bridge.cancel_stream(id).map_err(error)
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn tasks_list<'env>(&self, env: &'env napi::Env, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::TasksList(crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn tasks_show<'env>(&self, env: &'env napi::Env, id: String, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::TaskShow(id, crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn tasks_create<'env>(
        &self, env: &'env napi::Env,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::TaskCreate(crate::session::decode_input(input_json).map_err(error)?, crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn tasks_update<'env>(
        &self, env: &'env napi::Env,
        id: String,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::TaskUpdate(id, crate::session::decode_input(input_json).map_err(error)?, crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn tasks_delete<'env>(
        &self, env: &'env napi::Env,
        id: String,
        confirmed: bool,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::TaskDelete(id, confirmed, crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn projects_list<'env>(&self, env: &'env napi::Env, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectsList(crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn projects_show<'env>(&self, env: &'env napi::Env, id: String, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectShow(id, crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn projects_items<'env>(&self, env: &'env napi::Env, id: String, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectItems(id, crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn projects_unlink_item<'env>(
        &self, env: &'env napi::Env,
        id: String,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let input: crate::session::ProjectUnlinkInput =
            crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectUnlinkItem(id, input.item_type, input.target_id, input.confirmed, filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn projects_sync_workflow_files<'env>(&self,env:&'env napi::Env,input_json:String,filters_json:String)->napi::Result<napi::bindgen_prelude::PromiseRaw<'env,String>>{
        let input=crate::session::decode_input(input_json).map_err(error)?;
        let filters=crate::session::decode_input(filters_json).map_err(error)?;
        let prepared=self.bridge.prepare_work(crate::session::WorkRequest::ProjectSyncWorkflowFiles(input,filters)).map_err(error)?;
        env.spawn_future(async move{prepared.run().await.map_err(error)})
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn projects_list_sources_raw<'env>(&self, env: &'env napi::Env, project: String, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectSourcesRaw(project, crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn projects_list_sources_decoded_names<'env>(&self, env: &'env napi::Env, project: String, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectSourceDecodedNames(project, crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn projects_create_source<'env>(
        &self, env: &'env napi::Env,
        project: String,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectSourceCreate(project, Box::new(crate::session::decode_input(input_json).map_err(error)?), crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn projects_update_source_capabilities<'env>(
        &self, env: &'env napi::Env,
        project: String,
        source: String,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectSourceCapabilities(project, source, crate::session::decode_input(input_json).map_err(error)?, crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn projects_create<'env>(
        &self, env: &'env napi::Env,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectCreate(crate::session::decode_input(input_json).map_err(error)?, crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn projects_update<'env>(
        &self, env: &'env napi::Env,
        id: String,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectUpdate(id, crate::session::decode_input(input_json).map_err(error)?, crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn projects_delete<'env>(
        &self, env: &'env napi::Env,
        id: String,
        confirmed: bool,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectDelete(id, confirmed, crate::session::decode_input(filters_json).map_err(error)?)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn plans_list<'env>(&self, env: &'env napi::Env, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::PlansList(filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn plans_show<'env>(&self, env: &'env napi::Env, id: String, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::PlanShow(id, filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn plans_create<'env>(
        &self, env: &'env napi::Env,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::PlanCreate(Box::new(input), filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn plans_update<'env>(
        &self, env: &'env napi::Env,
        id: String,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::PlanUpdate(id, Box::new(input), filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn plans_delete<'env>(
        &self, env: &'env napi::Env,
        id: String,
        confirmed: bool,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::PlanDelete(id, confirmed, filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn workflows_list<'env>(&self, env: &'env napi::Env, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowsList(filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn workflows_show<'env>(&self, env: &'env napi::Env, id: String, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowShow(id, filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn workflows_create<'env>(
        &self, env: &'env napi::Env,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowCreate(Box::new(input), filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn workflows_update<'env>(
        &self, env: &'env napi::Env,
        id: String,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowUpdate(id, input, filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn workflows_delete<'env>(
        &self, env: &'env napi::Env,
        id: String,
        confirmed: bool,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowDelete(id, confirmed, filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn workflows_run<'env>(
        &self, env: &'env napi::Env,
        id: String,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowRun(id, input, filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn workflows_run_detail<'env>(
        &self, env: &'env napi::Env,
        id: String,
        run: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowRunDetail(id, run, filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn workflows_wait<'env>(
        &self, env: &'env napi::Env,
        id: String,
        run: String,
        input_json: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowWait(id, run, input, filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<string>")]
    pub fn workflows_cancel_run<'env>(
        &self, env: &'env napi::Env,
        id: String,
        run: String,
        filters_json: String,
    ) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, String>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowCancelRun(id, run, filters)).map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
    #[napi]
    pub fn cancel(&self) -> napi::Result<()> {
        self.bridge.cancel().map_err(error)
    }
    #[napi]
    pub fn consent(&self, request_id: String, approved: Vec<String>) -> napi::Result<()> {
        self.bridge.consent(request_id, approved).map_err(error)
    }
    #[napi(ts_return_type = "Promise<void>")]
    pub fn logout<'env>(&self, env: &'env napi::Env) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, ()>> {
        let prepared = self.bridge.prepare_logout().map_err(error)?;
        env.spawn_future(async move { prepared.run_unit().await.map_err(error) })
    }
    #[napi(ts_return_type = "Promise<void>")]
    pub fn close<'env>(&self, env: &'env napi::Env) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, ()>> {
        let prepared = self.bridge.prepare_close().map_err(error)?;
        env.spawn_future(async move { prepared.run().await.map_err(error) })
    }
}

// Internal opaque async result. Only this synchronous method creates plaintext
// in JavaScript, using safe NAPI allocation while the original Rust seal lives.
#[napi(js_name = "NativeFullChatOutput")]
pub struct NodeFullChatOutput {
    output: std::sync::Mutex<Option<crate::session::FullChatOutput>>,
}
#[napi]
impl NodeFullChatOutput {
    #[napi]
    pub fn release_json<'env>(&self, env: &'env napi::Env) -> napi::Result<napi::JsString<'env>> {
        let output = self.output.try_lock()
            .map_err(|_| error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(|| error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text| env.create_string(text)
            .map_err(|_| openmates_sdk::Error::Protocol.into())).map_err(error)
    }
    #[napi]
    pub fn discard(&self) -> napi::Result<()> {
        self.output.try_lock().map_err(|_| error(openmates_sdk::Error::Conflict.into()))?.take();
        Ok(())
    }
}

// Opaque async result: actual JS string allocation happens only in sync finish.
#[napi(js_name = "NativeChatDetailsOutput")]
pub struct NodeChatDetailsOutput {
    output: std::sync::Mutex<Option<crate::session::ChatDetailsOutput>>,
}
#[napi]
impl NodeChatDetailsOutput {
    #[napi]
    pub fn release_json<'env>(&self, env: &'env napi::Env) -> napi::Result<napi::JsString<'env>> {
        let output = self.output.try_lock()
            .map_err(|_| error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(|| error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text| env.create_string(text)
            .map_err(|_| openmates_sdk::Error::Protocol.into())).map_err(error)
    }
    #[napi]
    pub fn discard(&self) -> napi::Result<()> {
        self.output.try_lock().map_err(|_| error(openmates_sdk::Error::Conflict.into()))?.take();
        Ok(())
    }
}

// Saved updates/terminal Chat allocate only inside this guarded sync finish.
#[napi(js_name = "NativeSavedStreamOutput")]
pub struct NodeSavedStreamOutput {
    output: std::sync::Mutex<Option<crate::session::SavedStreamOutput>>,
}
#[napi]
impl NodeSavedStreamOutput {
    #[napi]
    pub fn is_terminal(&self)->napi::Result<bool> {
        let output=self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?;
        Ok(output.as_ref().ok_or_else(||error(openmates_sdk::Error::Cancelled.into()))?.is_terminal())
    }

    #[napi]
    pub fn release_json<'env>(&self, env: &'env napi::Env) -> napi::Result<napi::JsString<'env>> {
        let output=self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(||error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text|env.create_string(text).map_err(|_|openmates_sdk::Error::Protocol.into())).map_err(error)
    }
    #[napi]
    pub fn discard(&self)->napi::Result<()> {
        self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take();Ok(())
    }
}

#[napi(js_name="NativeDirectSkillOutput")]
pub struct NodeDirectSkillOutput { output:std::sync::Mutex<Option<crate::session::DirectSkillOutput>> }
#[napi]
impl NodeDirectSkillOutput {
    #[napi]
    pub fn release_json<'env>(&self, env: &'env napi::Env) -> napi::Result<napi::JsString<'env>> {
        let output=self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(||error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text|env.create_string(text).map_err(|_|openmates_sdk::Error::Protocol.into())).map_err(error)
    }
    #[napi]
    pub fn discard(&self)->napi::Result<()> {
        self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take();Ok(())
    }
}

#[napi(js_name="NativeAppsInventoryOutput")]
pub struct NodeAppsInventoryOutput { output:std::sync::Mutex<Option<crate::session::AppsInventoryOutput>> }
#[napi]
impl NodeAppsInventoryOutput {
    #[napi]
    pub fn release_json<'env>(&self,env:&'env napi::Env)->napi::Result<napi::JsString<'env>>{
        let output=self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take().ok_or_else(||error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text|env.create_string(text).map_err(|_|openmates_sdk::Error::Protocol.into())).map_err(error)
    }
    #[napi]
    pub fn discard(&self)->napi::Result<()>{self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take();Ok(())}
}

#[napi(js_name="NativeAppsInventoryOperation")]
pub struct NodeAppsInventoryOperation {prepared:std::sync::Mutex<Option<crate::session::PreparedAppsInventory>>,cancel:tokio_util::sync::CancellationToken}
#[napi]
impl NodeAppsInventoryOperation {
    #[napi(ts_return_type="Promise<NativeAppsInventoryOutput>")]
    pub fn run<'env>(&self,env:&'env napi::Env)->napi::Result<napi::bindgen_prelude::PromiseRaw<'env,NodeAppsInventoryOutput>>{
        let prepared=self.prepared.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take().ok_or_else(||error(openmates_sdk::Error::Cancelled.into()))?;
        env.spawn_future(async move{prepared.run().await.map(|output|NodeAppsInventoryOutput{output:std::sync::Mutex::new(Some(output))}).map_err(error)})
    }
    #[napi]
    pub fn cancel(&self){self.cancel.cancel();}
}

#[napi(js_name = "NativeSettingsRemindersOutput")]
pub struct NodeSettingsRemindersOutput { output: std::sync::Mutex<Option<crate::session::SettingsRemindersOutput>> }
#[napi]
impl NodeSettingsRemindersOutput {
    #[napi]
    pub fn release_json<'env>(&self, env: &'env napi::Env) -> napi::Result<napi::JsString<'env>> {
        let output = self.output.try_lock().map_err(|_| error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(|| error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text| env.create_string(text).map_err(|_| openmates_sdk::Error::Protocol.into()))
            .map_err(|error| napi::Error::new(napi::Status::GenericFailure, error.json()))
    }
    #[napi]
    pub fn discard(&self) -> napi::Result<()> {
        self.output.try_lock().map_err(|_| error(openmates_sdk::Error::Conflict.into()))?.take();
        Ok(())
    }
}

#[napi(js_name = "NativeSettingsRemindersOperation")]
pub struct NodeSettingsRemindersOperation {
    prepared: std::sync::Mutex<Option<crate::session::PreparedSettingsReminders>>,
    control: crate::session::SettingsRemindersControl,
}
impl Drop for NodeSettingsRemindersOperation { fn drop(&mut self) { self.control.cancel(); } }
#[napi]
impl NodeSettingsRemindersOperation {
    #[napi(ts_return_type = "Promise<NativeSettingsRemindersOutput>")]
    pub fn run<'env>(&self, env: &'env napi::Env) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, NodeSettingsRemindersOutput>> {
        let prepared = self.prepared.try_lock().map_err(|_| error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(|| error(openmates_sdk::Error::Cancelled.into()))?;
        env.spawn_future(async move {
            Ok(NodeSettingsRemindersOutput { output: std::sync::Mutex::new(Some(prepared.run().await
                .map_err(|error| napi::Error::new(napi::Status::GenericFailure, error.json()))?)) })
        })
    }
    #[napi]
    pub fn cancel(&self) { self.control.cancel(); }
}
