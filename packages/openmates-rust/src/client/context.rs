//! Fresh owner-scoped Project routing, selected encrypted context documents
//! and the active Project's Memories (`project_memories`) for one send.
use super::sync::decrypt_optional;
use super::sync_capability::AsyncCryptoScope;
use super::plaintext::Plain;
use super::*;
impl Client {
    pub(super) async fn decode_project_candidates(&self, rows: &[Value]) -> Result<Vec<Value>> {
        if rows.len() > 40 {
            return Err(Error::Protocol);
        }
        self.require_canonical_read_profile()?;
        let scope = AsyncCryptoScope::begin(self)?;
        let master = self.master_capability()?;
        let mut seen = std::collections::HashSet::new();
        let mut out = ContextValues::default();
        for row in rows {
            let id = required(row, "project_id")?;
            uuid::Uuid::parse_str(id).map_err(|_| Error::Protocol)?;
            if !seen.insert(id)
                || row["auto_selection"] != true
                || !["delayed", "immediate", "approval"]
                    .contains(&text(row, "focus_activation_policy"))
            {
                return Err(Error::Protocol);
            }
            scope.check(self)?;
            let unwrapped = master.decrypt_bytes(required(row, "encrypted_project_key")?).await;
            scope.check(self)?;
            let key = key_from_bytes(&unwrapped?)?;
            let name = zeroize::Zeroizing::new(crypto::decrypt_combined(required(row, "encrypted_name")?, &key)?);
            let summary = zeroize::Zeroizing::new(decrypt_optional(row, "encrypted_description", &key)?);
            out.push(json!({"project_id":id,"name":truncate(&name,160),"summary":truncate(&summary,640),"auto_selection":true,"focus_activation_policy":row["focus_activation_policy"]}));
        }
        scope.check(self)?;
        Ok(std::mem::take(&mut out.0))
    }
    pub(super) async fn project_routing_catalog(&mut self, id: &str) -> Result<Vec<Value>> {
        self.require_canonical_read_profile()?;
        let scope = AsyncCryptoScope::begin(self)?;
        let path = self.scoped(&format!("/v1/projects/{}", segment(id)))?;
        let detail = self.context_request(&scope, None, Method::GET, &path, None).await?;
        let project = &detail["project"];
        if text(project, "project_id") != id || project["archived"] == true {
            return Err(Error::Forbidden);
        }
        let wrapping = self.wrapping_capability().await;
        scope.check(self)?;
        let key = self.object_key_with_capability(Workspace::Projects, project, &wrapping?, &scope).await?;
        scope.check(self)?;
        let out=Plain::new(project_catalogue_items(&detail,&key)?);
        scope.check(self)?;
        Ok(out.into_inner())
    }
    pub(super) async fn active_project_context(
        &mut self,
        chat_id: &str,
        message: &str,
    ) -> Result<Value> {
        self.require_canonical_read_profile()?;
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, chat_id)?;
        let active = self.current_project_focus(&scope, chat_id).await?;
        if active.is_null() {
            return Ok(json!({}));
        }
        let id = required(&active, "project_id")?.to_owned();
        if active.get("team_id").and_then(Value::as_str) != self.team()? {
            return Err(Error::Forbidden);
        }
        let detail_path = self.scoped(&format!("/v1/projects/{}", segment(&id)))?;
        let detail = self.context_request(&scope, Some(chat_id), Method::GET, &detail_path, None).await?;
        let wrapping = self.wrapping_capability().await;
        scope.check_chat(self, chat_id)?;
        let key = self.object_key_with_capability(Workspace::Projects, &detail["project"], &wrapping?, &scope).await?;
        scope.check_chat(self, chat_id)?;
        let mut candidates = ContextValues::default();
        let mut catalog = ContextValues::default();
        let mut targets = BTreeMap::new();
        let mut memory_rows = Vec::new();
        for row in detail["items"].as_array().ok_or(Error::Protocol)? {
            if !["embed", "upload"].contains(&text(row, "item_type"))
                || text(row, "encrypted_metadata").is_empty()
                || !row["deleted_target_state"].is_null()
            {
                continue;
            }
            let plaintext = zeroize::Zeroizing::new(crypto::decrypt_combined(required(row, "encrypted_metadata")?, &key)?);
            let metadata = ContextValue(serde_json::from_str(&plaintext)?);
            let path = metadata
                .get("path")
                .or_else(|| metadata.get("display_path"))
                .and_then(Value::as_str)
                .unwrap_or("");
            let parts: Vec<_> = path.split('/').collect();
            if parts.len() < 3
                || parts[0] != ".openmates"
                || parts
                    .iter()
                    .any(|s| s.is_empty() || *s == "." || *s == ".." || s.contains('\0'))
                || !(path.ends_with(".md") || path.ends_with("/SKILL.md"))
            {
                continue;
            }
            // Project Memories are sent whole, not chosen by relevance (web
            // `collectCustomRuleDocuments`); they never become selection candidates.
            if super::project_memories::is_project_memory_path(path) {
                let item_id = required(row, "project_item_id")?.to_owned();
                memory_rows.push(super::project_memories::ProjectMemoryRow{item_id,row:row.clone(),revision:revision(row),path:path.to_owned()});
                continue;
            }
            let kind = match parts[1] {
                "focuses" => "focus",
                "memories" | "facts" => "memory",
                "rules" => "rule",
                "specs" => "spec",
                _ => continue,
            };
            let title = metadata
                .get("focus_title")
                .or_else(|| metadata.get("title"))
                .or_else(|| metadata.get("name"))
                .and_then(Value::as_str);
            let desc = metadata
                .get("focus_description")
                .or_else(|| metadata.get("summary"))
                .or_else(|| metadata.get("description"))
                .and_then(Value::as_str);
            let (Some(title), Some(desc)) = (title, desc) else {
                continue;
            };
            let item_id = required(row, "project_item_id")?;
            let rev = revision(row);
            if kind == "focus" && catalog.len() < 20 {
                catalog.push(json!({"id":item_id,"title":truncate(title,200),"summary":truncate(desc,640),"revision":rev}))
            }
            candidates.push(json!({"kind":kind,"id":item_id,"title":truncate(title,200),"description":truncate(desc,640),"when_to_use":truncate(text(&metadata,"focus_when_to_use"),640),"revision":rev}));
            targets.insert(item_id.to_owned(), row.clone());
        }
        for row in detail["folders"].as_array().ok_or(Error::Protocol)? {
            let title = zeroize::Zeroizing::new(decrypt_optional(row, "encrypted_name", &key)?);
            let description = zeroize::Zeroizing::new(decrypt_optional(row, "encrypted_description", &key)?);
            if !title.is_empty() && !description.is_empty() {
                candidates.push(json!({"kind":"folder","id":required(row,"folder_id")?,"title":truncate(&title,200),"description":truncate(&description,640),"when_to_use":"","revision":revision(row)}));
            }
        }
        let mut selected = ContextValues::default();
        if !candidates.is_empty() {
            let path = self.scoped(&format!("/v1/projects/{}/context/select", segment(&id)))?;
            let result=ContextValue(self.context_request(&scope,Some(chat_id),Method::POST,&path,Some(json!({"chat_id":chat_id,"text":truncate(message,8000),"candidates":candidates.iter().take(24).collect::<Vec<_>>()}))).await?);
            selected.0 = result["selected"]
                .as_array()
                .or_else(|| result["items"].as_array())
                .cloned()
                .ok_or(Error::Protocol)?;
        }
        let specialist = text(&active, "specialist_focus_id");
        let specialist = specialist
            .strip_prefix(&format!("project-focus:{id}:"))
            .unwrap_or(specialist);
        if let Some(row) = candidates
            .iter()
            .find(|v| text(v, "kind") == "focus" && text(v, "id") == specialist)
            && !selected.iter().any(|v| v["id"] == row["id"])
        {
            selected.push(row.clone())
        }
        let mut focus_docs = ContextValues::default();
        let mut context_docs = ContextValues::default();
        let mut rules = ContextValues::default();
        let mut chars = 0;
        for choice in selected.iter().take(5) {
            let Some(candidate) = candidates.iter().find(|v| {
                v["id"] == choice["id"]
                    && v["kind"] == choice["kind"]
                    && v["revision"] == choice["revision"]
            }) else {
                continue;
            };
            if self.current_project_focus(&scope, chat_id).await? != active {
                return Err(Error::Cancelled);
            }
            let kind = text(candidate, "kind");
            let item_id = text(candidate, "id");
            let doc = zeroize::Zeroizing::new(if kind == "folder" {
                let row = detail["folders"]
                    .as_array()
                    .ok_or(Error::Protocol)?
                    .iter()
                    .find(|r| text(r, "folder_id") == item_id)
                    .ok_or(Error::Protocol)?;
                decrypt_optional(row, "encrypted_description", &key)?
            } else {
                let row = targets.get(item_id).ok_or(Error::Protocol)?;
                let embed = zeroize::Zeroizing::new(crypto::decrypt_combined(required(row, "target_id_encrypted")?, &key)?);
                scope.check_chat(self, chat_id)?;
                let result = self.read_project_document(&id, &embed, &key).await;
                scope.check_chat(self, chat_id)?;
                let content = ContextValue(result?);
                ["code", "content", "markdown", "text"]
                    .into_iter()
                    .find_map(|k| content[k].as_str())
                    .ok_or(Error::Protocol)?
                    .to_owned()
            });
            if doc.len() > if kind == "focus" { 60_000 } else { 24_000 }
                || chars + doc.len() > 64_000
            {
                continue;
            }
            chars += doc.len();
            match kind{"focus"=>focus_docs.push(json!({"item_id":item_id,"document":doc.as_str(),"revision":candidate["revision"]})),"rule"=>rules.push(json!({"id":item_id,"source":"project","project_id":id,"document":doc.as_str(),"item_revision":candidate["revision"]})),_=>context_docs.push(json!({"item_id":item_id,"kind":kind,"title":candidate["title"],"description":candidate["description"],"document":doc.as_str(),"revision":candidate["revision"]}))}
        }
        if !memory_rows.is_empty() {
            if self.current_project_focus(&scope, chat_id).await? != active {
                return Err(Error::Cancelled);
            }
            let loaded = self.project_memory_documents(&scope, chat_id, &id, memory_rows, &key).await?;
            rules.0.extend(loaded);
        }
        if self.current_project_focus(&scope, chat_id).await? != active {
            return Err(Error::Cancelled);
        }
        let fresh = self.context_request(&scope, Some(chat_id), Method::GET, &detail_path, None).await?;
        let unchanged = |doc: &Value, id_field: &str, rev_field: &str| -> bool {
            fresh["items"]
                .as_array()
                .into_iter()
                .flatten()
                .chain(fresh["folders"].as_array().into_iter().flatten())
                .any(|row| {
                    (text(row, "project_item_id") == text(doc, id_field)
                        || text(row, "folder_id") == text(doc, id_field))
                        && revision(row) == text(doc, rev_field)
                })
        };
        focus_docs.retain(|d| unchanged(d, "item_id", "revision"));
        context_docs.retain(|d| unchanged(d, "item_id", "revision"));
        rules.retain(|d| unchanged(d, "id", "item_revision"));
        let mut result = ContextValue(json!({"active_focus_id":active["focus_id"],"project_focus_catalog":&catalog.0,"project_focus_documents":&focus_docs.0,"project_context_documents":&context_docs.0,"custom_memory_documents":&rules.0}));
        scope.check_chat(self, chat_id)?;
        Ok(std::mem::take(&mut result.0))
    }
    pub(super) async fn read_project_document(
        &mut self,
        project: &str,
        embed: &str,
        key: &[u8; 32],
    ) -> Result<Value> {
        self.require_canonical_read_profile()?;
        let scope = AsyncCryptoScope::begin(self)?;
        let path = self.scoped(&format!(
            "/v1/embeds/{}/encrypted?project_id={}",
            segment(embed),
            segment(project)
        ))?;
        let data = self.context_request(&scope, None, Method::GET, &path, None).await?;
        let wrapper = data["embed_keys"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .find(|w| text(w, "key_type") == "project")
            .ok_or(Error::Forbidden)?;
        let embed_key = key_from_bytes(&crypto::decrypt_bytes(
            required(wrapper, "encrypted_embed_key")?,
            key,
        )?)?;
        let plain = zeroize::Zeroizing::new(crypto::decrypt_combined(required(&data["embed"], "encrypted_content")?, &embed_key)?);
        let mut value = ContextValue(super::toon::decode(&plain)?);
        scope.check(self)?;
        Ok(std::mem::take(&mut value.0))
    }
    fn context_request<'a>(&'a mut self,scope:&'a AsyncCryptoScope,chat:Option<&'a str>,method:Method,path:&'a str,body:Option<Value>)->impl std::future::Future<Output=Result<Value>>+'a {
        // Own before first poll; every plaintext HTTP body enters the guarded
        // transport seam without an ordinary serializer across suspension.
        let body=Plain::new(body);
        async move {
            let check=|client:&Client|match chat{Some(id)=>scope.check_chat(client,id),None=>scope.check(client)};
            check(self)?;
            let result=match body.into_inner(){Some(body)=>self.request_plaintext(method,path,body).await.map(ContextValue),None=>self.request(method,path,None).await.map(ContextValue)};
            match result{
                Err(error @ (Error::Expired|Error::Forbidden|Error::Authentication|Error::Cancelled))=>Err(error),
                other=>{check(self)?;let mut value=other?;Ok(std::mem::take(&mut value.0))}
            }
        }
    }
    async fn current_project_focus(&mut self, scope: &AsyncCryptoScope, chat: &str) -> Result<Value> {
        let response = self
            .context_request(
                scope, Some(chat), Method::GET,
                &format!("/v1/projects/focus/current?chat_id={}", segment(chat)),
                None,
            )
            .await?;
        response.get("focus").cloned().ok_or(Error::Protocol)
    }
}
// Same deterministic focus-path/filter/projection for borrowed and owned reads.
pub(in crate::client) fn project_catalogue_items(detail:&Value,key:&[u8;32])->Result<Vec<Value>> {
        let mut out = ContextValues::default();
        for row in detail["items"].as_array().ok_or(Error::Protocol)? {
            if !["embed", "upload"].contains(&text(row, "item_type"))
                || text(row, "target_id_hash").is_empty()
                || !row["deleted_target_state"].is_null()
                || text(row, "encrypted_metadata").is_empty()
            {
                continue;
            }
            let plaintext = zeroize::Zeroizing::new(crypto::decrypt_combined(required(row, "encrypted_metadata")?, &key)?);
            let metadata = ContextValue(serde_json::from_str(&plaintext)?);
            let path = text(&metadata, "display_path");
            let parts: Vec<_> = path.split('/').collect();
            if parts.len() != 4
                || parts[0] != ".openmates"
                || parts[1] != "focuses"
                || parts[3] != "SKILL.md"
                || parts[2].is_empty()
                || !parts[2]
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
            {
                continue;
            }
            let title = required(&metadata, "focus_title")?;
            let description = required(&metadata, "focus_description")?;
            let when = metadata
                .get("focus_when_to_use")
                .and_then(Value::as_str)
                .ok_or(Error::Protocol)?;
            out.push(json!({"item_id":required(row,"project_item_id")?,"revision":revision(row),"title":truncate(title,180),"description":truncate(description,640),"when_to_use":truncate(when,640)}));
            if out.len() == 20 {
                break;
            }
        }
    Ok(std::mem::take(&mut out.0))
}
fn truncate(value: &str, max: usize) -> String {
    value.chars().take(max).collect()
}
fn revision(row: &Value) -> String {
    let parts = [
        "updated_at",
        "encrypted_metadata",
        "encrypted_note",
        "target_id_hash",
        "deleted_target_state",
    ]
    .map(|key| match row.get(key) {
        None | Some(Value::Null) => String::new(),
        Some(Value::String(s)) => s.clone(),
        Some(v) if v == &json!(false) || v == &json!(0) => String::new(),
        Some(v) => v.to_string(),
    });
    sha256(&parts.join("\0"))
}

struct ContextValue(Value);
impl std::ops::Deref for ContextValue { type Target=Value; fn deref(&self)->&Value { &self.0 } }
impl Drop for ContextValue { fn drop(&mut self) { crate::model::zeroize_json(&mut self.0); } }
#[derive(Default)]
struct ContextValues(Vec<Value>);
impl std::ops::Deref for ContextValues { type Target=Vec<Value>; fn deref(&self)->&Vec<Value> { &self.0 } }
impl std::ops::DerefMut for ContextValues { fn deref_mut(&mut self)->&mut Vec<Value> { &mut self.0 } }
impl ContextValues {
    fn wipe(&mut self){for value in &mut self.0{crate::model::zeroize_json(value);}}
    fn retain(&mut self,mut keep:impl FnMut(&Value)->bool){self.0.retain_mut(|value|{if keep(value){true}else{crate::model::zeroize_json(value);false}});}
}
impl Drop for ContextValues { fn drop(&mut self) { self.wipe(); } }
#[cfg(all(test, not(target_arch = "wasm32")))]
#[path="context_capability_tests.rs"]
mod capability_tests;
