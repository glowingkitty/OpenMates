//! Link a Workflow to a Project and optionally save its bound YAML file
//! (legacy CLI `workflows <id> add-to-project <project-id>`). The Project link
//! is encrypted with the Project key; the remote write reuses the bound-file
//! path (policy, approval, focus and authorization stay server enforced).
use super::*;

/// Where the Project link keeps the Workflow (legacy `targetMode`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WorkflowStorageMode {
    SaveOnlyInOpenMates,
    RemoteRepoCopy,
    RemoteCacheCopy,
}
impl WorkflowStorageMode {
    fn wire(self) -> &'static str {
        match self {
            Self::SaveOnlyInOpenMates => "save_only_in_openmates",
            Self::RemoteRepoCopy => "store_on_remote_machine_and_include_in_git",
            Self::RemoteCacheCopy => "store_local_only_on_remote_machine",
        }
    }
}

/// Caller-selected add-to-project options. `openmates_only` suppresses the
/// default-source YAML save exactly like the legacy `--openmates-only` flag.
#[derive(Clone, Debug)]
pub struct WorkflowAttachOptions {
    pub storage: WorkflowStorageMode,
    pub openmates_only: bool,
    pub folder_id: Option<String>,
    pub source_id: Option<String>,
    pub remote_folder: Option<String>,
    pub source_chat: Option<String>,
}

/// Remote YAML outcome; `path` is the bound file path when one is known.
#[derive(Debug, Serialize)]
pub struct WorkflowRemoteFileResult {
    pub status: &'static str,
    pub path: Option<String>,
    pub error: Option<&'static str>,
}

#[derive(Debug)]
pub struct WorkflowAttachResult {
    pub project_id: String,
    pub workflow_id: String,
    /// The created item, or the existing raw (encrypted) item row.
    pub item: Value,
    pub remote_file: Option<WorkflowRemoteFileResult>,
}

impl Projects<'_> {
    /// Link one Workflow to a Project. An existing link keeps its row and only
    /// its encrypted metadata is rewritten; a new link records the storage
    /// mode. Lost responses are errors, never automatic retries.
    pub async fn attach_workflow<S, A, F>(
        &mut self,
        workflow_id: &str,
        project: &str,
        options: WorkflowAttachOptions,
        serialize: S,
        mut approve: A,
    ) -> Result<WorkflowAttachResult>
    where
        S: FnOnce(&WorkflowFileDocument) -> Result<(String, String)>,
        A: FnMut(String) -> F,
        F: std::future::Future<Output = Result<bool>>,
    {
        if matches!(&self.backend, Backend::ApiKey(_)) {
            return Err(Error::Unavailable {
                code: "project_item_link_unavailable",
                reason: "PROJECT_ITEM_LINK_REQUIRES_COOKIE_SESSION",
            });
        }
        if let Some(folder) = &options.folder_id {
            uuid(folder)?;
        }
        self.workflow_active()?;
        let project = self.resolve(project).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let sources = self.list_sources_raw(&project_id).await?;
        let default_source = sources.first();
        if options.storage != WorkflowStorageMode::SaveOnlyInOpenMates && default_source.is_none() {
            return Err(Error::Invalid(
                "Remote-copy proposals require a Project source.",
            ));
        }
        let workflow = self.workflow_row(workflow_id).await?;
        let workflow_id = string(&workflow, "id")?.to_owned();
        let route = self.path(&format!("/v1/projects/{project_id}/items"), &[]);
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        self.workflow_active()?;
        let mut existing = None;
        for item in response["items"].as_array().ok_or(Error::Protocol)? {
            if item["item_type"] != "workflow" {
                continue;
            }
            super::super::items::child_scope(item, &project, self.filters.team_id.as_deref())?;
            let target = Zeroizing::new(super::super::items::optional_text(
                item,
                "target_id_encrypted",
                &project.key,
            )?);
            if target.as_str() == workflow_id {
                existing = Some(item.clone());
                break;
            }
        }
        let mut metadata = PrivateJson(match &existing {
            Some(item) => {
                let text = Zeroizing::new(super::super::items::optional_text(
                    item,
                    "encrypted_metadata",
                    &project.key,
                )?);
                if text.is_empty() {
                    json!({})
                } else {
                    serde_json::from_str(&text).map_err(|_| Error::Crypto)?
                }
            }
            None => json!({}),
        });
        if !metadata.0.is_object() {
            return Err(Error::Protocol);
        }
        let mut remote_file = None;
        if options.storage != WorkflowStorageMode::SaveOnlyInOpenMates
            || (default_source.is_some() && !options.openmates_only)
        {
            let source = match &options.source_id {
                Some(id) => sources.iter().find(|row| row["source_id"] == id.as_str()),
                None => default_source,
            };
            let mut binding = PrivateJson(match metadata.0.get("remote_workflow_file") {
                Some(binding) if !binding.is_null() => binding.clone(),
                _ => json!({
                    "project_id": project_id,
                    "source_id": source.map(|row| row["source_id"].clone()).unwrap_or(json!("")),
                    "folder_path": options.remote_folder.as_deref().unwrap_or(""),
                }),
            });
            if !binding.0.is_object() {
                return Err(Error::Protocol);
            }
            let chat = options
                .source_chat
                .as_deref()
                .or(workflow["source_chat_id"].as_str());
            let focus = match chat {
                Some(chat) => {
                    let route = self.path(
                        "/v1/projects/focus/current",
                        &[("chat_id".into(), chat.into())],
                    );
                    self.backend
                        .request(Method::GET, &route, None, None)
                        .await?["focus"]
                        .clone()
                }
                None => Value::Null,
            };
            self.workflow_active()?;
            let (status, error) = match (source, chat) {
                (None, _) => ("pending", Some("source_selection_required")),
                (Some(source), Some(chat))
                    if source["source_id"] == binding.0["source_id"]
                        && focus["project_id"] == project_id.as_str() =>
                {
                    let (filename, content) = serialize(&build_workflow_export(&workflow)?)?;
                    let content = Zeroizing::new(content);
                    let version = string(&workflow, "current_version_id")?.to_owned();
                    self.persist_workflow_binding(
                        WorkflowBindingWrite {
                            id: &workflow_id,
                            expected_version: &version,
                            project: &project,
                            source,
                            chat,
                            filename: &filename,
                            content: &content,
                        },
                        &mut binding.0,
                        &mut approve,
                    )
                    .await?
                }
                _ => ("pending", Some("project_focus_required")),
            };
            self.workflow_active()?;
            remote_file = Some(WorkflowRemoteFileResult {
                status,
                path: binding.0["file_path"].as_str().map(str::to_owned),
                error,
            });
            metadata.0["remote_workflow_file"] = std::mem::take(&mut binding.0);
            metadata.0["remote_file_status"] = json!(status);
            let object = metadata.0.as_object_mut().ok_or(Error::Protocol)?;
            match error {
                Some(error) => {
                    object.insert("remote_file_error".into(), json!(error));
                }
                None => {
                    object.remove("remote_file_error");
                }
            }
        }
        let item = match existing {
            Some(item) => {
                let encoded = Zeroizing::new(serde_json::to_string(&metadata.0)?);
                let encrypted = crypto::encrypt_combined(&encoded, &project.key)?;
                let item_id =
                    super::super::sources::source_patch_segment(string(&item, "project_item_id")?)?;
                let route = self.path(&format!("/v1/projects/{project_id}/items/{item_id}"), &[]);
                self.backend
                    .request(
                        Method::PATCH,
                        &route,
                        Some(json!({"encrypted_metadata":encrypted,"updated_at":now()})),
                        None,
                    )
                    .await?;
                self.workflow_active()?;
                item
            }
            None => {
                let object = metadata.0.as_object_mut().ok_or(Error::Protocol)?;
                object.insert("storage".into(), json!(options.storage.wire()));
                object.insert("source".into(), json!("cli_add_to_project"));
                let title = workflow["title"]
                    .as_str()
                    .ok_or(Error::Protocol)?
                    .to_owned();
                let linked = self
                    .link_item(
                        &project_id,
                        super::super::items::ProjectLink {
                            item_type: super::super::items::ProjectItemType::Workflow,
                            target_id: workflow_id.clone(),
                            display_name: title,
                            folder_id: options.folder_id.clone(),
                            metadata: std::mem::take(&mut metadata.0),
                        },
                    )
                    .await?;
                linked["item"].clone()
            }
        };
        Ok(WorkflowAttachResult {
            project_id,
            workflow_id,
            item,
            remote_file,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust
    #[test]
    fn storage_modes_use_the_legacy_wire_names() {
        assert_eq!(
            WorkflowStorageMode::SaveOnlyInOpenMates.wire(),
            "save_only_in_openmates"
        );
        assert_eq!(
            WorkflowStorageMode::RemoteRepoCopy.wire(),
            "store_on_remote_machine_and_include_in_git"
        );
        assert_eq!(
            WorkflowStorageMode::RemoteCacheCopy.wire(),
            "store_local_only_on_remote_machine"
        );
    }
}
