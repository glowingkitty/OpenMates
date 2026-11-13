//! Bound Workflow YAML synchronization through authenticated Project operations.
//! Keys, binding history and relay payloads never enter the CLI result/logs.
use super::*;
use crate::work::{WorkflowFileDocument, build_workflow_export};
use zeroize::Zeroizing;
mod attach;
mod requester;
pub use attach::{
    WorkflowAttachOptions, WorkflowAttachResult, WorkflowRemoteFileResult, WorkflowStorageMode,
};

#[derive(Serialize)]
pub struct WorkflowFileSaveStatus {
    pub project_id: String,
    pub status: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<&'static str>,
}
struct PrivateJson(Value);
impl std::ops::Deref for PrivateJson {
    type Target = Value;
    fn deref(&self) -> &Value {
        &self.0
    }
}
impl Drop for PrivateJson {
    fn drop(&mut self) {
        crate::model::zeroize_json(&mut self.0);
    }
}
fn relative(value: &str, folder: bool) -> Result<String> {
    if folder && matches!(value, "" | "." | "/") {
        return Ok(String::new());
    }
    if value.is_empty()
        || value.encode_utf16().count() > 2048
        || value.starts_with('/')
        || value.contains('\\')
        || value.chars().any(|c| c < ' ' || c == '\u{7f}')
        || value.split('/').any(|p| matches!(p, "" | "." | ".."))
    {
        return Err(Error::Invalid("invalid_workflow_folder"));
    }
    Ok(value.into())
}
fn file_path(binding: &Value, filename: &str) -> Result<String> {
    let folder = relative(
        binding["folder_path"].as_str().ok_or(Error::Protocol)?,
        true,
    )?;
    let path = match binding.get("file_path") {
        None | Some(Value::Null) => format!(
            "{}{}",
            if folder.is_empty() {
                String::new()
            } else {
                format!("{folder}/")
            },
            filename
        ),
        Some(Value::String(path)) => path.clone(),
        _ => return Err(Error::Protocol),
    };
    if relative(&path, false)? != path
        || !path.ends_with(".workflow.yml")
        || path.rsplit_once('/').map(|(p, _)| p).unwrap_or("") != folder
    {
        return Err(Error::Invalid("workflow_file_path_outside_selected_folder"));
    }
    Ok(path)
}
/// Whole-file replacement diff from `old` to `next` (shared with the hosted writer).
pub(super) fn replacement(path: &str, old: &str, next: &str) -> String {
    fn rows(value: &str, prefix: char) -> String {
        value
            .split_inclusive('\n')
            .map(|line| {
                if let Some(line) = line.strip_suffix('\n') {
                    format!("{prefix}{line}\n")
                } else {
                    format!("{prefix}{line}\n\\ No newline at end of file\n")
                }
            })
            .collect()
    }
    format!(
        "--- a/{path}\n+++ b/{path}\n@@ -{},{} +{},{} @@\n{}{}",
        usize::from(!old.is_empty()),
        old.split_inclusive('\n').count(),
        usize::from(!next.is_empty()),
        next.split_inclusive('\n').count(),
        rows(old, '-'),
        rows(next, '+')
    )
}
fn mutation(binding: &Value, path: &str, content: &str) -> Result<PrivateJson> {
    let operation = uuid::Uuid::new_v4().to_string();
    let value = PrivateJson(if binding.get("base_hash").is_none() {
        if binding.get("saved_content").is_some() {
            return Err(Error::Invalid("workflow_file_binding_incomplete"));
        }
        json!({"operation":"create_file","operation_id":operation,"path":path,"expected_base":null,"content":content})
    } else {
        let base = string(binding, "base_hash")?;
        let old = binding["saved_content"]
            .as_str()
            .ok_or(Error::Invalid("workflow_file_binding_hash_mismatch"))?;
        if base.len() != 64
            || !base
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            || hash(old) != base
        {
            return Err(Error::Invalid("workflow_file_binding_hash_mismatch"));
        }
        json!({"operation":"update_file","operation_id":operation,"path":path,"expected_base":base,"patch":replacement(path,old,content)})
    });
    if value["content"]
        .as_str()
        .or(value["patch"].as_str())
        .ok_or(Error::Protocol)?
        .len()
        > 200 * 1024
    {
        return Err(Error::Invalid("file_mutation_too_large"));
    }
    Ok(value)
}
/// `projectFileMutationDigest`: keyed proposal commitment (shared with the hosted writer).
pub(super) fn commitment(key: &[u8; 32], project: &str, chat: &str, mutation: &Value) -> Result<String> {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    let mut tuple = PrivateJson(json!([
        "openmates-project-file-proposal-v1",
        project,
        chat,
        mutation["operation"],
        mutation["operation_id"],
        mutation["path"],
        mutation["expected_base"],
        mutation["content"],
        mutation["patch"]
    ]));
    // A hosted rename (P11) also commits its target, so an approval of a -> b
    // cannot authorize a -> c. Other operations carry no `new_path`, which
    // keeps their nine-field tuple byte-identical to the web executor.
    if let (Some(target), Some(fields)) = (mutation.get("new_path"), tuple.0.as_array_mut()) {
        fields.push(target.clone());
    }
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(key).map_err(|_| Error::Crypto)?;
    let message = Zeroizing::new(serde_json::to_string(&tuple.0)?);
    mac.update(message.as_bytes());
    Ok(mac
        .finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}
fn classify(code: &str) -> (&'static str, &'static str) {
    match code {
        "source_offline" => ("pending", "source_offline"),
        "protocol_timeout" => ("pending", "protocol_timeout"),
        "file_changed" => ("conflict", "file_changed"),
        "file_exists" => ("conflict", "file_exists"),
        "write_approval_required" => ("pending", "write_approval_required"),
        "write_policy_required" => ("failed", "write_policy_required"),
        "operation_conflict" => ("conflict", "operation_conflict"),
        "source_session_changed" => ("failed", "source_session_changed"),
        "protected_path" => ("failed", "protected_path"),
        "invalid_path" => ("failed", "invalid_path"),
        "target_exists" => ("failed", "target_exists"),
        "invalid_patch" => ("failed", "invalid_patch"),
        "operation_unconfirmed" => ("failed", "operation_unconfirmed"),
        "write_authorization_denied" => ("failed", "write_authorization_denied"),
        _ => ("failed", "workflow_file_write_failed"),
    }
}
impl Projects<'_> {
    fn workflow_active(&self) -> Result<()> {
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        self.backend.verify_private_operation()
    }
    async fn workflow_row(&mut self, id: &str) -> Result<PrivateJson> {
        let route = self.path(&format!("/v1/workflows/{}", uuid(id)?), &[]);
        self.workflow_active()?;
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        self.workflow_active()?;
        if data["workflow"]["id"] != id {
            return Err(Error::Forbidden);
        }
        let mut row = data["workflow"].clone();
        if row["graph"].is_object() && row["graph"]["edges"].is_null() {
            row["graph"]["edges"] = json!([]);
        }
        Ok(PrivateJson(row))
    }
    async fn workflow_execute_mutation<A, F>(
        &mut self,
        project: &ResolvedProject,
        source: &Value,
        chat: &str,
        path: &str,
        mutation: &Value,
        approve: &mut A,
    ) -> Result<PrivateJson>
    where
        A: FnMut(String) -> F,
        F: std::future::Future<Output = Result<bool>>,
    {
        self.workflow_active()?;
        let project_id = string(&project.raw, "project_id")?;
        let route = self.path(&format!("/v1/projects/{project_id}/settings"), &[]);
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        self.workflow_active()?;
        let settings = response["settings"].as_object().ok_or(Error::Protocol)?;
        let mode = settings.get("write_mode").and_then(Value::as_str);
        match mode {
            Some("apply_and_show") => {}
            Some("always_ask") => {
                let accepted = tokio::select! {biased;
                    _=self.operation_cancel.cancelled()=>return Err(Error::Cancelled),
                    value=approve(path.to_owned())=>value?,
                };
                if !accepted {
                    return Ok(PrivateJson(
                        json!({"status":"pending","error":"write_approval_required"}),
                    ));
                }
            }
            _ => {
                return Ok(PrivateJson(
                    json!({"status":"failed","error":"write_policy_required"}),
                ));
            }
        }
        self.workflow_active()?;
        let digest = commitment(&project.key, project_id, chat, mutation)?;
        if mode == Some("always_ask") {
            let route = self.path(&format!("/v1/projects/{project_id}/write-approvals"), &[]);
            self.backend.request(Method::POST,&route,Some(json!({"chat_id":chat,"operation_id":mutation["operation_id"],"proposal_digest":digest})),None).await?;
        }
        self.workflow_active()?;
        self.workflow_remote_write(project, source, chat, mutation, &digest)
            .await
    }
    /// Synchronize existing encrypted bindings only, never create an attachment.
    /// Serializer is a plaintext formatting adapter. Approval supplies user
    /// intent only; actual focus/policy/authorization remain server enforced.
    pub async fn sync_workflow_files<S, A, F>(
        &mut self,
        id: &str,
        expected_version: &str,
        source_chat: Option<&str>,
        serialize: S,
        mut approve: A,
    ) -> Result<Vec<WorkflowFileSaveStatus>>
    where
        S: FnOnce(&WorkflowFileDocument) -> Result<(String, String)>,
        A: FnMut(String) -> F,
        F: std::future::Future<Output = Result<bool>>,
    {
        if matches!(&self.backend, Backend::ApiKey(_)) {
            return Err(Error::Unavailable {
                code: "workflow_update_requires_cookie_session",
                reason: "WORKFLOW_BOUND_FILES_REQUIRE_COOKIE_SESSION",
            });
        }
        self.workflow_active()?;
        self.scope()?;
        let workflow = self.workflow_row(id).await?;
        if string(&workflow, "current_version_id")? != expected_version {
            return Err(Error::Conflict);
        }
        let mut serialize = Some(serialize);
        let mut formatted: Option<(String, Zeroizing<String>)> = None;
        let chat = source_chat.or(workflow["source_chat_id"].as_str());
        let projects = self.list_resolved(None).await?;
        let mut results = vec![];
        for project in projects {
            self.workflow_active()?;
            let project_id = string(&project.raw, "project_id")?.to_owned();
            let route = self.path(&format!("/v1/projects/{project_id}/items"), &[]);
            let response = self
                .backend
                .request(Method::GET, &route, None, None)
                .await?;
            self.workflow_active()?;
            for item in response["items"].as_array().ok_or(Error::Protocol)? {
                if item["item_type"] != "workflow" {
                    continue;
                }
                super::items::child_scope(item, &project, self.filters.team_id.as_deref())?;
                let target = Zeroizing::new(super::items::optional_text(
                    item,
                    "target_id_encrypted",
                    &project.key,
                )?);
                if target.as_str() != id {
                    continue;
                }
                if item
                    .get("target_id_hash")
                    .is_some_and(|v| !v.is_null() && *v != json!(hash(&target)))
                {
                    return Err(Error::Forbidden);
                }
                let text = Zeroizing::new(super::items::optional_text(
                    item,
                    "encrypted_metadata",
                    &project.key,
                )?);
                let mut metadata = PrivateJson(if text.is_empty() {
                    json!({})
                } else {
                    serde_json::from_str(&text).map_err(|_| Error::Crypto)?
                });
                if !metadata.0.is_object() {
                    return Err(Error::Protocol);
                }
                let Some(binding) = metadata.0.get("remote_workflow_file").cloned() else {
                    continue;
                };
                let mut binding = PrivateJson(binding);
                if !binding.0.is_object() {
                    return Err(Error::Protocol);
                }
                let sources = self.list_sources_raw(&project_id).await?;
                let source = sources
                    .iter()
                    .find(|row| row["source_id"] == binding.0["source_id"]);
                let focus = if let Some(chat) = chat {
                    let route = self.path(
                        "/v1/projects/focus/current",
                        &[("chat_id".into(), chat.into())],
                    );
                    self.backend
                        .request(Method::GET, &route, None, None)
                        .await?["focus"]
                        .clone()
                } else {
                    Value::Null
                };
                self.workflow_active()?;
                let (status, error) = if source.is_none() {
                    ("pending", Some("source_selection_required"))
                } else if chat.is_none() || focus["project_id"] != project_id {
                    ("pending", Some("project_focus_required"))
                } else {
                    if formatted.is_none() {
                        let (name, content) = serialize.take().ok_or(Error::Conflict)?(
                            &build_workflow_export(&workflow)?,
                        )?;
                        formatted = Some((name, Zeroizing::new(content)));
                    }
                    let (filename, content) = formatted.as_ref().ok_or(Error::Conflict)?;
                    self.persist_workflow_binding(
                        WorkflowBindingWrite {
                            id,
                            expected_version,
                            project: &project,
                            source: source.ok_or(Error::Protocol)?,
                            chat: chat.ok_or(Error::Protocol)?,
                            filename,
                            content,
                        },
                        &mut binding.0,
                        &mut approve,
                    )
                    .await?
                };
                self.workflow_active()?;
                metadata.0["remote_workflow_file"] = std::mem::take(&mut binding.0);
                metadata.0["remote_file_status"] = json!(status);
                if let Some(error) = error {
                    metadata.0["remote_file_error"] = json!(error)
                } else {
                    metadata
                        .0
                        .as_object_mut()
                        .ok_or(Error::Protocol)?
                        .remove("remote_file_error");
                }
                let encoded = Zeroizing::new(serde_json::to_string(&metadata.0)?);
                let encrypted = crypto::server_fields::encrypt_text(&encoded, &project.key, &[])?;
                let item_id =
                    super::sources::source_patch_segment(string(item, "project_item_id")?)?;
                let route = self.path(&format!("/v1/projects/{project_id}/items/{item_id}"), &[]);
                // A failed/unknown metadata write is an error, never a reported save.
                self.backend
                    .request(
                        Method::PATCH,
                        &route,
                        Some(json!({"encrypted_metadata":encrypted,"updated_at":now()})),
                        None,
                    )
                    .await?;
                self.workflow_active()?;
                results.push(WorkflowFileSaveStatus {
                    project_id: project_id.clone(),
                    status,
                    error,
                });
            }
        }
        Ok(results)
    }
}

/// One bound YAML write: the caller has already selected the source and
/// checked Project focus. Shared by binding sync and add-to-project.
struct WorkflowBindingWrite<'a> {
    id: &'a str,
    expected_version: &'a str,
    project: &'a ResolvedProject,
    source: &'a Value,
    chat: &'a str,
    filename: &'a str,
    content: &'a str,
}
impl Projects<'_> {
    async fn persist_workflow_binding<A, F>(
        &mut self,
        w: WorkflowBindingWrite<'_>,
        binding: &mut Value,
        approve: &mut A,
    ) -> Result<(&'static str, Option<&'static str>)>
    where
        A: FnMut(String) -> F,
        F: std::future::Future<Output = Result<bool>>,
    {
        let status;
        let mut error = None;
        let path = file_path(binding, w.filename)?;
        if self.workflow_row(w.id).await?["current_version_id"] != w.expected_version {
            status = "conflict";
            error = Some("workflow_version_changed")
        } else {
            let mutation = mutation(binding, &path, w.content)?;
            let written = self
                .workflow_execute_mutation(w.project, w.source, w.chat, &path, &mutation.0, approve)
                .await;
            match written {
                Ok(written) => {
                    let expected_hash = hash(w.content);
                    let applied = written["status"] == "completed"
                        || (written["path"] == path
                            && written["operation"] == mutation.0["operation"]
                            && written["operation_id"] == mutation.0["operation_id"]
                            && written["after_hash"] == expected_hash);
                    if applied {
                        match self.workflow_row(w.id).await {
                            Ok(current) => {
                                binding["file_path"] = json!(path);
                                binding["base_hash"] = json!(expected_hash);
                                binding["saved_content"] = json!(w.content);
                                binding["workflow_version_id"] = json!(w.expected_version);
                                if current["current_version_id"] == w.expected_version {
                                    status = "saved"
                                } else {
                                    status = "conflict";
                                    error = Some("workflow_version_changed")
                                }
                            }
                            Err(Error::Cancelled) => return Err(Error::Cancelled),
                            Err(_) => {
                                status = "failed";
                                error = Some("workflow_file_write_failed")
                            }
                        }
                    } else {
                        status = match written["status"].as_str() {
                            Some("conflict") => "conflict",
                            Some("failed") => "failed",
                            _ => "pending",
                        };
                        error = written["error"].as_str().map(|code| classify(code).1);
                    }
                }
                Err(Error::Cancelled) => return Err(Error::Cancelled),
                Err(error_value) => {
                    let code = match error_value {
                        Error::Conflict => "operation_conflict",
                        Error::Unavailable { code, .. } => code,
                        _ => "workflow_file_write_failed",
                    };
                    let pair = classify(code);
                    status = pair.0;
                    error = Some(pair.1);
                }
            }
        }
        Ok((status, error))
    }
}

#[cfg(test)]
mod tests;
