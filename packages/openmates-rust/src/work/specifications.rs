//! Encrypted Project Specifications: typed document, client-side encryption,
//! content commitment and the list/show/revisions/revise/approve/create calls
//! against `/v1/projects/{project}/specifications`.
//!
//! The server stores opaque ciphertext and a client-made SHA-256 commitment of
//! the exact plaintext document text. Approval binds one revision id to that
//! commitment, and every read re-verifies it against the decrypted document.
use super::*;
use serde::{Deserialize, Serialize};

/// Largest accepted serialized document (the server limit is 4 MiB of ciphertext).
pub const MAX_DOCUMENT_BYTES: usize = 2 * 1024 * 1024;
/// Catalog reference used when the caller names none.
pub const DEFAULT_CATALOG_REVISION: &str = "catalog-1";

/// Included and excluded scope bullets.
#[derive(Clone, Default, Serialize, Deserialize, PartialEq, Debug)]
#[serde(default)]
pub struct SpecScope {
    pub included: Vec<String>,
    pub excluded: Vec<String>,
}
/// One requirement, referenced by chapters through its stable id.
#[derive(Clone, Default, Serialize, Deserialize, PartialEq, Debug)]
#[serde(default, rename_all = "camelCase")]
pub struct SpecRequirement {
    pub id: String,
    pub statement: String,
    pub applies_to: Vec<String>,
    pub example: String,
}
/// A user flow or edge case.
#[derive(Clone, Default, Serialize, Deserialize, PartialEq, Debug)]
#[serde(default, rename_all = "camelCase")]
pub struct SpecFlow {
    pub id: String,
    pub title: String,
    pub kind: String,
    pub steps: Vec<String>,
    pub required_check_refs: Vec<String>,
}
/// A field of a data model.
#[derive(Clone, Default, Serialize, Deserialize, PartialEq, Debug)]
#[serde(default)]
pub struct SpecModelField {
    pub name: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub description: String,
}
/// A data model referenced by chapters.
#[derive(Clone, Default, Serialize, Deserialize, PartialEq, Debug)]
#[serde(default)]
pub struct SpecModel {
    pub id: String,
    pub description: String,
    pub fields: Vec<SpecModelField>,
}
/// A chapter grouping canonical requirements, flows and models by id.
#[derive(Clone, Default, Serialize, Deserialize, PartialEq, Debug)]
#[serde(default, rename_all = "camelCase")]
pub struct SpecChapter {
    pub id: String,
    pub title: String,
    pub introduction: String,
    pub requirement_ids: Vec<String>,
    pub flow_ids: Vec<String>,
    pub model_ids: Vec<String>,
}
/// The readable document, shaped like the web `SpecificationDocument` reader.
#[derive(Clone, Default, Serialize, Deserialize, PartialEq, Debug)]
#[serde(default, rename_all = "camelCase")]
pub struct SpecificationDocument {
    pub title: String,
    pub project: String,
    pub category: String,
    pub summary: String,
    pub outcome: String,
    pub scope: SpecScope,
    pub chapters: Vec<SpecChapter>,
    pub requirements: Vec<SpecRequirement>,
    pub flows: Vec<SpecFlow>,
    pub models: Vec<SpecModel>,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub preview_notice: String,
}
/// Input of `create` and `revise`; ids are client-made and kept for retries.
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct SpecificationInput {
    pub specification_id: Option<String>,
    pub revision_id: Option<String>,
    pub surface_catalog_revision_id: Option<String>,
    pub document: SpecificationDocument,
}

/// Lowercase SHA-256 of the exact plaintext document text (the commitment).
pub fn content_hash(document_text: &str) -> String {
    hash(document_text)
}

impl SpecificationDocument {
    /// Refuses documents the reader cannot resolve.
    pub fn validate(&self) -> Result<()> {
        if self.title.trim().is_empty() || self.summary.trim().is_empty() {
            return Err(Error::Invalid(
                "A Specification needs a title and a summary.",
            ));
        }
        let unique = |ids: Vec<&str>| {
            let set: std::collections::BTreeSet<_> = ids.iter().collect();
            ids.iter().all(|id| !id.is_empty()) && set.len() == ids.len()
        };
        let reqs: Vec<&str> = self.requirements.iter().map(|r| r.id.as_str()).collect();
        let flows: Vec<&str> = self.flows.iter().map(|f| f.id.as_str()).collect();
        let models: Vec<&str> = self.models.iter().map(|m| m.id.as_str()).collect();
        let chapters: Vec<&str> = self.chapters.iter().map(|c| c.id.as_str()).collect();
        if ![&reqs, &flows, &models, &chapters]
            .into_iter()
            .all(|ids| unique(ids.clone()))
        {
            return Err(Error::Invalid(
                "Specification ids must be present and unique.",
            ));
        }
        if self
            .flows
            .iter()
            .any(|f| !matches!(f.kind.as_str(), "user_flow" | "edge_case"))
        {
            return Err(Error::Invalid("Flow kind must be user_flow or edge_case."));
        }
        let known =
            |ids: &[String], from: &[&str]| ids.iter().all(|id| from.contains(&id.as_str()));
        if self.chapters.iter().any(|c| {
            !known(&c.requirement_ids, &reqs)
                || !known(&c.flow_ids, &flows)
                || !known(&c.model_ids, &models)
        }) {
            return Err(Error::Invalid(
                "A chapter references an unknown requirement, flow or model.",
            ));
        }
        Ok(())
    }
}

/// Specification operations in the current Personal or Team scope.
pub struct Specifications<'a> {
    backend: Backend<'a>,
    team: Option<String>,
}
struct Opened {
    head: Value,
    key: Key,
}
impl<'a> Specifications<'a> {
    pub(crate) fn cookie(client: &'a mut Client, team: Option<String>) -> Self {
        Self {
            backend: Backend::Cookie(client),
            team,
        }
    }
    pub(crate) fn api_key(client: &'a mut OpenMates) -> Self {
        Self {
            backend: Backend::ApiKey(client),
            team: None,
        }
    }
    /// Selects the Team scope; `None` keeps Personal.
    pub fn with_team(mut self, team: Option<String>) -> Self {
        self.team = team;
        self
    }
    fn route(&self, project: &str, suffix: &str, params: &[(String, String)]) -> Result<String> {
        uuid(project)?;
        if let Some(team) = &self.team {
            uuid(team)?;
        }
        Ok(path(
            &format!("/v1/projects/{project}/specifications{suffix}"),
            self.team.as_deref(),
            params,
        ))
    }
    async fn project_key(&mut self, project: &str) -> Result<Key> {
        uuid(project)?;
        let route = path(
            &format!("/v1/projects/{project}"),
            self.team.as_deref(),
            &[],
        );
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let row = &data["project"];
        if row["project_id"] != project {
            return Err(Error::Forbidden);
        }
        if self.team.is_none()
            && let Backend::ApiKey(client) = &mut self.backend
            && let Some(key) = client.project_grant_key(project).await?
        {
            return Ok(key);
        }
        let wrapping = self.backend.wrapping(self.team.as_deref()).await?;
        super::projects::project_key(row, &wrapping, self.team.as_deref())
    }
    /// Unwraps the Specification key with the exact Project wrapper.
    fn spec_key(head: &Value, project: &str, project_key: &[u8; 32]) -> Result<Key> {
        let wanted = hash(project);
        let rows: Vec<&Value> = head["key_wrappers"]
            .as_array()
            .ok_or(Error::Forbidden)?
            .iter()
            .filter(|w| w["key_type"] == "project" && w["hashed_project_id"] == wanted)
            .collect();
        if rows.len() != 1 {
            return Err(Error::Forbidden);
        }
        key_bytes(&crypto::server_fields::decrypt_bytes(
            string(rows[0], "encrypted_specification_key")?,
            project_key,
            &[],
        )?)
    }
    async fn open(&mut self, project: &str, head: Value) -> Result<Opened> {
        let project_key = self.project_key(project).await?;
        let key = Self::spec_key(&head, project, &project_key)?;
        Ok(Opened { head, key })
    }
    fn text(raw: &Value, field: &str, key: &[u8; 32]) -> Result<String> {
        crypto::server_fields::decrypt_text(string(raw, field)?, key, &[])
    }
    fn head_view(opened: &Opened) -> Result<Value> {
        let h = &opened.head;
        Ok(json!({
            "specification_id": h["specification_id"], "status": h["status"],
            "current_revision_id": h["current_revision_id"],
            "current_revision_number": h["current_revision_number"],
            "version": h["version"], "created_at": h["created_at"], "updated_at": h["updated_at"],
            "title": Self::text(h, "encrypted_title", &opened.key)?,
            "summary": Self::text(h, "encrypted_summary", &opened.key)?,
        }))
    }
    fn revision_view(raw: &Value, key: &[u8; 32], with_document: bool) -> Result<Value> {
        let mut view = json!({
            "revision_id": raw["revision_id"], "revision_number": raw["revision_number"],
            "content_hash": raw["content_hash"], "approval_state": raw["approval_state"],
            "approved_at": raw["approved_at"], "created_at": raw["created_at"],
            "supersedes_revision_id": raw["supersedes_revision_id"],
            "project_surface_catalog_revision_id": raw["project_surface_catalog_revision_id"],
            "title": Self::text(raw, "encrypted_title", key)?,
            "summary": Self::text(raw, "encrypted_summary", key)?,
        });
        if with_document {
            let text = Self::text(raw, "encrypted_specification_document", key)?;
            if content_hash(&text) != string(raw, "content_hash")? {
                return Err(Error::Conflict);
            }
            let document: SpecificationDocument =
                serde_json::from_str(&text).map_err(|_| Error::Protocol)?;
            view["document"] = serde_json::to_value(document)?;
        }
        Ok(view)
    }
    /// Lists Specification heads of one Project (first page, newest first).
    pub async fn list(
        &mut self,
        project: &str,
        limit: u8,
        after: Option<&str>,
    ) -> Result<Vec<Value>> {
        let mut params = vec![("limit".to_owned(), limit.clamp(1, 100).to_string())];
        if let Some(after) = after {
            params.push(("after".into(), uuid(after)?.to_owned()));
        }
        let route = self.route(project, "", &params)?;
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let rows = data["specifications"]
            .as_array()
            .ok_or(Error::Protocol)?
            .clone();
        let project_key = self.project_key(project).await?;
        rows.into_iter()
            .map(|head| {
                let key = Self::spec_key(&head, project, &project_key)?;
                Self::head_view(&Opened { head, key })
            })
            .collect()
    }
    /// Reads the head and one exact revision (current when `revision` is `None`).
    pub async fn show(&mut self, project: &str, id: &str, revision: Option<&str>) -> Result<Value> {
        uuid(id)?;
        let mut params = vec![];
        if let Some(rev) = revision {
            params.push(("revision_id".to_owned(), uuid(rev)?.to_owned()));
        }
        let route = self.route(project, &format!("/{id}"), &params)?;
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        if data["specification"]["specification_id"] != id {
            return Err(Error::Forbidden);
        }
        if let Some(rev) = revision
            && data["revision"]["revision_id"] != rev
        {
            return Err(Error::Forbidden);
        }
        let opened = self.open(project, data["specification"].clone()).await?;
        Ok(json!({
            "specification": Self::head_view(&opened)?,
            "revision": Self::revision_view(&data["revision"], &opened.key, true)?,
        }))
    }
    /// Revision history, newest first (titles and summaries only).
    pub async fn revisions(
        &mut self,
        project: &str,
        id: &str,
        limit: u8,
        before: Option<u64>,
    ) -> Result<Vec<Value>> {
        let head = self.show_head(project, id).await?;
        let mut params = vec![("limit".to_owned(), limit.clamp(1, 100).to_string())];
        if let Some(before) = before {
            params.push(("before".into(), before.to_string()));
        }
        let route = self.route(project, &format!("/{id}/revisions"), &params)?;
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        data["revisions"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|raw| Self::revision_view(raw, &head.key, false))
            .collect()
    }
    async fn show_head(&mut self, project: &str, id: &str) -> Result<Opened> {
        uuid(id)?;
        let route = self.route(project, &format!("/{id}"), &[])?;
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        if data["specification"]["specification_id"] != id {
            return Err(Error::Forbidden);
        }
        self.open(project, data["specification"].clone()).await
    }
    fn revision_body(input: &SpecificationInput, key: &[u8; 32]) -> Result<(Value, String)> {
        input.document.validate()?;
        let text = serde_json::to_string(&input.document)?;
        if text.len() > MAX_DOCUMENT_BYTES {
            return Err(Error::Invalid("The Specification document is too large."));
        }
        let revision = match &input.revision_id {
            Some(id) => uuid(id)?.to_owned(),
            None => uuid::Uuid::new_v4().to_string(),
        };
        let catalog = input
            .surface_catalog_revision_id
            .clone()
            .unwrap_or_else(|| DEFAULT_CATALOG_REVISION.into());
        let seal = |value: &str| crypto::server_fields::encrypt_text(value, key, &[]);
        Ok((
            json!({
                "revision_id": revision, "content_hash": content_hash(&text),
                "project_surface_catalog_revision_id": catalog,
                "encrypted_title": seal(input.document.title.trim())?,
                "encrypted_summary": seal(input.document.summary.trim())?,
                "encrypted_specification_document": seal(&text)?,
            }),
            revision,
        ))
    }
    /// Creates a Specification with its first draft revision.
    pub async fn create(&mut self, project: &str, input: SpecificationInput) -> Result<Value> {
        let id = match &input.specification_id {
            Some(id) => uuid(id)?.to_owned(),
            None => uuid::Uuid::new_v4().to_string(),
        };
        let project_key = self.project_key(project).await?;
        let key = crypto::random_key();
        let (mut body, revision) = Self::revision_body(&input, &key)?;
        let wrap =
            |wrapping: &[u8; 32]| crypto::server_fields::encrypt_bytes(key.as_ref(), wrapping, &[]);
        let mut wrappers = vec![
            json!({"key_type":"project","hashed_project_id":hash(project),"encrypted_specification_key":wrap(&project_key)?}),
        ];
        match &self.team {
            Some(team) => {
                let team_key = self.backend.wrapping(Some(team)).await?;
                wrappers.push(json!({"key_type":"team","hashed_team_id":hash(team),"team_key_epoch":1,"encrypted_specification_key":wrap(&team_key)?}));
            }
            None => {
                let master = self.backend.master().await?;
                wrappers.push(
                    json!({"key_type":"master","encrypted_specification_key":wrap(&master)?}),
                );
            }
        }
        body["specification_id"] = json!(id);
        body["key_wrappers"] = json!(wrappers);
        let route = self.route(project, "", &[])?;
        let data = self
            .backend
            .request(Method::POST, &route, Some(body), None)
            .await?;
        self.written(project, &id, &revision, data).await
    }
    /// Adds a draft revision on top of `base_revision`; a stale base is a conflict.
    pub async fn revise(
        &mut self,
        project: &str,
        id: &str,
        base_revision: &str,
        input: SpecificationInput,
    ) -> Result<Value> {
        uuid(id)?;
        let head = self.show_head(project, id).await?;
        let (mut body, revision) = Self::revision_body(&input, &head.key)?;
        body["base_revision_id"] = json!(uuid(base_revision)?);
        let route = self.route(project, &format!("/{id}/revisions"), &[])?;
        let data = self
            .backend
            .request(Method::POST, &route, Some(body), None)
            .await?;
        self.written(project, id, &revision, data).await
    }
    /// Approves one exact revision; refuses when its content no longer matches the commitment.
    pub async fn approve(&mut self, project: &str, id: &str, revision: &str) -> Result<Value> {
        let current = self.show(project, id, Some(revision)).await?;
        let hash = string(&current["revision"], "content_hash")?.to_owned();
        let route = self.route(project, &format!("/{id}/approve"), &[])?;
        let body = json!({"revision_id": revision, "content_hash": hash});
        let data = self
            .backend
            .request(Method::POST, &route, Some(body), None)
            .await?;
        self.written(project, id, revision, data).await
    }
    async fn written(
        &mut self,
        project: &str,
        id: &str,
        revision: &str,
        data: Value,
    ) -> Result<Value> {
        if data["specification"]["specification_id"] != id
            || data["revision"]["revision_id"] != revision
        {
            return Err(Error::Forbidden);
        }
        let opened = self.open(project, data["specification"].clone()).await?;
        let mut out = json!({
            "specification": Self::head_view(&opened)?,
            "revision": Self::revision_view(&data["revision"], &opened.key, true)?,
        });
        if let Some(replayed) = data.get("replayed") {
            out["replayed"] = replayed.clone();
        }
        Ok(out)
    }
}
#[cfg(test)]
#[path = "specifications_tests.rs"]
mod tests;
