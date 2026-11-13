//! IO adapter of the hosted Project file executor: the effects
//! `executeHostedProjectFileJob` needs (list links, read a ciphertext head,
//! look up an exact revision receipt, commit a revision) plus the P11 link
//! moves (rename, delete), implemented over the
//! authenticated session. Mirrors the npm CLI `registerCliProjectFileExecutor`
//! adapter (`readEncryptedProjectFile`, `getProjectFileRevisionReceipt`,
//! `commitHostedProjectFileRevision`). Cookie sessions only.
use super::super::items::optional_text;
use super::*;

/// Effects of one hosted file operation. Implemented by [`ProjectIo`] and by
/// in-memory fakes in the unit tests.
pub(super) trait HostedIo {
    /// Every hosted-file candidate link of the Project with its metadata path.
    async fn list_files(&mut self) -> HostedResult<Vec<HostedFile>>;
    /// The decrypted current head of one linked embed.
    async fn read_head(&mut self, embed_id: &str) -> HostedResult<HostedHead>;
    /// The committed receipt of exactly this operation, if any.
    async fn receipt(
        &mut self,
        embed_id: &str,
        operation_id: &str,
        chat_id: &str,
        digest: &str,
    ) -> HostedResult<Option<Value>>;
    /// Publish one revision transaction and return the server result.
    async fn commit(&mut self, payload: Value) -> HostedResult<Value>;
    /// `POST /v1/projects/{id}/items/{item}/rename`; the embed is kept.
    async fn rename_link(&mut self, item_id: &str, body: Value) -> HostedResult<Value>;
    /// `DELETE /v1/projects/{id}/items/{item}`; the embed and revisions stay.
    async fn delete_link(&mut self, item_id: &str, body: Value) -> HostedResult<Value>;
}

impl Projects<'_> {
    /// One Project item-link request (adopt, rename, delete). A refusal whose
    /// body names a stable link code (`path_conflict`, `embed_already_linked`,
    /// …) becomes [`HostedFileError::Rejected`] with that code; other failures
    /// keep the core error.
    ///
    /// # Errors
    /// As described; cookie sessions only.
    pub(super) async fn item_link_request(
        &mut self,
        method: Method,
        route: &str,
        body: Value,
    ) -> HostedResult<Value> {
        let client = self.hosted_client()?;
        client.clear_project_item_error();
        match client
            .request_task_headers(method, route, Some(body), None, None, None)
            .await
        {
            Ok(value) => Ok(value),
            Err(error) => match client.take_project_item_error() {
                Some(code) => Err(HostedFileError::Rejected(code.to_owned())),
                None => Err(HostedFileError::Core(error)),
            },
        }
    }

    /// The session client; hosted files are first-party session data only.
    pub(super) fn hosted_client(&mut self) -> Result<&mut Client> {
        match &mut self.backend {
            Backend::Cookie(client) => Ok(client),
            Backend::ApiKey(_) => Err(Error::Unavailable {
                code: "hosted_project_files_unavailable",
                reason: "HOSTED_PROJECT_FILES_REQUIRE_COOKIE_SESSION",
            }),
        }
    }
}

/// Session-backed effects for one resolved Project.
pub(super) struct ProjectIo<'p, 'a> {
    pub(super) projects: &'p mut Projects<'a>,
    pub(super) project_id: String,
    pub(super) key: Key,
}

impl ProjectIo<'_, '_> {
    fn active(&self) -> HostedResult<()> {
        if self.projects.operation_cancel.is_cancelled() {
            return Err(HostedFileError::Core(Error::Cancelled));
        }
        Ok(self.projects.backend.verify_private_operation()?)
    }
}

/// npm CLI `listFiles`: embed/upload links whose metadata names a path
/// (`path ?? file_path ?? filename ?? display name`); links the hosted path
/// rule refuses are not source files and are skipped.
pub(super) fn linked_files(items: &Value, key: &[u8; 32]) -> HostedResult<Vec<HostedFile>> {
    let mut files = Vec::new();
    for item in items
        .as_array()
        .ok_or(HostedFileError::Core(Error::Protocol))?
    {
        if !matches!(item["item_type"].as_str(), Some("embed" | "upload")) {
            continue;
        }
        let target = Zeroizing::new(optional_text(item, "target_id_encrypted", key)?);
        if target.is_empty() {
            continue;
        }
        if item["target_id_hash"]
            .as_str()
            .is_some_and(|expected| expected != hash(&target))
        {
            return Err(HostedFileError::Core(Error::Forbidden));
        }
        let metadata_text = Zeroizing::new(optional_text(item, "encrypted_metadata", key)?);
        let metadata: Value = if metadata_text.is_empty() {
            json!({})
        } else {
            serde_json::from_str(&metadata_text)
                .map_err(|_| HostedFileError::Core(Error::Crypto))?
        };
        let display = optional_text(item, "encrypted_display_name", key)?;
        let path = ["path", "file_path", "filename"]
            .iter()
            .find_map(|field| match &metadata[*field] {
                Value::Null => None,
                value => Some(value.clone()),
            })
            .unwrap_or_else(|| {
                if item
                    .get("encrypted_display_name")
                    .is_some_and(|v| !v.is_null())
                {
                    json!(display)
                } else {
                    Value::Null
                }
            });
        // An adopted application (its folder) or test result is a Project link
        // but never a file: listing it would shadow the folder's files and let
        // a file write address the application embed.
        let non_file_link = item["link_kind"]
            .as_str()
            .is_some_and(|kind| kind != "file")
            || matches!(
                metadata["source"].as_str(),
                Some(super::adopt_plan::APPLICATION_SOURCE | super::adopt_plan::TEST_RESULT_SOURCE)
            );
        if !path.is_string() || non_file_link {
            continue;
        }
        match normalize_path(&path) {
            Ok(path) => files.push(HostedFile {
                embed_id: target.to_string(),
                path,
                item_id: item["project_item_id"].as_str().map(str::to_owned),
                metadata: metadata.clone(),
            }),
            Err(HostedFileError::Refused(_)) => {}
            Err(error) => return Err(error),
        }
    }
    Ok(files)
}

/// Decode a ciphertext head projection (`/v1/embeds/{id}/encrypted`).
pub(super) fn decode_head(
    response: &Value,
    embed_id: &str,
    project_id: &str,
    project_key: &[u8; 32],
) -> HostedResult<HostedHead> {
    let embed = response
        .get("embed")
        .filter(|e| e.is_object())
        .ok_or(HostedFileError::Core(Error::Protocol))?;
    if embed["embed_id"].as_str().is_some_and(|id| id != embed_id) {
        return Err(HostedFileError::Core(Error::Forbidden));
    }
    let wrapper = response["embed_keys"].as_array().and_then(|rows| {
        rows.iter().find(|row| {
            row["key_type"] == "project"
                && row["encrypted_embed_key"].is_string()
                && row["hashed_project_id"]
                    .as_str()
                    .is_none_or(|h| h == hash(project_id))
        })
    });
    // npm falls back to a chat/master wrapper from its synced cache for old
    // links. The core has no such cache read here, so the file waits instead.
    let Some(wrapper) = wrapper else {
        return refused("file_key_unavailable");
    };
    let raw = crypto::server_fields::decrypt_bytes(
        string(wrapper, "encrypted_embed_key")?,
        project_key,
        &[],
    )?;
    let embed_key = key_bytes(&raw)?;
    let cipher = embed["encrypted_content"]
        .as_str()
        .ok_or(HostedFileError::Refused("file_key_unavailable"))?;
    let plain = Zeroizing::new(
        crypto::server_fields::decrypt_text(cipher, &embed_key, &[])
            .map_err(|_| HostedFileError::Refused("file_decryption_failed"))?,
    );
    // npm `toonEncodeContent` falls back to JSON text when TOON cannot encode
    // a value; readers (`parseEmbedContentObject`) accept both.
    let content: Vec<(String, Value)> =
        if let Ok(Value::Object(map)) = serde_json::from_str::<Value>(&plain) {
            map.into_iter().collect()
        } else {
            let decoded = crate::toon_decode::decode(&plain)
                .map_err(|_| HostedFileError::Refused("unsupported_file_content"))?;
            let crate::toon_decode::ToonValue::Object(object) = decoded else {
                return refused("unsupported_file_content");
            };
            object
                .entries()
                .iter()
                .map(|(key, value)| (key.clone(), value.to_json_value()))
                .collect()
        };
    let revision = match &embed["version_number"] {
        Value::Null => 1,
        value => value
            .as_u64()
            .filter(|v| *v >= 1)
            .ok_or(HostedFileError::Core(Error::Protocol))?,
    };
    Ok(HostedHead {
        embed_key,
        content,
        revision,
        has_initial_history: response["has_initial_history"] == true,
    })
}

impl HostedIo for ProjectIo<'_, '_> {
    async fn list_files(&mut self) -> HostedResult<Vec<HostedFile>> {
        self.active()?;
        let route = self
            .projects
            .path(&format!("/v1/projects/{}", self.project_id), &[]);
        let response = self
            .projects
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        self.active()?;
        if response["project"]["project_id"] != self.project_id.as_str() {
            return Err(HostedFileError::Core(Error::Forbidden));
        }
        linked_files(&response["items"], &self.key)
    }

    async fn read_head(&mut self, embed_id: &str) -> HostedResult<HostedHead> {
        self.active()?;
        uuid(embed_id)?;
        let route = self.projects.path(
            &format!("/v1/embeds/{embed_id}/encrypted"),
            &[("project_id".into(), self.project_id.clone())],
        );
        let response = self
            .projects
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        self.active()?;
        decode_head(&response, embed_id, &self.project_id, &self.key)
    }

    async fn receipt(
        &mut self,
        embed_id: &str,
        operation_id: &str,
        chat_id: &str,
        digest: &str,
    ) -> HostedResult<Option<Value>> {
        self.active()?;
        uuid(embed_id)?;
        let route = self.projects.path(
            &format!("/v1/embeds/{embed_id}/revision-receipts/{operation_id}"),
            &[
                ("project_id".into(), self.project_id.clone()),
                ("chat_id".into(), chat_id.into()),
                ("proposal_digest".into(), digest.into()),
            ],
        );
        let receipt = self
            .projects
            .hosted_client()?
            .hosted_file_optional_get(&route)
            .await?;
        self.active()?;
        Ok(receipt)
    }

    async fn commit(&mut self, payload: Value) -> HostedResult<Value> {
        self.active()?;
        let result = self
            .projects
            .hosted_client()?
            .commit_embed_revision(payload)
            .await?;
        self.active()?;
        Ok(result)
    }

    async fn rename_link(&mut self, item_id: &str, body: Value) -> HostedResult<Value> {
        self.active()?;
        uuid(item_id)?;
        let route = self.projects.path(
            &format!("/v1/projects/{}/items/{item_id}/rename", self.project_id),
            &[],
        );
        let result = self
            .projects
            .item_link_request(Method::POST, &route, body)
            .await?;
        self.active()?;
        Ok(result)
    }

    async fn delete_link(&mut self, item_id: &str, body: Value) -> HostedResult<Value> {
        self.active()?;
        uuid(item_id)?;
        let route = self.projects.path(
            &format!("/v1/projects/{}/items/{item_id}", self.project_id),
            &[],
        );
        let result = self
            .projects
            .item_link_request(Method::DELETE, &route, body)
            .await?;
        self.active()?;
        Ok(result)
    }
}
