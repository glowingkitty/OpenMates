//! Project file operations against the tree, run by the hosted device
//! executor over an in-memory [`HostedIo`], so every `result` is exactly what
//! the device executor returns and every revision is built by its write path.
use super::hosted::io::HostedIo;
use super::hosted::job::{self, HostedContext};
use super::tree::{Entry, ProjectTree};
use super::*;
use futures_util::FutureExt;
use zeroize::Zeroizing;

/// Result of one operation: the model-facing `result` and the revisions the
/// server has to commit (empty for read, list and search).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct OpOutcome {
    /// Same shape as the hosted device executor's result.
    pub result: Value,
    /// Ciphertext changes, in order.
    pub revisions: Vec<Revision>,
}

enum Captured {
    Commit(Value),
    Rename { item_id: String, body: Value },
    Delete { item_id: String, body: Value },
}

struct TreeIo<'t> {
    tree: &'t ProjectTree,
    /// Read the last synced text instead of the working file (building a
    /// revision for a change that is already on disk).
    use_base: bool,
    captured: Vec<Captured>,
}

impl HostedIo for TreeIo<'_> {
    async fn list_files(&mut self) -> HostedResult<Vec<HostedFile>> {
        Ok(self
            .tree
            .files
            .iter()
            .map(|(path, entry)| HostedFile {
                embed_id: entry.embed_id.clone(),
                path: path.clone(),
                item_id: entry.item_id.clone(),
                metadata: entry.metadata.clone(),
            })
            .collect())
    }

    async fn read_head(&mut self, embed_id: &str) -> HostedResult<HostedHead> {
        let Some((path, entry)) = self.tree.files.iter().find(|(_, e)| e.embed_id == embed_id)
        else {
            return refused("file_not_found");
        };
        let text = if self.use_base {
            entry.synced().to_owned()
        } else {
            self.tree
                .disk_text(path)
                .ok_or(HostedFileError::Refused("file_not_found"))?
        };
        let mut fields = entry.fields.clone();
        let has = |name: &str, fields: &[(String, Value)]| {
            fields.iter().any(|(k, v)| k == name && !v.is_null())
        };
        let name = if has("code", &fields) || !has("content", &fields) {
            "code"
        } else {
            "content"
        };
        match fields.iter_mut().find(|(k, _)| k == name) {
            Some(slot) => slot.1 = json!(text),
            None => fields.push((name.to_owned(), json!(text))),
        }
        Ok(HostedHead {
            embed_key: entry.embed_key.clone(),
            content: fields,
            revision: entry.base_version.unwrap_or(1).max(1),
            has_initial_history: entry.has_initial_history,
        })
    }

    async fn receipt(&mut self, _: &str, _: &str, _: &str, _: &str) -> HostedResult<Option<Value>> {
        Ok(None)
    }

    async fn commit(&mut self, payload: Value) -> HostedResult<Value> {
        let next = payload["expected_revision"].as_u64().unwrap_or(0) + 1;
        self.captured.push(Captured::Commit(payload));
        Ok(json!({"status": "committed", "current_revision": next}))
    }

    async fn rename_link(&mut self, item_id: &str, body: Value) -> HostedResult<Value> {
        self.captured.push(Captured::Rename {
            item_id: item_id.to_owned(),
            body,
        });
        Ok(json!({}))
    }

    async fn delete_link(&mut self, item_id: &str, body: Value) -> HostedResult<Value> {
        self.captured.push(Captured::Delete {
            item_id: item_id.to_owned(),
            body,
        });
        Ok(json!({}))
    }
}

impl Entry {
    /// The plaintext the server will hold once every built revision commits.
    pub(super) fn synced(&self) -> &str {
        self.pending.as_deref().unwrap_or(&self.base_text)
    }
}

fn content_text(fields: &[(String, Value)]) -> Option<String> {
    let get = |name: &str| fields.iter().find(|(k, _)| k == name).map(|(_, v)| v);
    let value = match get("code") {
        Some(Value::Null) | None => get("content"),
        other => other,
    };
    value.and_then(Value::as_str).map(str::to_owned)
}

impl ProjectTree {
    /// Run one Project file operation (`list`, `search`, `read_text`,
    /// `create_file`, `update_file`, `rename_file`, `delete_file`; arguments
    /// as the device executor takes them, plus an optional `operation_id`).
    /// Changes are applied to the working files at once and returned as
    /// revisions for the server to commit.
    ///
    /// # Errors
    /// The executor refusal codes (`file_not_found`, `stale_base`,
    /// `invalid_patch`, `file_exists`, `protected_path`, ...) and
    /// `unsupported_operation` for any other operation.
    pub fn run_op(&mut self, operation: &str, arguments: &Value) -> HostedResult<OpOutcome> {
        let operation = match operation {
            "list" => HostedFileOperation::List,
            "search" => HostedFileOperation::Search,
            "read_text" => HostedFileOperation::ReadText,
            "create_file" => HostedFileOperation::CreateFile,
            "update_file" => HostedFileOperation::UpdateFile,
            "rename_file" => HostedFileOperation::RenameFile,
            "delete_file" => HostedFileOperation::DeleteFile,
            _ => return refused("unsupported_operation"),
        };
        let operation_id = arguments["operation_id"]
            .as_str()
            .map_or_else(|| uuid::Uuid::new_v4().to_string(), str::to_owned);
        self.run_job(operation, arguments.clone(), operation_id, false)
    }

    pub(super) fn run_job(
        &mut self,
        operation: HostedFileOperation,
        arguments: Value,
        operation_id: String,
        use_base: bool,
    ) -> HostedResult<OpOutcome> {
        let mutation = if operation.is_mutation() {
            let mut fields = arguments.clone();
            if !fields.is_object() {
                return refused("invalid_file_mutation");
            }
            fields["operation"] = json!(operation.wire());
            fields["operation_id"] = json!(operation_id);
            Some(
                serde_json::from_value::<HostedFileMutation>(fields)
                    .map_err(|_| HostedFileError::Refused("invalid_file_mutation"))?,
            )
        } else {
            None
        };
        let job = HostedFileJob {
            operation_id,
            chat_id: self.chat_id.clone(),
            operation,
            arguments,
        };
        let placeholder: Key = crypto::random_key();
        let (result, captured) = {
            let ctx = HostedContext {
                project_id: &self.project_id,
                project_key: &self.project_key,
                chat_key: Some(self.chat_key.as_ref().map_or(&*placeholder, |k| &**k)),
                team_id: self.team_id.as_deref(),
                private_paths: &[],
                ignored_read_approved: false,
            };
            let mut io = TreeIo {
                tree: self,
                use_base,
                captured: Vec::new(),
            };
            let result = job::execute(&mut io, &ctx, &job, mutation.as_ref())
                .now_or_never()
                .ok_or(HostedFileError::Core(Error::Protocol))??;
            (result, io.captured)
        };
        let revisions = self.apply_captured(&result, captured)?;
        Ok(OpOutcome { result, revisions })
    }

    fn apply_captured(
        &mut self,
        result: &Value,
        captured: Vec<Captured>,
    ) -> HostedResult<Vec<Revision>> {
        let mut revisions = Vec::new();
        for item in captured {
            revisions.push(match item {
                Captured::Commit(payload) => self.apply_commit(result, payload)?,
                Captured::Rename { item_id, body } => self.apply_rename(result, item_id, body)?,
                Captured::Delete { item_id, body } => self.apply_delete(result, item_id, body)?,
            });
        }
        Ok(revisions)
    }

    fn apply_commit(&mut self, result: &Value, mut payload: Value) -> HostedResult<Revision> {
        let path = normalize_path(&result["path"])?;
        let embed_id = string(&payload, "embed_id")?.to_owned();
        let creating = payload.get("create").is_some();
        let embed_key: Key = if creating {
            let wrapper = payload["create"]["key_wrappers"]
                .as_array()
                .and_then(|rows| rows.iter().find(|row| row["key_type"] == "project"))
                .ok_or(Error::Protocol)?;
            let raw = Zeroizing::new(crypto::server_fields::decrypt_bytes(
                string(wrapper, "encrypted_embed_key")?,
                &self.project_key,
                &[],
            )?);
            key_bytes(&raw)?
        } else {
            self.files
                .get(&path)
                .ok_or(HostedFileError::Refused("file_not_found"))?
                .embed_key
                .clone()
        };
        let plain = Zeroizing::new(crypto::server_fields::decrypt_text(
            string(&payload["head"], "encrypted_content")?,
            &embed_key,
            &[],
        )?);
        let fields = crate::work::decode_content_fields(&plain).ok_or(Error::Crypto)?;
        let text = Zeroizing::new(content_text(&fields).ok_or(Error::Crypto)?);
        self.write_disk(&path, &text)?;
        let base_version = payload["expected_revision"].as_i64().filter(|_| !creating);
        if creating {
            if self.chat_key.is_none() {
                if let Some(rows) = payload["create"]["key_wrappers"].as_array_mut() {
                    rows.retain(|row| row["key_type"] != "chat");
                }
            }
            self.files.insert(
                path.clone(),
                Entry {
                    embed_id: embed_id.clone(),
                    item_id: payload["create"]["project_item_id"]
                        .as_str()
                        .map(str::to_owned),
                    metadata: json!({"path": path, "source": HOSTED_SOURCE}),
                    embed_key,
                    fields,
                    base_version: None,
                    base_text: String::new(),
                    pending: Some(text.to_string()),
                    has_initial_history: false,
                },
            );
        } else if let Some(entry) = self.files.get_mut(&path) {
            entry.fields = fields;
            entry.pending = Some(text.to_string());
        }
        Ok(Revision {
            path,
            embed_id,
            base_version,
            kind: if creating {
                RevisionKind::Create
            } else {
                RevisionKind::Update
            },
            transaction: payload,
        })
    }

    fn apply_rename(
        &mut self,
        result: &Value,
        item_id: String,
        body: Value,
    ) -> HostedResult<Revision> {
        let new_path = normalize_path(&result["path"])?;
        let old_path = normalize_path(&result["previous_path"])?;
        let (from, to) = (self.resolve(&old_path)?, self.resolve(&new_path)?);
        if let Some(parent) = to.parent() {
            std::fs::create_dir_all(parent).map_err(|_| Error::Protocol)?;
        }
        std::fs::rename(from, to).map_err(|_| Error::Protocol)?;
        let mut entry = self
            .files
            .remove(&old_path)
            .ok_or(HostedFileError::Refused("file_not_found"))?;
        entry.item_id = result["project_item_id"].as_str().map(str::to_owned);
        entry.metadata["path"] = json!(new_path);
        let revision = Revision {
            path: new_path.clone(),
            embed_id: entry.embed_id.clone(),
            base_version: entry.base_version.and_then(|v| i64::try_from(v).ok()),
            kind: RevisionKind::Move,
            transaction: json!({"action": "rename", "item_id": item_id, "body": body}),
        };
        self.files.insert(new_path, entry);
        Ok(revision)
    }

    fn apply_delete(
        &mut self,
        result: &Value,
        item_id: String,
        body: Value,
    ) -> HostedResult<Revision> {
        let path = normalize_path(&result["path"])?;
        // A file the command already removed is fine; anything else is not.
        match std::fs::remove_file(self.resolve(&path)?) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err(Error::Protocol.into()),
        }
        let entry = self
            .files
            .remove(&path)
            .ok_or(HostedFileError::Refused("file_not_found"))?;
        Ok(Revision {
            path,
            embed_id: entry.embed_id,
            base_version: entry.base_version.and_then(|v| i64::try_from(v).ok()),
            kind: RevisionKind::Delete,
            transaction: json!({"action": "delete", "item_id": item_id, "body": body}),
        })
    }
}
