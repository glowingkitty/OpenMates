//! Cookie-only encrypted source authoring. Native filesystem approval is separate.
use super::*;

#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProjectSourceType {
    LocalFolder,
    LocalGitRepository,
    RemoteFolder,
    RemoteGitRepository,
}
#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProjectSourceCapability {
    Read,
    Search,
    Import,
    WriteRequest,
    RunCommand,
}
#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProjectSourceStatus {
    Connected,
    Offline,
    PermissionRequired,
    Revoked,
}
/// Metadata is encrypted in full, including legacy root/binding_root fields.
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectSourceCreate {
    pub source_id: String,
    pub source_type: ProjectSourceType,
    pub display_name: String,
    pub metadata: serde_json::Map<String, Value>,
    pub capabilities: Vec<ProjectSourceCapability>,
    pub status: ProjectSourceStatus,
    pub created_at: u64,
    pub updated_at: u64,
    pub last_indexed_at: Option<u64>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectSourceCapabilitiesPatch {
    pub capabilities: Vec<ProjectSourceCapability>,
    pub updated_at: u64,
}
/// Validated/decrypted response; no Debug to avoid accidental metadata logging.
#[derive(Clone, Serialize, Deserialize)]
pub struct ProjectSource {
    pub source_id: String,
    pub source_type: ProjectSourceType,
    pub display_name: String,
    pub metadata: serde_json::Map<String, Value>,
    pub capabilities: Vec<ProjectSourceCapability>,
    pub status: ProjectSourceStatus,
    pub created_at: u64,
    pub updated_at: u64,
    pub last_indexed_at: Option<u64>,
}
fn source_id(id: &str) -> Result<()> {
    if id.is_empty() || id.len() > 128 || id.chars().any(char::is_control) {
        return Err(Error::Invalid("Supply an exact Project source ID."));
    }
    Ok(())
}
/// FastAPI's ordinary path parameter cannot represent a decoded slash; URL
/// clients normalize dot segments before dispatch. Creation still preserves
/// these legacy IDs, but PATCH must refuse rather than target another route.
pub(super) fn source_patch_segment(id: &str) -> Result<String> {
    source_id(id)?;
    if id.contains('/') || matches!(id, "." | "..") {
        return Err(Error::Invalid(
            "Project source ID cannot be represented by the backend PATCH route.",
        ));
    }
    // form_urlencoded uses '+' for spaces, which path parameters do not
    // decode as spaces. Literal '+' was already encoded as %2B.
    Ok(url::form_urlencoded::byte_serialize(id.as_bytes())
        .collect::<String>()
        .replace('+', "%20"))
}
fn source_capabilities(values: &[ProjectSourceCapability], require_nonempty: bool) -> Result<()> {
    if values.len() > 8
        || require_nonempty && values.is_empty()
        || require_nonempty
            && values
                .iter()
                .enumerate()
                .any(|(i, c)| values[..i].contains(c))
    {
        return Err(Error::Invalid(
            "Project source capabilities must be unique and supported.",
        ));
    }
    Ok(())
}
fn source_create_wire(input: &ProjectSourceCreate, key: &[u8; 32]) -> Result<Value> {
    source_id(&input.source_id)?;
    // Creation preserves the backend's empty-capability legacy representation.
    source_capabilities(&input.capabilities, false)?;
    let name = crypto::server_fields::encrypt_text(&input.display_name, key, &[])?;
    let metadata = crypto::server_fields::encrypt_text(&serde_json::to_string(&input.metadata)?, key, &[])?;
    if name.len() > 128_000 || metadata.len() > 128_000 {
        return Err(Error::Invalid(
            "Project source ciphertext exceeds the server bound.",
        ));
    }
    Ok(
        json!({"source_id": input.source_id, "source_type": input.source_type,
        "encrypted_display_name":name, "encrypted_metadata":metadata,
        "capabilities":input.capabilities, "status":input.status,
        "created_at":input.created_at,"updated_at":input.updated_at,
        "last_indexed_at":input.last_indexed_at}),
    )
}
fn source_ack(response: &Value) -> Result<&Value> {
    response
        .get("source")
        .filter(|source| source.is_object())
        .ok_or(Error::Protocol)
}
fn source_decode(
    raw: &Value,
    project: &str,
    owner: &str,
    team: Option<&str>,
    key: &[u8; 32],
) -> Result<ProjectSource> {
    if raw["hashed_project_id"] != hash(project)
        || match team {
            Some(team) => raw["hashed_team_id"] != hash(team) || !raw["hashed_user_id"].is_null(),
            None => raw["hashed_user_id"] != hash(owner) || !raw["hashed_team_id"].is_null(),
        }
    {
        return Err(Error::Forbidden);
    }
    let id = string(raw, "source_id")?;
    source_id(id).map_err(|_| Error::Protocol)?;
    let caps: Vec<ProjectSourceCapability> =
        serde_json::from_value(raw["capabilities"].clone()).map_err(|_| Error::Protocol)?;
    source_capabilities(&caps, false).map_err(|_| Error::Protocol)?;
    for field in ["encrypted_metadata", "encrypted_display_name"] {
        if string(raw, field)?.len() > 128_000 {
            return Err(Error::Protocol);
        }
    }
    let metadata = crypto::decrypt_combined(string(raw, "encrypted_metadata")?, key)?;
    Ok(ProjectSource {
        source_id: id.into(),
        source_type: serde_json::from_value(raw["source_type"].clone())
            .map_err(|_| Error::Protocol)?,
        display_name: crypto::decrypt_combined(string(raw, "encrypted_display_name")?, key)?,
        metadata: serde_json::from_str(&metadata).map_err(|_| Error::Crypto)?,
        capabilities: caps,
        status: serde_json::from_value(raw["status"].clone()).map_err(|_| Error::Protocol)?,
        created_at: raw["created_at"].as_u64().ok_or(Error::Protocol)?,
        updated_at: raw["updated_at"].as_u64().ok_or(Error::Protocol)?,
        last_indexed_at: serde_json::from_value(raw["last_indexed_at"].clone())
            .map_err(|_| Error::Protocol)?,
    })
}
impl Projects<'_> {
    fn source_cookie_only(&self) -> Result<()> {
        if matches!(&self.backend, Backend::ApiKey(_)) {
            return Err(Error::Unavailable {
                code: "project_source_authoring_unavailable",
                reason: "PROJECT_SOURCE_AUTHORING_REQUIRES_COOKIE_SESSION",
            });
        }
        Ok(())
    }
    async fn source_cookie_owner(&mut self) -> Result<String> {
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        // Refuse before validation/resolution/transport, even for invalid inputs.
        match &mut self.backend {
            Backend::ApiKey(_) => Err(Error::Unavailable {
                code: "project_source_authoring_unavailable",
                reason: "PROJECT_SOURCE_AUTHORING_REQUIRES_COOKIE_SESSION",
            }),
            Backend::Cookie(client) => {
                client.validate_session().await?;
                client.user()["id"]
                    .as_str()
                    .filter(|v| !v.is_empty())
                    .or_else(|| client.user()["user_id"].as_str().filter(|v| !v.is_empty()))
                    .map(str::to_owned)
                    .ok_or(Error::Authentication)
            }
        }
    }
    pub async fn create_source(
        &mut self,
        selector: &str,
        input: ProjectSourceCreate,
    ) -> Result<ProjectSource> {
        let owner = self.source_cookie_owner().await?;
        self.scope()?;
        source_id(&input.source_id)?;
        source_capabilities(&input.capabilities, false)?;
        let project = self.resolve(selector).await?;
        let id = string(&project.raw, "project_id")?;
        let payload = source_create_wire(&input, &project.key)?;
        let route = self.path(&format!("/v1/projects/{id}/sources"), &[]);
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        // The canonical route enforces current Team mutate role and configured
        // write mode. Do not infer either from cached Project data or titles.
        let response = self
            .backend
            .request(Method::POST, &route, Some(payload.clone()), None)
            .await?;
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let raw = source_ack(&response)?;
        for (field, value) in payload.as_object().ok_or(Error::Protocol)? {
            if raw[field] != *value {
                return Err(Error::Forbidden);
            }
        }
        source_decode(
            raw,
            id,
            &owner,
            self.filters.team_id.as_deref(),
            &project.key,
        )
    }
    pub async fn update_source_capabilities(
        &mut self,
        selector: &str,
        id: &str,
        input: ProjectSourceCapabilitiesPatch,
    ) -> Result<ProjectSource> {
        self.source_cookie_only()?;
        let encoded_id = source_patch_segment(id)?;
        let owner = self.source_cookie_owner().await?;
        self.scope()?;
        source_capabilities(&input.capabilities, true)?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?;
        let route = self.path(
            &format!("/v1/projects/{project_id}/sources/{}", encoded_id),
            &[],
        );
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        // Backend preserves encrypted fields and enforces attached-by member
        // ownership and non-revoked source; this call grants no host authority.
        let response = self
            .backend
            .request(
                Method::PATCH,
                &route,
                Some(json!({"capabilities":input.capabilities,"updated_at":input.updated_at})),
                None,
            )
            .await?;
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let raw = source_ack(&response)?;
        if raw["source_id"] != id
            || raw["capabilities"] != json!(input.capabilities)
            || raw["updated_at"] != input.updated_at
            || raw["status"] == "revoked"
        {
            return Err(Error::Forbidden);
        }
        source_decode(
            raw,
            project_id,
            &owner,
            self.filters.team_id.as_deref(),
            &project.key,
        )
    }
}
#[cfg(test)]
mod tests;

#[cfg(all(test, not(target_arch = "wasm32")))]
mod field_interop_tests {
    use super::*;
    use crate::work::task_crypto::field_interop_support::{assert_web, case};
    #[test]
    fn actual_source_fields_read_in_web_legacy_decoders() {
        let key = [31; 32];
        let input = ProjectSourceCreate {
            source_id: "fixture/source".into(), source_type: ProjectSourceType::LocalFolder,
            display_name: "Private source Δ".into(), metadata: serde_json::from_value(json!({"root":"/synthetic/project"})).unwrap(),
            capabilities: vec![ProjectSourceCapability::Read], status: ProjectSourceStatus::Connected,
            created_at: 1, updated_at: 2, last_indexed_at: None,
        };
        let raw = source_create_wire(&input, &key).unwrap();
        let metadata = serde_json::to_string(&input.metadata).unwrap();
        assert_web(vec![case("source.name", "object-text", raw["encrypted_display_name"].as_str().unwrap(), &key, input.display_name.as_bytes(), ""),
            case("source.metadata", "object-text", raw["encrypted_metadata"].as_str().unwrap(), &key, metadata.as_bytes(), "")]);
        assert_eq!(raw["source_id"], "fixture/source");
        assert_eq!(raw["capabilities"], json!(["read"]));
    }
}
