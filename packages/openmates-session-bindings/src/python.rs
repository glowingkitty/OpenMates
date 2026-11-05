use crate::{BindingError, SessionBridge};
use pyo3::{exceptions::PyRuntimeError, prelude::*};
fn error(error: BindingError) -> PyErr {
    PyRuntimeError::new_err(error.json())
}
#[pyfunction]
fn reconstruct_embed_version(input_json: String) -> PyResult<String> {
    crate::reconstruct_embed_version_json(input_json).map_err(error)
}
#[pyfunction]
fn privacy(input_json: String) -> PyResult<String> {
    crate::privacy_json(input_json).map_err(error)
}
#[pyfunction]
fn task_order(input_json: String) -> PyResult<String> {
    crate::sort_tasks_json(input_json).map_err(error)
}
#[pyclass(name = "NativeInitialSyncOperation", module = "openmates._native")]
struct PythonInitialSyncOperation {
    prepared: std::sync::Mutex<Option<crate::PreparedInitialSyncOperation>>,
    control: crate::InitialSyncOperationControl,
}
impl Drop for PythonInitialSyncOperation { fn drop(&mut self) { self.control.cancel(); } }
#[pymethods]
impl PythonInitialSyncOperation {
    fn run<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.prepared.try_lock().map_err(|_| error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(|| error(openmates_sdk::Error::Conflict.into()))?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            Ok(PythonInitialSyncMetadata { value: prepared.run().await.map_err(error)? })
        })
    }
    fn cancel(&self) { self.control.cancel(); }
}
#[pyclass(name = "NativeInitialSyncMetadata", module = "openmates._native")]
struct PythonInitialSyncMetadata { value: crate::InitialSyncMetadata }
#[pymethods]
impl PythonInitialSyncMetadata {
    fn received_metadata_count<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let value = self.value.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move { value.received_metadata_count().await.map_err(error) })
    }
    fn cancel(&self) { self.value.cancel(); }
}
#[pyclass(name = "NativeSessionClient", module = "openmates._native")]
struct PythonSessionClient {
    bridge: SessionBridge,
}
impl Drop for PythonSessionClient {
    fn drop(&mut self) {
        let _ = self.bridge.cancel();
    }
}
#[pymethods]
impl PythonSessionClient {
    fn initial_sync_open(&self, id: String) -> PyResult<PythonInitialSyncOperation> {
        let prepared = self.bridge.prepare_initial_sync(id).map_err(error)?;
        let control = prepared.control();
        Ok(PythonInitialSyncOperation { prepared: std::sync::Mutex::new(Some(prepared)), control })
    }
    fn account_reminders_open(&self) -> PyResult<PythonSettingsRemindersOperation> {
        let prepared = self.bridge.prepare_account_reminders().map_err(error)?;
        let control = prepared.control();
        Ok(PythonSettingsRemindersOperation { prepared: std::sync::Mutex::new(Some(prepared)), control })
    }
    fn first_page_open<'py>(&self,py:Python<'py>,id:String,include_secrets:bool,include_private_output:bool)->PyResult<Bound<'py,PyAny>>{
        let prepared = self.bridge.capture_first_page_open(id,include_secrets,include_private_output);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn first_page_next<'py>(&self,py:Python<'py>,id:String)->PyResult<Bound<'py,PyAny>>{
        let bridge=self.bridge.clone();pyo3_async_runtimes::tokio::future_into_py(py,async move{bridge.first_page_next(id).await.map_err(error)})
    }
    fn first_page_receipt(&self,id:String,stage_id:String,receipt:String)->PyResult<()>{self.bridge.first_page_receipt(id,stage_id,receipt).map_err(error)}
    fn first_page_capacity(&self,id:String,stage_id:String,accepted:bool)->PyResult<()>{self.bridge.first_page_capacity(id,stage_id,accepted).map_err(error)}
    fn first_page_close(&self,id:String)->PyResult<()>{self.bridge.first_page_close(id).map_err(error)}
    fn cache_chat_stage<'py>(&self, py: Python<'py>, id: String, include_secrets: bool) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_cache_chat_stage(id,include_secrets);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn cache_chat_commit<'py>(&self, py: Python<'py>, stage_id: String, receipt: String) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move { bridge.cache_chat_commit(stage_id, receipt).await.map_err(error) })
    }
    fn cache_chat_discard(&self, stage_id: String) -> PyResult<()> {
        self.bridge.cache_chat_discard(stage_id).map_err(error)
    }
    #[pyo3(signature=(id,include_secrets,selected=None))]
    fn chat_monitor_stage_prefer_cache<'py>(&self, py: Python<'py>, id: String, include_secrets: bool, selected: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move { bridge.chat_monitor_stage_prefer_cache(id, selected, include_secrets).await.map_err(error) })
    }
    fn embeds_share_url<'py>(&self,py:Python<'py>,id:String,expires_json:String,password:String)->PyResult<Bound<'py,PyAny>>{
        let prepared = self.bridge.capture_embeds_share_url(id,expires_json,password);
        pyo3_async_runtimes::tokio::future_into_py(py, async move { prepared.await.map_err(error) })
    }
    fn embeds_version_content<'py>(&self,py:Python<'py>,id:String,version_json:String)->PyResult<Bound<'py,PyAny>>{
        let prepared = self.bridge.capture_embeds_version_content(id,version_json);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn drafts_list_cached<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_drafts_list_cached();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn drafts_list<'py>(&self, py: Python<'py>, options: String) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_drafts_list(options);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn drafts_get<'py>(
        &self,
        py: Python<'py>,
        id: String,
        options: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_drafts_get(id,options);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn drafts_sync<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_drafts_sync();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }

    fn chat_monitor_validate<'py>(
        &self,
        py: Python<'py>,
        id: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge.chat_monitor_validate(id).await.map_err(error)
        })
    }
    fn completion_recovery_discard(&self, id: String) -> PyResult<()> {
        self.bridge.completion_recovery_discard(id).map_err(error)
    }
    fn chat_monitor_access_denial(&self, id: String) -> PyResult<String> {
        self.bridge.chat_monitor_access_denial(id).map_err(error)
    }
    fn chat_monitor_open<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_chat_monitor_open();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn chat_monitor_next<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge.chat_monitor_next(id).await.map_err(error)
        })
    }
    #[pyo3(signature=(id,include_secrets,selected=None))]
    fn chat_monitor_stage<'py>(
        &self,
        py: Python<'py>,
        id: String,
        include_secrets: bool,
        selected: Option<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge
                .chat_monitor_stage(id, selected, include_secrets)
                .await
                .map_err(error)
        })
    }
    fn chat_monitor_commit<'py>(
        &self,
        py: Python<'py>,
        id: String,
        stage_id: String,
        receipt: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge
                .chat_monitor_commit(id, stage_id, receipt)
                .await
                .map_err(error)
        })
    }
    fn chat_monitor_discard(&self, id: String, stage_id: String) -> PyResult<()> {
        self.bridge
            .chat_monitor_discard(id, stage_id)
            .map_err(error)
    }
    fn chat_monitor_close(&self, id: String) -> PyResult<()> {
        self.bridge.chat_monitor_close(id).map_err(error)
    }
    fn completion_recovery_enable<'py>(
        &self,
        py: Python<'py>,
        enabled: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_completion_recovery_enable(enabled);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn completion_recovery_jobs<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_completion_recovery_discover(None);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn completion_recovery_jobs_for_chat<'py>(
        &self, py: Python<'py>, chat_id: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_completion_recovery_discover(Some(chat_id));
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn completion_recovery_stage<'py>(
        &self,
        py: Python<'py>,
        id: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge.completion_recovery_stage(id).await.map_err(error)
        })
    }
    fn completion_recovery_resume<'py>(
        &self,
        py: Python<'py>,
        checkpoint: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge
                .completion_recovery_resume(checkpoint)
                .await
                .map_err(error)
        })
    }
    fn completion_recovery_commit<'py>(
        &self,
        py: Python<'py>,
        id: String,
        receipt: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge
                .completion_recovery_commit(id, receipt)
                .await
                .map_err(error)
        })
    }
    fn project_task_watch_open<'py>(
        &self,
        py: Python<'py>,
        project: String,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_project_task_watch_open(project,input_json,filters_json);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn project_task_watch_next<'py>(
        &self,
        py: Python<'py>,
        id: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge.project_task_watch_next(id).await.map_err(error)
        })
    }
    fn project_task_watch_commit<'py>(
        &self,
        py: Python<'py>,
        id: String,
        receipt_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge
                .project_task_watch_commit(id, receipt_json)
                .await
                .map_err(error)
        })
    }
    fn project_task_watch_close(&self, id: String) -> PyResult<()> {
        self.bridge.project_task_watch_close(id).map_err(error)
    }
    #[new]
    fn new(options_json: String) -> PyResult<Self> {
        Ok(Self {
            bridge: SessionBridge::with_identity(&options_json, openmates_sdk::ClientIdentity::Pip)
                .map_err(error)?,
        })
    }
    #[pyo3(signature=(email,password,tfa=None,stay_logged_in=false))]
    fn login_password<'py>(
        &self,
        py: Python<'py>,
        email: String,
        password: String,
        tfa: Option<String>,
        stay_logged_in: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.prepare_login_password(email, password, tfa, openmates_sdk::PasswordLoginOptions { stay_logged_in }).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move { prepared.run_string().await.map_err(error) })
    }
    fn import_session<'py>(
        &self,
        py: Python<'py>,
        session_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.prepare_import_session(session_json).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move { prepared.run_unit().await.map_err(error) })
    }
    fn export_session<'py>(
        &self,
        py: Python<'py>,
        include_secrets: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge.export_session(include_secrets).await.map_err(error)
        })
    }
    fn validate_session<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge.validate_session().await.map_err(error)
        })
    }
    fn apps_inventory_open(&self)->PyResult<PythonAppsInventoryOperation>{
        let prepared=self.bridge.prepare_apps_inventory().map_err(error)?;
        let cancel=prepared.cancellation_request();
        Ok(PythonAppsInventoryOperation{prepared:std::sync::Mutex::new(Some(prepared)),cancel})
    }
    fn apps_inventory_prepare<'py>(&self,py:Python<'py>)->PyResult<Bound<'py,PyAny>>{
        let prepared=self.bridge.capture_apps_inventory_prepare();
        pyo3_async_runtimes::tokio::future_into_py(py,async move{prepared.await.map(|output|PythonAppsInventoryOutput{output:std::sync::Mutex::new(Some(output))}).map_err(error)})
    }
    fn list<'py>(&self, py: Python<'py>, workspace: String) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge.list(workspace).await.map_err(error)
        })
    }
    fn chat_details_prepare<'py>(&self, py: Python<'py>, id: String, options_json: String) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_chat_details_prepare(id,options_json);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map(|output| PythonChatDetailsOutput { output: std::sync::Mutex::new(Some(output)) }).map_err(error)
        })
    }
    fn open_chat_prepare<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_full_chat_read_prepare(id);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map(|output| PythonFullChatOutput { output: std::sync::Mutex::new(Some(output)) }).map_err(error)
        })
    }
    fn chat_message_window<'py>(&self, py: Python<'py>, id: String, options: String) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_chat_message_window(id,options);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn saved_chat_read<'py>(&self, py: Python<'py>, id: String, options: String) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_saved_chat_read(id,options);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn saved_chat_exact_message<'py>(&self, py: Python<'py>, id: String, options: String) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_saved_chat_exact_message(id,options);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    #[pyo3(signature=(id=None))]
    fn set_team<'py>(&self, py: Python<'py>, id: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.prepare_set_team(id).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move { prepared.run_unit().await.map_err(error) })
    }
    #[pyo3(signature=(text,chat_id=None))]
    fn start_send<'py>(
        &self,
        py: Python<'py>,
        text: String,
        chat_id: Option<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.capture_start_saved_stream(text,chat_id);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.await.map_err(error)
        })
    }
    fn run_skill_prepare<'py>(&self,py:Python<'py>,app:String,skill:String,input:String)->PyResult<Bound<'py,PyAny>> {
        let prepared=self.bridge.run_skill_prepare(app,skill,input);
        pyo3_async_runtimes::tokio::future_into_py(py,async move{
            prepared.await
                .map(|output|PythonDirectSkillOutput{output:std::sync::Mutex::new(Some(output))}).map_err(error)
        })
    }
    fn next_event_prepare<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let bridge=self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py,async move {
            bridge.next_event_prepare(id).await
                .map(|output|PythonSavedStreamOutput{output:std::sync::Mutex::new(Some(output))})
                .map_err(error)
        })
    }
    fn next_event<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge.next_anonymous_event(id).await.map_err(error)
        })
    }
    fn tasks_list<'py>(
        &self,
        py: Python<'py>,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Parse before spawning so no malformed input can start a request.
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::TasksList(filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn tasks_show<'py>(
        &self,
        py: Python<'py>,
        id: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Parse before spawning so no malformed input can start a request.
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::TaskShow(id, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn tasks_create<'py>(
        &self,
        py: Python<'py>,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Parse before spawning so no malformed input can start a request.
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::TaskCreate(input, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn tasks_update<'py>(
        &self,
        py: Python<'py>,
        id: String,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Parse before spawning so no malformed input can start a request.
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::TaskUpdate(id, input, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn tasks_delete<'py>(
        &self,
        py: Python<'py>,
        id: String,
        confirmed: bool,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Parse before spawning so no malformed input can start a request.
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::TaskDelete(id, confirmed, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn projects_list<'py>(
        &self,
        py: Python<'py>,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Parse before spawning so no malformed input can start a request.
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectsList(filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn projects_show<'py>(
        &self,
        py: Python<'py>,
        id: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Parse before spawning so no malformed input can start a request.
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectShow(id, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn projects_sync_workflow_files<'py>(&self,py:Python<'py>,input_json:String,filters_json:String)->PyResult<Bound<'py,PyAny>>{
        let input=crate::session::decode_input(input_json).map_err(error)?;
        let filters=crate::session::decode_input(filters_json).map_err(error)?;
        let prepared=self.bridge.prepare_work(crate::session::WorkRequest::ProjectSyncWorkflowFiles(input,filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py,async move{prepared.run().await.map_err(error)})
    }
    fn projects_list_sources_raw<'py>(&self, py: Python<'py>, project: String, filters_json: String) -> PyResult<Bound<'py, PyAny>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectSourcesRaw(project, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move { prepared.run().await.map_err(error) })
    }
    fn projects_list_sources_decoded_names<'py>(&self, py: Python<'py>, project: String, filters_json: String) -> PyResult<Bound<'py, PyAny>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectSourceDecodedNames(project, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move { prepared.run().await.map_err(error) })
    }
    fn projects_create_source<'py>(
        &self,
        py: Python<'py>,
        project: String,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectSourceCreate(project, Box::new(input), filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn projects_update_source_capabilities<'py>(
        &self,
        py: Python<'py>,
        project: String,
        source: String,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectSourceCapabilities(project, source, input, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn projects_create<'py>(
        &self,
        py: Python<'py>,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Parse before spawning so no malformed input can start a request.
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectCreate(input, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn projects_items<'py>(
        &self,
        py: Python<'py>,
        id: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectItems(id, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn projects_unlink_item<'py>(
        &self,
        py: Python<'py>,
        id: String,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let input: crate::session::ProjectUnlinkInput =
            crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectUnlinkItem(id, input.item_type, input.target_id, input.confirmed, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn projects_update<'py>(
        &self,
        py: Python<'py>,
        id: String,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Parse before spawning so no malformed input can start a request.
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectUpdate(id, input, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn projects_delete<'py>(
        &self,
        py: Python<'py>,
        id: String,
        confirmed: bool,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Parse before spawning so no malformed input can start a request.
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::ProjectDelete(id, confirmed, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn plans_list<'py>(
        &self,
        py: Python<'py>,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::PlansList(filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn plans_show<'py>(
        &self,
        py: Python<'py>,
        id: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::PlanShow(id, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn plans_create<'py>(
        &self,
        py: Python<'py>,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::PlanCreate(Box::new(input), filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn plans_update<'py>(
        &self,
        py: Python<'py>,
        id: String,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::PlanUpdate(id, Box::new(input), filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn plans_delete<'py>(
        &self,
        py: Python<'py>,
        id: String,
        confirmed: bool,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::PlanDelete(id, confirmed, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn workflows_list<'py>(
        &self,
        py: Python<'py>,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowsList(filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn workflows_show<'py>(
        &self,
        py: Python<'py>,
        id: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowShow(id, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn workflows_create<'py>(
        &self,
        py: Python<'py>,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowCreate(Box::new(input), filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn workflows_update<'py>(
        &self,
        py: Python<'py>,
        id: String,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowUpdate(id, input, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn workflows_delete<'py>(
        &self,
        py: Python<'py>,
        id: String,
        confirmed: bool,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowDelete(id, confirmed, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn workflows_run<'py>(
        &self,
        py: Python<'py>,
        id: String,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowRun(id, input, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn workflows_run_detail<'py>(
        &self,
        py: Python<'py>,
        id: String,
        run: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowRunDetail(id, run, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn workflows_wait<'py>(
        &self,
        py: Python<'py>,
        id: String,
        run: String,
        input_json: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let input = crate::session::decode_input(input_json).map_err(error)?;
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowWait(id, run, input, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn workflows_cancel_run<'py>(
        &self,
        py: Python<'py>,
        id: String,
        run: String,
        filters_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let filters = crate::session::decode_input(filters_json).map_err(error)?;
        let prepared = self.bridge.prepare_work(crate::session::WorkRequest::WorkflowCancelRun(id, run, filters)).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            prepared.run().await.map_err(error)
        })
    }
    fn cancel(&self) -> PyResult<()> {
        self.bridge.cancel().map_err(error)
    }
    fn start_anonymous<'py>(
        &self,
        py: Python<'py>,
        anonymous_id: String,
        text: String,
        options_json: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let bridge = self.bridge.clone();
        let options = crate::session::anonymous::options(options_json).map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            bridge
                .start_anonymous(anonymous_id, text, options)
                .await
                .map_err(error)
        })
    }
    fn cancel_stream(&self, id: String) -> PyResult<()> {
        self.bridge.cancel_stream(id).map_err(error)
    }
    fn consent(&self, request_id: String, approved: Vec<String>) -> PyResult<()> {
        self.bridge.consent(request_id, approved).map_err(error)
    }
    fn logout<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.prepare_logout().map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move { prepared.run_unit().await.map_err(error) })
    }
    fn close<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.bridge.prepare_close().map_err(error)?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move { prepared.run().await.map_err(error) })
    }
}
#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PythonSessionClient>()?;
    module.add_class::<PythonInitialSyncOperation>()?;
    module.add_class::<PythonInitialSyncMetadata>()?;
    module.add_class::<PythonSettingsRemindersOutput>()?;
    module.add_class::<PythonSettingsRemindersOperation>()?;
    crate::python_api_key::register(module)?;
    crate::python_remote_crypto::register(module)?;
    crate::python_metadata_ephemeral::register(module)?;
    module.add_function(wrap_pyfunction!(task_order, module)?)?;
    module.add_function(wrap_pyfunction!(privacy, module)?)?;
    module.add_function(wrap_pyfunction!(reconstruct_embed_version, module)?)?;
    Ok(())
}

// Internal opaque result crosses the future queue without exposing plaintext.
#[pyclass(name = "NativeFullChatOutput")]
struct PythonFullChatOutput {
    output: std::sync::Mutex<Option<crate::session::FullChatOutput>>,
}
#[pymethods]
impl PythonFullChatOutput {
    fn release_json<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, pyo3::types::PyString>> {
        let output = self.output.try_lock()
            .map_err(|_| error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(|| error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text| Ok(pyo3::types::PyString::new(py, text))).map_err(error)
    }
    fn discard(&self) -> PyResult<()> {
        self.output.try_lock().map_err(|_| error(openmates_sdk::Error::Conflict.into()))?.take();
        Ok(())
    }
}

#[pyclass(name = "NativeChatDetailsOutput")]
struct PythonChatDetailsOutput {
    output: std::sync::Mutex<Option<crate::session::ChatDetailsOutput>>,
}
#[pymethods]
impl PythonChatDetailsOutput {
    fn release_json<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, pyo3::types::PyString>> {
        let output = self.output.try_lock()
            .map_err(|_| error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(|| error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text| Ok(pyo3::types::PyString::new(py, text))).map_err(error)
    }
    fn discard(&self) -> PyResult<()> {
        self.output.try_lock().map_err(|_| error(openmates_sdk::Error::Conflict.into()))?.take();
        Ok(())
    }
}

#[pyclass(name = "NativeSavedStreamOutput")]
struct PythonSavedStreamOutput {
    output:std::sync::Mutex<Option<crate::session::SavedStreamOutput>>,
}
#[pymethods]
impl PythonSavedStreamOutput {
    fn is_terminal(&self)->PyResult<bool> {
        let output=self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?;
        Ok(output.as_ref().ok_or_else(||error(openmates_sdk::Error::Cancelled.into()))?.is_terminal())
    }

    fn release_json<'py>(&self,py:Python<'py>)->PyResult<Bound<'py,pyo3::types::PyString>> {
        let output=self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(||error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text|Ok(pyo3::types::PyString::new(py,text))).map_err(error)
    }
    fn discard(&self)->PyResult<()> {
        self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take();Ok(())
    }
}

#[pyclass(name="NativeDirectSkillOutput")]
struct PythonDirectSkillOutput { output:std::sync::Mutex<Option<crate::session::DirectSkillOutput>> }
#[pymethods]
impl PythonDirectSkillOutput {
    fn release_json<'py>(&self,py:Python<'py>)->PyResult<Bound<'py,pyo3::types::PyString>> {
        let output=self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(||error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text|Ok(pyo3::types::PyString::new(py,text))).map_err(error)
    }
    fn discard(&self)->PyResult<()> {
        self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take();Ok(())
    }
}

#[pyclass(name="NativeAppsInventoryOutput")]
struct PythonAppsInventoryOutput { output:std::sync::Mutex<Option<crate::session::AppsInventoryOutput>> }
#[pymethods]
impl PythonAppsInventoryOutput {
    fn release_json<'py>(&self,py:Python<'py>)->PyResult<Bound<'py,pyo3::types::PyString>>{
        let output=self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take().ok_or_else(||error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text|Ok(pyo3::types::PyString::new(py,text))).map_err(error)
    }
    fn discard(&self)->PyResult<()>{self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take();Ok(())}
}

#[pyclass(name="NativeAppsInventoryOperation")]
struct PythonAppsInventoryOperation {prepared:std::sync::Mutex<Option<crate::session::PreparedAppsInventory>>,cancel:tokio_util::sync::CancellationToken}
#[pymethods]
impl PythonAppsInventoryOperation {
    fn run<'py>(&self,py:Python<'py>)->PyResult<Bound<'py,PyAny>>{
        let prepared=self.prepared.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take().ok_or_else(||error(openmates_sdk::Error::Cancelled.into()))?;
        pyo3_async_runtimes::tokio::future_into_py(py,async move{prepared.run().await.map(|output|PythonAppsInventoryOutput{output:std::sync::Mutex::new(Some(output))}).map_err(error)})
    }
    fn cancel(&self){self.cancel.cancel();}
}

#[pyclass(name = "NativeSettingsRemindersOutput", module = "openmates._native")]
struct PythonSettingsRemindersOutput { output: std::sync::Mutex<Option<crate::session::SettingsRemindersOutput>> }
#[pymethods]
impl PythonSettingsRemindersOutput {
    fn release_json<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, pyo3::types::PyString>> {
        let output = self.output.try_lock().map_err(|_| error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(|| error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text| Ok(pyo3::types::PyString::new(py, text)))
            .map_err(|error| pyo3::exceptions::PyRuntimeError::new_err(error.json()))
    }
    fn discard(&self) -> PyResult<()> {
        self.output.try_lock().map_err(|_| error(openmates_sdk::Error::Conflict.into()))?.take();
        Ok(())
    }
}

#[pyclass(name = "NativeSettingsRemindersOperation", module = "openmates._native")]
struct PythonSettingsRemindersOperation {
    prepared: std::sync::Mutex<Option<crate::session::PreparedSettingsReminders>>,
    control: crate::session::SettingsRemindersControl,
}
impl Drop for PythonSettingsRemindersOperation { fn drop(&mut self) { self.control.cancel(); } }
#[pymethods]
impl PythonSettingsRemindersOperation {
    fn run<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let prepared = self.prepared.try_lock().map_err(|_| error(openmates_sdk::Error::Conflict.into()))?
            .take().ok_or_else(|| error(openmates_sdk::Error::Cancelled.into()))?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            Ok(PythonSettingsRemindersOutput { output: std::sync::Mutex::new(Some(prepared.run().await
                .map_err(|error| pyo3::exceptions::PyRuntimeError::new_err(error.json()))?)) })
        })
    }
    fn cancel(&self) { self.control.cancel(); }
}
