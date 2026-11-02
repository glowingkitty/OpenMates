use super::sync::decrypt_optional;
use super::*;
use super::sync_capability::{AsyncCryptoScope,PlainItems,wipe_item};
use crate::crypto::master::MasterCapability;
use super::plaintext::Plain;
impl Client {
    /// Reuse only an SDK-issued inventory that still matches this exact Client,
    /// context, credentials and ciphertext. Any stale/unsupported proof takes
    /// the existing list path, including its authentication and sync behavior.
    pub async fn list_with_fresh_chat_inventory(
        &mut self,
        workspace: Workspace,
        proof: FreshChatInventory,
        cancel: &CancellationToken,
    ) -> Result<Vec<Item>> {
        self.require_canonical_read_profile()?;
        if cancel.is_cancelled() || self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if workspace == Workspace::Chats && self.chat_inventory_is_current(&proof)? {
            let items = Plain::new(self.render_chat_inventory_with_capability().await?);
            if cancel.is_cancelled() || !self.chat_inventory_is_current(&proof)? {
                return Err(Error::Cancelled);
            }
            self.require_canonical_read_profile()?;
            self.record_complete_chat_list(&proof);
            return Ok(items.into_inner());
        }
        tokio::select! {
            biased;
            _ = cancel.cancelled() => Err(Error::Cancelled),
            result = self.list(workspace) => result,
        }
    }

    pub async fn list(&mut self, workspace: Workspace) -> Result<Vec<Item>> {
        self.require_canonical_read_profile()?;
        match workspace {
            Workspace::Chats => match self.sync_chats().await {
                Err(Error::Offline) if !self.chats.is_empty() => {self.require_canonical_read_profile()?;self.cached_chats_with_capability().await},
                result => result,
            },
            Workspace::Tasks => self.list_tasks().await,
            Workspace::Settings => {
                self.validate_session_for_request().await?;
                self.require_canonical_read_profile()?;
                let scope=AsyncCryptoScope::begin(self)?;let mut items=PlainItems(self.settings_items());scope.check(self)?;
                Ok(std::mem::take(&mut items.0))
            }
            Workspace::Apps => {
                let data = self
                    .request(
                        Method::GET,
                        "/v1/apps/metadata?include_unavailable=true",
                        None,
                    )
                    .await?;
                if !data.is_array(){data.get("apps").ok_or(Error::Protocol)?;}
                let scope=AsyncCryptoScope::begin(self)?;
                let mut output=PlainItems(app_inventory_items(&data)?);
                self.require_canonical_read_profile()?;scope.check(self)?;
                Ok(std::mem::take(&mut output.0))
            }
            Workspace::Projects | Workspace::Workflows => {
                let kind = if workspace == Workspace::Projects {
                    "projects"
                } else {
                    "workflows"
                };
                let path = self.scoped(&format!("/v1/{kind}"))?;
                let data = self.request(Method::GET, &path, None).await?;
                let rows = data[kind].as_array().ok_or(Error::Protocol)?;
                let wrapping = self.wrapping_capability().await?;
                let scope=AsyncCryptoScope::begin(self)?;let mut output=PlainItems(vec![]);
                for row in rows{output.0.push(self.object_item_with_capability(workspace,row,&wrapping,&scope).await?);}
                self.require_canonical_read_profile()?;scope.check(self)?;
                Ok(std::mem::take(&mut output.0))
            }
        }
    }
    pub async fn detail(&mut self, workspace: Workspace, id: &str) -> Result<Item> {
        self.require_canonical_read_profile()?;
        if workspace == Workspace::Chats {
            let mut chat = Plain::new(self.open_chat(id).await?);
            let scope=AsyncCryptoScope::begin(self)?;
            let mut item=Plain::new(Item::default());
            item.id=std::mem::take(&mut chat.id);item.title=std::mem::take(&mut chat.title);item.category=std::mem::take(&mut chat.category);item.fields=serde_json::to_value(&chat.messages)?;
            self.require_canonical_read_profile()?;scope.check(self)?;
            return Ok(item.into_inner());
        }
        if workspace == Workspace::Settings {
            self.validate_session_for_request().await?;
            self.require_canonical_read_profile()?;
            let scope=AsyncCryptoScope::begin(self)?;let mut items=PlainItems(self.settings_items());
            let index=items.0.iter().position(|item|item.id==id).ok_or(Error::Invalid("Unknown settings section."))?;
            scope.check(self)?;
            return Ok(items.0.remove(index));
        }
        if workspace == Workspace::Apps {
            if let Some(id) = id.strip_prefix("embed:") {
                return self.embed_detail(id).await;
            }
            if let Some(title) = id.strip_prefix("wiki:") {
                return self.wiki_detail(title).await;
            }
        }
        if workspace == Workspace::Apps {
            return self.app_detail(id).await;
        }
        let (path, field) = match workspace {
            Workspace::Tasks => (format!("/v1/user-tasks/{}", segment(id)), "task"),
            Workspace::Projects => (format!("/v1/projects/{}", segment(id)), "project"),
            Workspace::Workflows => (format!("/v1/workflows/{}", segment(id)), "workflow"),
            _ => unreachable!(),
        };
        let path = self.scoped(&path)?;
        let data = self.request(Method::GET, &path, None).await?;
        let row = data.get(field).ok_or(Error::Protocol)?.clone();
        let wrapping = self.wrapping_capability().await?;
        let scope=AsyncCryptoScope::begin(self)?;
        let mut item=Plain::new(self.object_item_with_capability(workspace,&row,&wrapping,&scope).await?);
        if workspace == Workspace::Projects {
            let key = self.object_key_with_capability(workspace,&row,&wrapping,&scope).await?;
            let mut files = Plain::new(vec![]);
            for folder in data["folders"].as_array().into_iter().flatten() {
                let name=Plain::new(decrypt_optional(folder,"encrypted_name",&key)?);
                files.push(json!({"name":name.as_str(),"kind":"folder","folder_id":folder["folder_id"]}));
            }
            for child in data["items"].as_array().into_iter().flatten() {
                let target=Plain::new(decrypt_optional(child,"target_id_encrypted",&key)?);
                let name=Plain::new(decrypt_optional(child,"encrypted_display_name",&key)?);
                let metadata=Plain::new(decrypt_optional(child,"encrypted_metadata",&key)?);
                let metadata=Plain::new(if metadata.is_empty(){json!({})}else{serde_json::from_str::<Value>(&metadata)?});
                let note=Plain::new(decrypt_optional(child,"encrypted_note",&key)?);
                let kind = text(child, "item_type");
                files.push(json!({"name":name.as_str(),"path":metadata.get("path").or_else(||metadata.get("file_path")).cloned().unwrap_or(Value::Null),"kind":kind,"embedId":if ["embed","upload"].contains(&kind){target.as_str()}else{""},"target_id":target.as_str(),"metadata":&*metadata,"note":note.as_str()}));
            }
            item.fields["files"] = Value::Array(files.into_inner());
            item.fields["mutation_permissions"] = row["mutation_permissions"].clone();
        }
        if workspace == Workspace::Workflows {
            let result = self
                .request(
                    Method::GET,
                    &format!("/v1/workflows/{}/runs", segment(id)),
                    None,
                )
                .await?;
            item.fields["runs"] = result["runs"].clone();
        }
        self.require_canonical_read_profile()?;scope.check(self)?;
        Ok(item.into_inner())
    }
    fn settings_items(&self) -> Vec<Item> {
        [("language","Language","text",self.user.get("language").cloned().unwrap_or(json!("en"))),("timezone","Timezone","text",self.user.get("timezone").cloned().unwrap_or(json!("UTC"))),("darkmode","Dark mode","boolean",self.user.get("darkmode").cloned().unwrap_or(json!(false)))].into_iter().map(|(id,title,kind,value)|Item{id:id.into(),title:title.into(),fields:json!({"parent":"interface","fields":[{"key":"value","label":title,"type":kind}],"values":{"value":value}}),..Item::default()}).collect()
    }
    pub(super) fn object_key(&self,workspace:Workspace,row:&Value,wrapping:&[u8;32])->Result<Key>{
        let encrypted=self.object_key_ciphertext(workspace,row)?;
        key_from_bytes(&crypto::decrypt_bytes(encrypted,wrapping)?)
    }
    // One selector owns Personal/Team wrapper choice and shape checks for both
    // existing native bytes and genuine opaque capabilities.
    pub(in crate::client) fn object_key_ciphertext<'a>(&self,workspace:Workspace,row:&'a Value)->Result<&'a str>{
        let (field, id_field) = match workspace {
            Workspace::Tasks => ("encrypted_task_key", "task_id"),
            Workspace::Projects => ("encrypted_project_key", "project_id"),
            _ => return Err(Error::Protocol),
        };
        required(row, id_field)?;
        let encrypted = if let Some(team) = self.team()? {
            let hash = sha256(team);
            if row
                .get("hashed_team_id")
                .and_then(Value::as_str)
                .is_some_and(|h| h != hash)
            {
                return Err(Error::Forbidden);
            }
            let wrapper = row["key_wrappers"]
                .as_array()
                .ok_or(Error::Forbidden)?
                .iter()
                .find(|w| {
                    text(w, "key_type") == "team"
                        && text(w, "hashed_team_id") == hash
                        && w["team_key_epoch"] == 1
                })
                .ok_or(Error::Forbidden)?;
            required(wrapper, field)?
        } else {
            if row
                .get("hashed_team_id")
                .and_then(Value::as_str)
                .is_some_and(|h| !h.is_empty())
            {
                return Err(Error::Forbidden);
            }
            required(row, field)?
        };
        Ok(encrypted)
    }
    fn object_item(&self, workspace: Workspace, row: &Value, wrapping: &[u8; 32]) -> Result<Item> {
        if workspace == Workspace::Workflows {
            let mut item=Plain::new(public_item(row,workspace)?);
            let slug=Plain::new(decrypt_optional(row,"encrypted_slug",wrapping)?);
            item.fields["slug"]=json!(slug.as_str());
            return Ok(item.into_inner());
        }
        if workspace == Workspace::Tasks && text(row,"source")=="workflow_run" {return Self::workflow_run_item(row);}
        let key = self.object_key(workspace, row, wrapping)?;
        self.object_item_from_key(workspace,row,&key)
    }
    fn workflow_run_item(row:&Value)->Result<Item>{
        Ok(Item {
                id: required(row, "task_id")?.into(),
                title: if text(row, "title").is_empty() {
                    "Workflow run"
                } else {
                    text(row, "title")
                }
                .into(),
                description: text(row, "blocked_message").into(),
                status: text(row, "status").into(),
                fields: json!({"read_only":true,"workflow_run_id":row["workflow_run_id"],"source":"workflow_run","position":row["position"]}),
                ..Item::default()
            })
    }
    fn object_item_from_key(&self,workspace:Workspace,row:&Value,key:&[u8;32])->Result<Item>{
        let title_field = if workspace == Workspace::Projects {
            "encrypted_name"
        } else {
            "encrypted_title"
        };
        let id_field = if workspace == Workspace::Projects {
            "project_id"
        } else {
            "task_id"
        };
        let mut item=Plain::new(Item{id:required(row,id_field)?.into(),..Item::default()});
        let title=Plain::new(decrypt_optional(row,title_field,key)?);
        item.title=if workspace==Workspace::Tasks&&title.is_empty(){"(untitled task)".into()}else{title.into_inner()};
        item.description=decrypt_optional(row,"encrypted_description",key)?;
        item.status=text(row,"status").into();item.category=workspace.label().into();
        let slug=Plain::new(decrypt_optional(row,"encrypted_slug",key)?);
        let project_id=Plain::new(if workspace==Workspace::Tasks{
            let ids=Plain::new(decrypt_optional(row,"encrypted_linked_project_ids",key)?);
            if ids.is_empty(){Value::Null}else{let parsed=Plain::new(serde_json::from_str::<Value>(&ids)?);parsed.get(0).cloned().unwrap_or(Value::Null)}
        }else{Value::Null});
        item.fields=json!({"version":row["version"],"slug":slug.as_str(),"priority":row["priority"],"pinned":row["pinned"],"archived":row["archived"],"created_at":row["created_at"],"updated_at":row["updated_at"]});
        item.fields["project_id"]=project_id.into_inner();
        if workspace==Workspace::Tasks{item.fields["position"]=row["position"].clone();item.fields["source"]=row["source"].clone();}
        Ok(item.into_inner())
    }
    async fn list_tasks(&mut self) -> Result<Vec<Item>> {
        self.require_canonical_read_profile()?;
        let wrapping = self.wrapping_capability().await?;
        let scope=AsyncCryptoScope::begin(self)?;
        let mut output = PlainItems(vec![]);
        let mut cursor: Option<String> = None;
        let mut seen = std::collections::HashSet::new();
        for _ in 0..100 {
            let mut url = self.url("/v1/user-tasks")?;
            {
                let mut q = url.query_pairs_mut();
                q.append_pair("limit", "100")
                    .append_pair("paginate", "true");
                if let Some(c) = &cursor {
                    q.append_pair("cursor", c);
                }
            }
            let path = self.scoped(&format!("{}?{}", self.request_route_path(&url)?, url.query().unwrap_or("")))?;
            let page = self.request(Method::GET, &path, None).await?;
            let rows = page["tasks"].as_array().ok_or(Error::Protocol)?;
            for row in rows {
                if !seen.insert(required(row, "task_id")?.to_owned()) {
                    return Err(Error::Protocol);
                }
                output.0.push(self.object_item_with_capability(Workspace::Tasks,row,&wrapping,&scope).await?);
            }
            if page["complete"] == true {
                if !page["next_cursor"].is_null() {
                    return Err(Error::Protocol);
                }
                self.require_canonical_read_profile()?;scope.check(self)?;return Ok(std::mem::take(&mut output.0));
            }
            if page.get("complete").is_none() && cursor.is_none() && rows.len() < 100 {
                self.require_canonical_read_profile()?;scope.check(self)?;return Ok(std::mem::take(&mut output.0));
            }
            if page["complete"] != false || rows.len() != 100 {
                return Err(Error::Protocol);
            }
            let next = required(&page, "next_cursor")?.to_owned();
            if next.len() > 512 || cursor.as_ref().is_some_and(|c| c >= &next) {
                return Err(Error::Protocol);
            }
            cursor = Some(next);
        }
        Err(Error::Protocol)
    }
    pub async fn mutate(&mut self, mutation: Mutation) -> Result<Option<Item>> {
        if matches!(&mutation,
            Mutation::Update { workspace:Workspace::Chats,id,.. }
            | Mutation::Delete { workspace:Workspace::Chats,id }
            if self.is_ephemeral_chat(id))
        {
            return Err(Error::Invalid(
                "Volatile chats do not have saved mutations.",
            ));
        }
        self.require_credentials()?;
        match mutation {
            Mutation::SetSetting { section, fields } => {
                if self.team()?.is_some() {
                    return Err(Error::Forbidden);
                }
                let value = fields
                    .get("value")
                    .or_else(|| fields.get(&section))
                    .cloned()
                    .unwrap_or_else(|| fields.clone());
                let (route, body) = match section.as_str() {
                    "language" => {
                        let value = value
                            .as_str()
                            .filter(|v| {
                                v.len() >= 2
                                    && v.len() <= 8
                                    && v.bytes().all(|c| c.is_ascii_alphabetic() || c == b'-')
                            })
                            .ok_or(Error::Invalid("Enter a valid language code."))?;
                        ("language", json!({"language":value}))
                    }
                    "timezone" => {
                        let value = value
                            .as_str()
                            .filter(|v| {
                                !v.is_empty() && v.len() <= 100 && !v.contains(['\n', '\r', '\0'])
                            })
                            .ok_or(Error::Invalid("Enter an IANA timezone name."))?;
                        ("timezone", json!({"timezone":value}))
                    }
                    "darkmode" => {
                        let value = value
                            .as_bool()
                            .ok_or(Error::Invalid("Dark mode must be enabled or disabled."))?;
                        ("darkmode", json!({"darkmode":value}))
                    }
                    _ => {
                        return Err(Error::Invalid(
                            "This setting requires a dedicated settings flow.",
                        ));
                    }
                };
                let scope=AsyncCryptoScope::begin(self)?;
                self.request(
                    Method::POST,
                    &format!("/v1/settings/user/{route}"),
                    Some(body),
                )
                .await?;
                scope.check(self)?;
                Ok(None)
            }
            Mutation::RunWorkflow { id } => {
                let request_id = uuid::Uuid::new_v4().to_string();
                let path = format!("/v1/workflows/{}/run", segment(&id));
                // Workflow runs require an idempotency header; this native path
                // is intentionally handled by the transport-specific helper.
                let scope=AsyncCryptoScope::begin(self)?;
                let mut result=Plain::new(self.workflow_run(&path,&request_id).await?);
                scope.check(self)?;
                let item=Plain::new(Item{id:required(&result["run"],"id")?.into(),title:"Workflow run".into(),status:text(&result["run"],"status").into(),fields:result["run"].take(),..Item::default()});
                scope.check(self)?;
                Ok(Some(item.into_inner()))
            }
            Mutation::Create { workspace, fields } => {
                if workspace == Workspace::Apps {
                    return self.run_app_skill(fields).await;
                }
                self.write_object(workspace, None, fields).await
            }
            Mutation::Update {
                workspace,
                id,
                fields,
            } => self.write_object(workspace, Some(&id), fields).await,
            Mutation::Delete { workspace, id } => {
                match workspace {
                    Workspace::Tasks => {
                        let item=Plain::new(self.detail(workspace,&id).await?);
                        let version = item.fields["version"].as_u64().ok_or(Error::Protocol)?;
                        let scope=AsyncCryptoScope::begin(self)?;
                        let path = self.scoped(&format!(
                            "/v1/user-tasks/{}?version={version}",
                            segment(&id)
                        ))?;
                        self.request(Method::DELETE, &path, None).await?;
                        scope.check(self)?;
                    }
                    Workspace::Projects => {
                        let scope=AsyncCryptoScope::begin(self)?;
                        let path = self.scoped(&format!(
                            "/v1/projects/{}?confirmation_project_id={}",
                            segment(&id),
                            segment(&id)
                        ))?;
                        self.request(Method::DELETE, &path, None).await?;
                        scope.check(self)?;
                    }
                    Workspace::Workflows => {
                        if self.team()?.is_some() {
                            return Err(Error::Forbidden);
                        }
                        let scope=AsyncCryptoScope::begin(self)?;
                        self.request(
                            Method::DELETE,
                            &format!("/v1/workflows/{}", segment(&id)),
                            None,
                        )
                        .await?;
                        scope.check(self)?;
                    }
                    Workspace::Chats => {
                        if self.cached_draft_shell(&id)? {
                            self.clear_draft(&id).await?;
                            return Ok(None);
                        }
                        let mut ws = self.socket().await?;
                        let scope=AsyncCryptoScope::begin(self)?;scope.check_chat(self,&id)?;
                        // The canonical handler reads camelCase chatId. Keep
                        // chat_id too, as the shared client wire contract does.
                        let mut body = json!({"chatId":id,"chat_id":id});
                        if let Some(team) = self.team()? {
                            body["team_id"] = json!(team)
                        }
                        transport::send(&mut ws, "delete_chat", body).await?;
                        transport::wait(&mut ws, "chat_deleted", "chat_id", &id).await?;
                        scope.check_chat(self,&id)?;
                        self.remove_chat_row(&id);
                        self.record_deleted_chat(&id);
                        self.history.remove(&id);
                        self.sync_message_windows.remove(&id);
                        self.selected_first_pages.remove(&id);
                        if self.active_chat.as_deref() == Some(&id) {
                            self.active_chat = None;
                        }
                        let _ = ws.close(None).await;
                    }
                    _ => return Err(Error::Invalid("Deletion is unavailable in this workspace.")),
                }
                Ok(None)
            }
        }
    }
    async fn write_object(
        &mut self,
        workspace: Workspace,
        id: Option<&str>,
        fields: Value,
    ) -> Result<Option<Item>> {
        let title = fields.get("title").and_then(Value::as_str);
        let description = fields.get("description").and_then(Value::as_str);
        if !fields.is_object() {
            return Err(Error::Invalid("Object fields must be a JSON object."));
        }
        let allowed: &[&str] = match workspace {
            Workspace::Chats => &["title"],
            Workspace::Tasks => &["title", "description", "slug", "status", "priority"],
            Workspace::Projects => &[
                "title",
                "description",
                "slug",
                "pinned",
                "archived",
                "default_focus_id",
                "write_mode",
                "settings",
            ],
            Workspace::Workflows => &["title", "graph", "enabled", "run_content_retention", "slug"],
            _ => &[],
        };
        if fields
            .as_object()
            .is_some_and(|m| m.keys().any(|k| !allowed.contains(&k.as_str())))
        {
            return Err(Error::Invalid(
                "Some edited fields require a dedicated native flow that is not available yet.",
            ));
        }
        self.preflight_workspace_slug_index(fields.get("slug").and_then(Value::as_str).is_some())?;
        if workspace == Workspace::Chats {
            let id = id.ok_or(Error::Invalid("Start a chat by sending a message."))?;
            let generation = self.generation;
            let cancel = self.operation_cancel.clone();
            self.open_chat(id).await?;
            let row = self.chats.get(id).ok_or(Error::Protocol)?.clone();
            // The old metadata writer forbids Direct chat mutation. Preserve
            // that boundary when using the existing title-only writer.
            if text(&row, "chat_visibility") == "direct" {
                return Err(Error::Forbidden);
            }
            let wrapping = self.wrapping_capability().await?;
            let key = self.chat_key_with_capability(&row,&wrapping).await?;
            let title = title.ok_or(Error::Invalid("A chat title is required."))?;
            let encrypted = crypto::encrypt_combined(title, &key)?;
            // Manual post-processing writes only the supplied fields and
            // durably acknowledges them. In particular, do not resend an old
            // icon/category to satisfy the initial-chat metadata guard.
            let mut body = json!({"chat_id":id,"encrypted_title":encrypted,
                "manual_update":true,"title_changed":true,
                "versions":{"messages_v":row["messages_v"].as_u64().unwrap_or(0),
                    "title_v":row["title_v"].as_u64().unwrap_or(0),
                    "metadata_v":row["metadata_v"].as_u64().unwrap_or(0)},
                "encrypted_chat_key":row["encrypted_chat_key"]});
            if let Some(team) = self.team()? {
                body["team_id"] = json!(team)
            }
            let mut ws = self.socket().await?;
            let effect_scope=AsyncCryptoScope::begin(self)?;
            effect_scope.check_chat(self,id)?;
            if cancel.is_cancelled() || self.generation != generation {
                return Err(Error::Cancelled);
            }
            transport::send(&mut ws, "update_post_processing_metadata", body).await?;
            let receipt =
                transport::wait(&mut ws, "post_processing_metadata_stored", "chat_id", id).await?;
            let _ = ws.close(None).await;
            if cancel.is_cancelled() || self.generation != generation {
                return Err(Error::Cancelled);
            }
            effect_scope.check_chat(self,id)?;
            let (title_v, metadata_v) = accepted_rename_versions(&row, &receipt)?;
            if let Some(row) = self.chats.get_mut(id) {
                row["encrypted_title"] = json!(encrypted);
                row["title_v"] = json!(title_v);
                row["metadata_v"] = json!(metadata_v);
            }
            let item=Plain::new(self.chat_item(self.chats.get(id).ok_or(Error::Protocol)?,&key)?);
            effect_scope.check_chat(self,id)?;
            return Ok(Some(item.into_inner()));
        }
        if workspace == Workspace::Workflows {
            if self.team()?.is_some() {
                return Err(Error::Forbidden);
            }
            let master=self.master_capability()?;
            let scope=AsyncCryptoScope::begin(self)?;
            let mut body = json!({});
            for name in ["title", "graph", "enabled", "run_content_retention"] {
                if let Some(v) = fields.get(name) {
                    body[name] = v.clone()
                }
            }
            if id.is_none() && (title.is_none() || fields.get("graph").is_none()) {
                return Err(Error::Invalid(
                    "Workflow creation requires title and graph.",
                ));
            }
            if let Some(slug) = fields
                .get("slug")
                .and_then(Value::as_str)
                .or(if id.is_none() { title } else { None })
            {
                self.add_slug_with_capability(&mut body,slug,&master,&master,fields.get("slug").and_then(Value::as_str).is_some(),&scope).await?
            }
            let path = id
                .map(|id| format!("/v1/workflows/{}", segment(id)))
                .unwrap_or_else(|| "/v1/workflows".into());
            scope.check(self)?;
            let response = self
                .request(
                    if id.is_some() {
                        Method::PATCH
                    } else {
                        Method::POST
                    },
                    &path,
                    Some(body),
                )
                .await?;
            scope.check(self)?;
            return Ok(Some(self.object_item_with_capability(workspace,&response["workflow"],&master,&scope).await?));
        }
        if !matches!(workspace, Workspace::Tasks | Workspace::Projects) {
            return Err(Error::Invalid(
                "Creation and editing are unavailable in this workspace.",
            ));
        }
        let wrapping = self.wrapping_capability().await?;
        let scope=AsyncCryptoScope::begin(self)?;
        let resource = if workspace == Workspace::Tasks {
            "user-tasks"
        } else {
            "projects"
        };
        let singular = if workspace == Workspace::Tasks {
            "task"
        } else {
            "project"
        };
        let id_field = if workspace == Workspace::Tasks {
            "task_id"
        } else {
            "project_id"
        };
        let key_field = if workspace == Workspace::Tasks {
            "encrypted_task_key"
        } else {
            "encrypted_project_key"
        };
        let mut body = json!({"updated_at":now_ms()/1000});
        let key;
        if let Some(id) = id {
            let path = self.scoped(&format!("/v1/{resource}/{}", segment(id)))?;
            let current = self.request(Method::GET, &path, None).await?;
            let row = &current[singular];
            key = self.object_key_with_capability(workspace,row,&wrapping,&scope).await?;
            body["version"] = row["version"].clone();
        } else {
            let title = title
                .filter(|v| !v.trim().is_empty())
                .ok_or(Error::Invalid("A title is required."))?;
            key = crypto::random_key();
            let object_id = uuid::Uuid::new_v4().to_string();
            body[id_field] = json!(object_id);
            let encrypted_key = wrapping.encrypt_server_bytes(key.as_ref()).await?;
            scope.check(self)?;
            body[key_field] = json!(encrypted_key);
            body["created_at"] = json!(now_ms() / 1000);
            body["version"] = json!(1);
            self.add_slug_with_capability(&mut body,fields.get("slug").and_then(Value::as_str).unwrap_or(title),&MasterCapability::from_native(key.clone()),&wrapping,fields.get("slug").and_then(Value::as_str).is_some(),&scope).await?;
            if let Some(team) = self.team()? {
                body["team_id"] = json!(team);
                body["key_wrappers"] = json!([{"key_type":"team","hashed_team_id":sha256(team),"team_key_epoch":1,(key_field):encrypted_key,"created_at":now_ms()/1000}]);
            }
            if workspace == Workspace::Tasks {
                body["status"] = json!("todo");
                body["assignee_type"] = json!("user");
                body["priority"] = json!(0);
                body["position"] = json!(now_ms() / 1000);
                body["encrypted_labels"] = json!(crypto::server_fields::encrypt_text("[]", &key, &[])?);
                body["encrypted_tags"] = body["encrypted_labels"].clone();
                body["label_hashes"] = json!([]);
                body["encrypted_linked_project_ids"] = json!(crypto::server_fields::encrypt_text("[]", &key, &[])?);
                body["linked_project_ids"] = json!([]);
            } else {
                let focus = required(&fields, "default_focus_id").map_err(|_| {
                    Error::Invalid(
                        "Project creation requires default_focus_id and explicit write_mode.",
                    )
                })?;
                uuid::Uuid::parse_str(focus)
                    .map_err(|_| Error::Invalid("Invalid default focus ID."))?;
                let mode = required(&fields, "write_mode")?;
                if !["always_ask", "apply_and_show"].contains(&mode) {
                    return Err(Error::Invalid("Choose a Project write policy."));
                }
                body["default_focus_id"] = json!(focus);
                body["write_mode"] = json!(mode);
                body["encrypted_settings"] = json!(crypto::server_fields::encrypt_text(
                    &fields
                        .get("settings")
                        .cloned()
                        .unwrap_or_else(|| json!({}))
                        .to_string(),
                    &key,
                    &[]
                )?);
                body["last_opened_at"] = json!(now_ms() / 1000);
            }
        }
        if let Some(v) = title {
            body[if workspace == Workspace::Tasks {
                "encrypted_title"
            } else {
                "encrypted_name"
            }] = json!(crypto::server_fields::encrypt_text(v, &key, &[])?)
        }
        if let Some(v) = description.or(if id.is_none() { Some("") } else { None }) {
            body["encrypted_description"] = json!(crypto::server_fields::encrypt_text(v, &key, &[])?)
        }
        if id.is_some()
            && let Some(slug) = fields.get("slug").and_then(Value::as_str)
        {
            self.add_slug_with_capability(&mut body,slug,&MasterCapability::from_native(key.clone()),&wrapping,true,&scope).await?
        }
        let allowed = if workspace == Workspace::Tasks {
            &["status", "priority"][..]
        } else {
            &["pinned", "archived"][..]
        };
        for name in allowed {
            if let Some(v) = fields.get(*name) {
                body[*name] = v.clone()
            }
        }
        let path = self.scoped(
            &id.map(|id| format!("/v1/{resource}/{}", segment(id)))
                .unwrap_or_else(|| format!("/v1/{resource}")),
        )?;
        scope.check(self)?;
        let response = self
            .request(
                if id.is_some() {
                    Method::PATCH
                } else {
                    Method::POST
                },
                &path,
                Some(body),
            )
            .await?;
        scope.check(self)?;
        Ok(Some(self.object_item_with_capability(workspace,&response[singular],&wrapping,&scope).await?))
    }
}
fn accepted_rename_versions(row: &Value, receipt: &Value) -> Result<(u64, u64)> {
    if receipt["status"] != "stored" {
        return Err(Error::Protocol);
    }
    let versions = &receipt["versions"];
    let messages = versions["messages_v"].as_u64().ok_or(Error::Protocol)?;
    let title = versions["title_v"]
        .as_u64()
        .filter(|v| *v > 0)
        .ok_or(Error::Protocol)?;
    let metadata = versions["metadata_v"]
        .as_u64()
        .filter(|v| *v > 0)
        .ok_or(Error::Protocol)?;
    let old_title = row["title_v"].as_u64().unwrap_or(0);
    // Canonical legacy fallback applies only when metadata_v is absent/zero;
    // an existing positive metadata version is independent of title_v.
    let old_metadata = row["metadata_v"]
        .as_u64()
        .filter(|v| *v > 0)
        .unwrap_or(old_title);
    if messages < row["messages_v"].as_u64().unwrap_or(0)
        || title <= old_title
        || metadata <= old_metadata
    {
        return Err(Error::Conflict);
    }
    // A metadata receipt cannot mark unseen message history as synchronized.
    Ok((title, metadata))
}
// Shared exact Apps DTO projection for ordinary and fixed owned inventory.
pub(super) fn app_inventory_items(data:&Value)->Result<Vec<Item>> {
    let rows=if data.is_array(){data}else{data.get("apps").ok_or(Error::Protocol)?};
    let mut output=PlainItems(vec![]);
    if let Some(rows)=rows.as_array(){for row in rows{output.0.push(public_item(row,Workspace::Apps)?);}}
    else if let Some(rows)=rows.as_object(){for(id,row)in rows{
        let mut row=Plain::new(row.clone());if row.get("id").is_none(){row["id"]=json!(id);}
        output.0.push(public_item(&row,Workspace::Apps)?);
    }}else{return Err(Error::Protocol)}
    Ok(std::mem::take(&mut output.0))
}
fn public_item(row: &Value, workspace: Workspace) -> Result<Item> {
    let id = text(row, "id");
    let id = if id.is_empty() {
        required(row, "app_id")?
    } else {
        id
    };
    let title = ["title", "name", "name_translation_key"]
        .into_iter()
        .map(|k| text(row, k))
        .find(|v| !v.is_empty())
        .unwrap_or(id);
    Ok(Item {
        id: id.into(),
        title: title.into(),
        description: text(row, "description").into(),
        status: text(row, "status").into(),
        category: workspace.label().into(),
        fields: row.clone(),
    })
}

#[cfg(test)]
#[path = "workspaces_delete_tests.rs"]
pub(super) mod delete_tests;

#[cfg(test)]
#[path = "workspaces_rename_tests.rs"]
mod rename_tests;

#[cfg(test)]
#[path = "workspaces_task_order_tests.rs"]
mod task_order_tests;

#[cfg(test)]
#[path="workspaces_server_field_tests.rs"]
pub(super) mod server_field_tests;

impl Client {
    pub(in crate::client) async fn object_key_with_capability(&self,workspace:Workspace,row:&Value,wrapping:&MasterCapability,scope:&AsyncCryptoScope)->Result<Key>{
        scope.check(self)?;
        let encrypted=self.object_key_ciphertext(workspace,row)?;
        let plain=wrapping.decrypt_bytes(encrypted).await?;
        scope.check(self)?;
        key_from_bytes(&plain)
    }
    pub(in crate::client) async fn object_item_with_capability(&self,workspace:Workspace,row:&Value,wrapping:&MasterCapability,scope:&AsyncCryptoScope)->Result<Item>{
        self.require_canonical_read_profile()?;scope.check(self)?;
        let mut item=match wrapping.native_key(){
            Ok(key)=>self.object_item(workspace,row,key)?,
            Err(Error::Unavailable{code:"master_key_extraction_unavailable",..})=>{
                if workspace==Workspace::Workflows {
                    let mut item=Plain::new(public_item(row,workspace)?);
                    let slug=Plain::new(self.decrypt_optional_with_capability(row,"encrypted_slug",wrapping).await?);
                    item.fields["slug"]=json!(slug.as_str());item.into_inner()
                } else if workspace==Workspace::Tasks&&text(row,"source")=="workflow_run" {
                    Self::workflow_run_item(row)?
                } else {
                    let key=self.object_key_with_capability(workspace,row,wrapping,scope).await?;
                    self.object_item_from_key(workspace,row,&key)?
                }
            }
            Err(error)=>return Err(error),
        };
        if let Err(error)=self.require_canonical_read_profile().and_then(|_|scope.check(self)){wipe_item(&mut item);return Err(error);}
        Ok(item)
    }
}

impl Client {
    fn preflight_workspace_slug_index(&self,explicit:bool)->Result<()> {
        if !explicit||self.team()?.is_some(){return Ok(());}
        let Some(credentials)=&self.browser_credentials else{return Ok(());};
        AsyncCryptoScope::begin(self)?.check(self)?;
        match credentials.master.native_key(){Ok(_)=>Ok(()),Err(Error::Unavailable{code:"master_key_extraction_unavailable",..})=>Err(Error::Unavailable{code:"opaque_slug_index_unavailable",reason:"EXPLICIT_SLUG_REQUIRES_EXISTING_HKDF_INDEX_CAPABILITY"}),Err(error)=>Err(error)}
    }
    async fn add_slug_with_capability(&self,body:&mut Value,slug:&str,key:&MasterCapability,lookup:&MasterCapability,explicit:bool,scope:&AsyncCryptoScope)->Result<()> {
        scope.check(self)?;
        let raw=match lookup.native_key(){
            Ok(raw)=>raw,
            Err(Error::Unavailable{code:"master_key_extraction_unavailable",..}) if !explicit=>return Ok(()),
            Err(Error::Unavailable{code:"master_key_extraction_unavailable",..})=>return Err(Error::Unavailable{code:"opaque_slug_index_unavailable",reason:"EXPLICIT_SLUG_REQUIRES_EXISTING_HKDF_INDEX_CAPABILITY"}),
            Err(error)=>return Err(error),
        };
        let normalized=crypto::normalize_object_slug(slug)?;
        let hash=crypto::object_slug_lookup_hash(&normalized,raw)?;
        let encrypted=key.encrypt_server_bytes(normalized.as_bytes()).await?;
        scope.check(self)?;
        body["encrypted_slug"]=json!(encrypted);body["slug_lookup_hash"]=json!(hash);
        Ok(())
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="workspaces_opaque_tests.rs"]
mod opaque_tests;
