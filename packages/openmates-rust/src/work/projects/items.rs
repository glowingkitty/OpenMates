//! Project links only: unlinking never deletes the linked object.
use super::*;

/// Item types accepted by the existing Project unlink endpoint.
#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProjectItemType {
    Embed,
    Chat,
    Workflow,
}

/// One encrypted Project link to create; the target object is never copied.
pub struct ProjectLink {
    pub item_type: ProjectItemType,
    pub target_id: String,
    pub display_name: String,
    pub folder_id: Option<String>,
    /// Plain JSON object, encrypted with the Project key before transport.
    pub metadata: Value,
}

impl Projects<'_> {
    /// Return the legacy decrypted folder/item projection in the selected scope.
    /// The canonical detail route also supports approved developer Project grants;
    /// the dedicated `/items` route is Cookie-only.
    pub async fn items(&mut self, selector: &str) -> Result<Value> {
        self.items_active()?;
        self.scope()?;
        let id = if uuid::Uuid::parse_str(selector).is_ok() {
            selector.to_owned()
        } else {
            string(&self.resolve(selector).await?.raw, "project_id")?.to_owned()
        };
        let route = self.path(&format!("/v1/projects/{id}"), &[]);
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        self.items_active()?;
        let raw = response["project"].clone();
        if raw["project_id"] != id {
            return Err(Error::Forbidden);
        }
        let key = self.row_key(&raw).await?;
        self.items_active()?;
        // Authenticate the Project metadata too, before releasing child plaintext.
        let project = decode(raw, key)?;
        let result = decode_items(&response, &project, self.filters.team_id.as_deref())?;
        self.items_active()?;
        Ok(result)
    }

    /// Remove links matching an exact type and target ID, without deleting targets.
    /// A lost or malformed response is an error, never an automatic retry.
    pub async fn unlink_item(
        &mut self,
        selector: &str,
        item_type: ProjectItemType,
        target_id: &str,
        confirmed: bool,
    ) -> Result<Value> {
        self.items_active()?;
        if !confirmed {
            return Err(Error::Invalid(
                "Project item removal requires explicit confirmation.",
            ));
        }
        if target_id.is_empty() || target_id.len() > 4096 || target_id.chars().any(char::is_control)
        {
            return Err(Error::Invalid(
                "Supply a valid exact Project item target ID.",
            ));
        }
        self.scope()?;
        if matches!(self.backend, Backend::ApiKey(_)) {
            return Err(Error::Unavailable {
                code: "project_item_unlink_unavailable",
                reason: "PROJECT_ITEM_UNLINK_REQUIRES_COOKIE_SESSION",
            });
        }
        let project = self.resolve(selector).await?;
        self.items_active()?;
        let permissions = &project.raw["mutation_permissions"];
        if permissions["manage_any_items"] != true && permissions["manage_own_items"] != true {
            return Err(Error::Forbidden);
        }
        // Team members can unlink only their own links. The backend checks every
        // matching attached_by_user_hash atomically at this existing endpoint.
        let id = string(&project.raw, "project_id")?;
        let kind = serde_json::to_value(item_type)?;
        let route = self.path(
            &format!("/v1/projects/{id}/items"),
            &[
                (
                    "item_type".into(),
                    kind.as_str().ok_or(Error::Protocol)?.into(),
                ),
                ("target_id".into(), target_id.into()),
            ],
        );
        let response = self
            .backend
            .request(Method::DELETE, &route, None, None)
            .await?;
        let deleted = response["deleted"].as_bool().ok_or(Error::Protocol)?;
        let count = response["deleted_count"].as_u64().ok_or(Error::Protocol)?;
        if deleted != (count > 0) {
            return Err(Error::Protocol);
        }
        Ok(json!({"project_id":id,"target_id":target_id,"deleted":deleted,"deleted_count":count}))
    }

    /// Create one encrypted Project link (the legacy CLI's
    /// createEncryptedProjectItem). The target stays where it is; only the
    /// target ID, display name, empty note and metadata are encrypted with the
    /// Project key. A lost response is an error, never an automatic retry.
    pub async fn link_item(&mut self, selector: &str, link: ProjectLink) -> Result<Value> {
        self.items_active()?;
        let ProjectLink {
            item_type,
            target_id,
            display_name,
            folder_id,
            metadata,
        } = link;
        if target_id.is_empty() || target_id.len() > 4096 || target_id.chars().any(char::is_control)
        {
            return Err(Error::Invalid(
                "Supply a valid exact Project item target ID.",
            ));
        }
        if !metadata.is_object() {
            return Err(Error::Invalid("Project item metadata must be an object."));
        }
        self.scope()?;
        if matches!(self.backend, Backend::ApiKey(_)) {
            return Err(Error::Unavailable {
                code: "project_item_link_unavailable",
                reason: "PROJECT_ITEM_LINK_REQUIRES_COOKIE_SESSION",
            });
        }
        let project = self.resolve(selector).await?;
        self.items_active()?;
        let id = string(&project.raw, "project_id")?.to_owned();
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| Error::Protocol)?
            .as_secs();
        let kind = serde_json::to_value(item_type)?;
        let key = &project.key;
        let body = json!({
            "project_item_id":uuid::Uuid::new_v4().to_string(),
            "folder_id":folder_id,
            "item_type":kind,
            "target_id":target_id,
            "target_id_encrypted":crypto::encrypt_combined(&target_id,key)?,
            "encrypted_display_name":crypto::encrypt_combined(&display_name,key)?,
            "encrypted_note":crypto::encrypt_combined("",key)?,
            "encrypted_metadata":crypto::encrypt_combined(&serde_json::to_string(&metadata)?,key)?,
            "created_at":now,"updated_at":now,"position":now
        });
        let route = self.path(&format!("/v1/projects/{id}/items"), &[]);
        let response = self
            .backend
            .request(Method::POST, &route, Some(body), None)
            .await?;
        let item = response
            .get("item")
            .filter(|item| item.is_object())
            .cloned()
            .ok_or(Error::Protocol)?;
        Ok(json!({"project_id":id,"item":item}))
    }

    fn items_active(&self) -> Result<()> {
        if self.operation_cancel.is_cancelled() {
            Err(Error::Cancelled)
        } else {
            Ok(())
        }
    }
}

pub(super) fn child_scope(
    row: &Value,
    project: &ResolvedProject,
    team: Option<&str>,
) -> Result<()> {
    let expected = hash(string(&project.raw, "project_id")?);
    if row["hashed_project_id"] != expected {
        return Err(Error::Forbidden);
    }
    if let Some(team) = team {
        if row["hashed_team_id"] != hash(team) || !row["hashed_user_id"].is_null() {
            return Err(Error::Forbidden);
        }
    } else if !row["hashed_team_id"].is_null()
        || row["hashed_user_id"] != project.raw["hashed_user_id"]
    {
        return Err(Error::Forbidden);
    }
    Ok(())
}

pub(super) fn optional_text(row: &Value, field: &str, key: &[u8; 32]) -> Result<String> {
    match row.get(field) {
        None | Some(Value::Null) => Ok(String::new()),
        Some(Value::String(text)) if text.is_empty() => Ok(String::new()),
        Some(Value::String(text)) => crypto::decrypt_combined(text, key),
        _ => Err(Error::Protocol),
    }
}

fn decode_items(response: &Value, project: &ResolvedProject, team: Option<&str>) -> Result<Value> {
    let folders = response["folders"].as_array().ok_or(Error::Protocol)?;
    let items = response["items"].as_array().ok_or(Error::Protocol)?;
    let mut ids = std::collections::BTreeSet::new();
    let mut decoded_folders = Vec::with_capacity(folders.len());
    for row in folders {
        child_scope(row, project, team)?;
        let id = string(row, "folder_id")?;
        if !ids.insert(id) {
            return Err(Error::Protocol);
        }
        decoded_folders.push(json!({
            "folder_id":id,
            // Legacy output intentionally returns the parent hash, not a guessed ID.
            "parent_folder_id":row["hashed_parent_folder_id"],
            "name":optional_text(row,"encrypted_name",&project.key)?,
            "position":row.get("position").filter(|v|!v.is_null()).cloned().unwrap_or(json!(0))
        }));
    }
    ids.clear();
    let mut decoded_items = Vec::with_capacity(items.len());
    for row in items {
        child_scope(row, project, team)?;
        let id = string(row, "project_item_id")?;
        if !ids.insert(id) {
            return Err(Error::Protocol);
        }
        let kind = string(row, "item_type")?;
        if !["embed", "chat", "upload", "workflow"].contains(&kind) {
            return Err(Error::Protocol);
        }
        let target = optional_text(row, "target_id_encrypted", &project.key)?;
        if row
            .get("target_id_hash")
            .is_some_and(|v| !v.is_null() && v != &json!(hash(&target)))
        {
            return Err(Error::Forbidden);
        }
        decoded_items.push(json!({"project_item_id":id,"type":kind,"target_id":target,
            "display_name":optional_text(row,"encrypted_display_name",&project.key)?,
            "ownership_label":row["ownership_label"],
            "position":row.get("position").filter(|v|!v.is_null()).cloned().unwrap_or(json!(0))}));
    }
    Ok(
        json!({"project_id":project.raw["project_id"],"folders":decoded_folders,"items":decoded_items}),
    )
}

#[cfg(test)]
mod tests;
