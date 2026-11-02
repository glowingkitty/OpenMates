//! Named Workflow authoring and opaque template operations.
use super::*;
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct WorkflowAskOptions {
    pub create: Option<WorkflowCreate>,
    pub exact_update: Option<WorkflowAskUpdate>,
    pub exact_action: Option<WorkflowAskAction>,
    pub selected_object_id: Option<String>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowAskUpdate {
    pub workflow_id: String,
    pub patch: WorkflowPatch,
}
#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkflowAction {
    Enable,
    Disable,
    Delete,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowAskAction {
    pub workflow_id: String,
    pub action: WorkflowAction,
    #[serde(default)]
    pub confirmed: bool,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowProposal {
    pub title: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub steps: Vec<WorkflowStepProposal>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowStepProposal {
    pub title: String,
    #[serde(default)]
    pub body: String,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowTemplateProjection {
    pub template_id: String,
    pub source_version: u64,
    pub ciphertext: String,
    pub ciphertext_checksum: String,
    pub owner_wrapped_key: String,
    pub projection_schema_version: u32,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowBindingCompletion {
    pub r#type: String,
    pub node_id: String,
    #[serde(default)]
    pub chat_id: Option<String>,
    #[serde(default)]
    pub new_chat: bool,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowTemplateImport {
    pub template_version: u32,
    pub title: String,
    #[serde(default)]
    pub description: Option<String>,
    pub trigger_template: Object,
    #[serde(default)]
    pub node_templates: Vec<Object>,
    #[serde(default)]
    pub edge_templates: Vec<Object>,
    #[serde(default)]
    pub variables_schema: Object,
    #[serde(default)]
    pub required_capabilities: Vec<String>,
    #[serde(default)]
    pub binding_requirements: Vec<Object>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowTemplateShortUrl {
    pub token: String,
    pub encrypted_url: String,
    pub template_id: String,
    #[serde(default)]
    pub ttl_seconds: Option<u64>,
    #[serde(default)]
    pub password_protected: bool,
}
impl Workflows<'_> {
    pub async fn plan_ask(&mut self, instruction: &str) -> Result<WorkflowProposal> {
        self.scope(false)?;
        self.backend.verify_private_operation()?;
        instruction_text(instruction)?;
        let data = self
            .backend
            .request(
                Method::POST,
                "/v1/workflows/ask/plan",
                Some(json!({"instruction":instruction})),
                None,
            )
            .await?;
        let proposal: WorkflowProposal = serde_json::from_value(data["proposed_workflow"].clone())
            .map_err(|_| Error::Protocol)?;
        validate_title(&proposal.title, Some(&proposal.description))?;
        if proposal.steps.len() > 5
            || proposal.steps.iter().any(|s| {
                s.title.is_empty() || s.title.chars().count() > 160 || s.body.chars().count() > 500
            })
        {
            return Err(Error::Protocol);
        }
        Ok(proposal)
    }
    pub async fn ask(&mut self, instruction: &str, input: WorkflowAskOptions) -> Result<Value> {
        self.scope(false)?;
        self.backend.verify_private_operation()?;
        instruction_text(instruction)?;
        if usize::from(input.create.is_some())
            + usize::from(input.exact_update.is_some())
            + usize::from(input.exact_action.is_some())
            > 1
        {
            return Err(Error::Invalid("Choose one exact Workflow ask operation."));
        }
        let mut payload = json!({"instruction":instruction});
        if let Some(create) = input.create {
            payload["create"] = self.create_wire(create).await?;
        }
        if let Some(update) = input.exact_update {
            let id = self.resolve(&update.workflow_id).await?;
            payload["exact_update"] =
                json!({"workflow_id":id,"patch":self.patch_wire(update.patch).await?});
        }
        if let Some(action) = input.exact_action {
            if matches!(action.action, WorkflowAction::Delete) && !action.confirmed {
                return Err(Error::Invalid(
                    "Explicit Workflow deletion confirmation is required.",
                ));
            }
            payload["exact_action"] = json!({"workflow_id":self.resolve(&action.workflow_id).await?,"action":action.action});
        }
        if let Some(selected) = input.selected_object_id {
            payload["selected_object_id"] = json!(self.resolve(&selected).await?);
        }
        let mut data = self
            .backend
            .request(Method::POST, "/v1/workflows/ask", Some(payload), None)
            .await?;
        if data["workflow"].is_object() {
            data["workflow"] = self.decode(data["workflow"].clone()).await?;
        }
        if let Some(rows) = data["workflows"].as_array() {
            let mut output = vec![];
            for row in rows {
                output.push(self.decode(row.clone()).await?);
            }
            data["workflows"] = json!(output);
        }
        Ok(data)
    }
    pub async fn upsert_template_projection(
        &mut self,
        id: &str,
        input: WorkflowTemplateProjection,
    ) -> Result<Value> {
        self.scope(false)?;
        bounded(&input.template_id, 200)?;
        bounded(&input.ciphertext, 100_000)?;
        bounded(&input.ciphertext_checksum, 200)?;
        bounded(&input.owner_wrapped_key, 100_000)?;
        if input.source_version == 0 || input.projection_schema_version == 0 {
            return Err(Error::Invalid("Template versions must be positive."));
        }
        self.resource(
            id,
            "/template-projection",
            Method::PUT,
            Some(serde_json::to_value(input)?),
            false,
        )
        .await
    }
    pub async fn template_projection(&mut self, id: &str) -> Result<Value> {
        self.resource(id, "/template-projection", Method::GET, None, false)
            .await
    }
    pub async fn get_public_template_projection(&mut self, template: &str) -> Result<Value> {
        bounded(template, 200)?;
        let data = self.backend.public_workflow_projection(template).await?;
        if data["template_id"] != template
            || !data["ciphertext"].is_string()
            || !data["ciphertext_checksum"].is_string()
            || data["projection_schema_version"]
                .as_u64()
                .is_none_or(|n| n == 0)
        {
            return Err(Error::Protocol);
        }
        Ok(data)
    }
    pub async fn revoke_template_projection(&mut self, id: &str) -> Result<Value> {
        self.resource(
            id,
            "/template-projection/revoke",
            Method::POST,
            Some(json!({})),
            false,
        )
        .await
    }
    pub async fn unrevoke_template_projection(&mut self, id: &str) -> Result<Value> {
        self.resource(
            id,
            "/template-projection/unrevoke",
            Method::POST,
            Some(json!({})),
            false,
        )
        .await
    }
    pub async fn complete_imported_binding(
        &mut self,
        id: &str,
        input: WorkflowBindingCompletion,
    ) -> Result<Value> {
        bounded(&input.r#type, 100)?;
        bounded(&input.node_id, 200)?;
        if let Some(chat) = &input.chat_id {
            uuid(chat)?;
        }
        if input.new_chat && input.chat_id.is_some() {
            return Err(Error::Invalid("Choose an existing or a new chat binding."));
        }
        self.resource(
            id,
            "/binding-requirements/complete",
            Method::POST,
            Some(serde_json::to_value(input)?),
            false,
        )
        .await
    }
    pub async fn create_template_short_url(
        &mut self,
        input: WorkflowTemplateShortUrl,
    ) -> Result<Value> {
        self.scope(false)?;
        bounded(&input.token, 200)?;
        bounded(&input.encrypted_url, 100_000)?;
        bounded(&input.template_id, 200)?;
        let mut payload = serde_json::to_value(&input)?;
        payload
            .as_object_mut()
            .ok_or(Error::Protocol)?
            .remove("template_id");
        payload
            .as_object_mut()
            .ok_or(Error::Protocol)?
            .retain(|_, v| !v.is_null());
        payload["content_type"] = json!("workflow_template");
        payload["content_id"] = json!(input.template_id);
        self.backend
            .request(Method::POST, "/v1/share/short-url", Some(payload), None)
            .await
    }
    pub async fn revoke_short_url(&mut self, token: &str) -> Result<Value> {
        self.scope(false)?;
        bounded(token, 200)?;
        self.backend
            .request(
                Method::DELETE,
                &format!("/v1/share/short-url/{}", opaque_id(token)?),
                None,
                None,
            )
            .await
    }
    pub async fn import_template(&mut self, input: WorkflowTemplateImport) -> Result<Value> {
        self.scope(false)?;
        self.backend.verify_private_operation()?;
        validate_title(&input.title, input.description.as_deref())?;
        if input.template_version == 0 {
            return Err(Error::Invalid("Template version must be positive."));
        }
        let payload = serde_json::to_value(input)?;
        file::validate_portable_value(&payload)?;
        let data = self
            .backend
            .request(
                Method::POST,
                "/v1/workflows/template-import",
                Some(payload),
                None,
            )
            .await?;
        self.decode(data["workflow"].clone()).await
    }
}
fn bounded(value: &str, max: usize) -> Result<()> {
    if value.is_empty() || value.len() > max || value.chars().any(char::is_control) {
        return Err(Error::Invalid("Invalid Workflow template field."));
    }
    Ok(())
}
fn instruction_text(value: &str) -> Result<()> {
    if value.trim().is_empty() || value.chars().count() > 20_000 {
        return Err(Error::Invalid(
            "Workflow instructions require 1–20,000 characters.",
        ));
    }
    Ok(())
}

impl Workflows<'_> {
    pub async fn add_to_project(
        &mut self,
        id: &str,
        project: &str,
        folder: Option<&str>,
    ) -> Result<Value> {
        self.scope(true)?;
        if let Some(folder) = folder {
            uuid(folder)?;
        }
        let workflow = self.get(id).await?;
        let workflow_id = string(&workflow, "id")?;
        let project = match &mut self.backend {
            Backend::Cookie(client) => {
                client
                    .projects()
                    .with_filters(ProjectFilters {
                        personal: self.filters.personal,
                        team_id: self.filters.team_id.clone(),
                        ..Default::default()
                    })
                    .resolve(project)
                    .await?
            }
            Backend::ApiKey(client) => {
                client
                    .projects()
                    .with_filters(ProjectFilters {
                        personal: self.filters.personal,
                        team_id: self.filters.team_id.clone(),
                        ..Default::default()
                    })
                    .resolve(project)
                    .await?
            }
        };
        let payload = project_item_wire(workflow_id, workflow["title"].as_str().unwrap_or(workflow_id), folder, &project.key)?;
        let route = self.path(
            &format!("/v1/projects/{}/items", string(&project.raw, "project_id")?),
            &[],
        );
        let response = self
            .backend
            .request(Method::POST, &route, Some(payload), None)
            .await?;
        object_field(&response, "item")
    }
    pub async fn remove_from_project(&mut self, id: &str, project: &str) -> Result<Value> {
        self.scope(true)?;
        let workflow = self.get(id).await?;
        let project = self.project_id(project).await?;
        let route = self.path(
            &format!("/v1/projects/{project}/items"),
            &[
                ("item_type".into(), "workflow".into()),
                ("target_id".into(), string(&workflow, "id")?.into()),
            ],
        );
        let data = self
            .backend
            .request(Method::DELETE, &route, None, None)
            .await?;
        if !data["deleted"].is_boolean() || !data["deleted_count"].is_u64() {
            return Err(Error::Protocol);
        }
        Ok(data)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::work::tasks::tests::{client, mock};
    const FLOW: &str = "dbaaccdd-1111-4111-8111-aabbccddeeff";
    #[tokio::test]
    async fn public_projection_never_sends_cookie_or_authorization() {
        let(api,server)=mock(vec![json!({"template_id":"fixture","ciphertext":"opaque","ciphertext_checksum":"checksum","projection_schema_version":1})]).await;
        let mut client = client(&api);
        let mut session = client.clone_session().unwrap();
        session
            .cookies
            .insert("auth_refresh_token".into(), "private-cookie".into());
        client.reset(&api, Some(session)).unwrap();
        assert_eq!(
            client
                .workflows()
                .get_public_template_projection("fixture")
                .await
                .unwrap()["template_id"],
            "fixture"
        );
        let request = server.await.unwrap();
        let headers = request[0].to_lowercase();
        assert!(!headers.contains("cookie:"));
        assert!(!headers.contains("authorization:"));
        assert!(!headers.contains("private-cookie"));
    }
    #[tokio::test]
    async fn exact_ask_delete_and_template_context_reject_before_io() {
        let mut client = client("http://127.0.0.1:1");
        let options = WorkflowAskOptions {
            exact_action: Some(WorkflowAskAction {
                workflow_id: FLOW.into(),
                action: WorkflowAction::Delete,
                confirmed: false,
            }),
            ..Default::default()
        };
        assert!(matches!(
            client.workflows().ask("delete", options).await,
            Err(Error::Invalid(_))
        ));
        client.set_private_operation_gate(Some(std::sync::Arc::new(|| Err(Error::Forbidden))));
        assert!(matches!(
            client.workflows().ask("ask", Default::default()).await,
            Err(Error::Forbidden)
        ));
    }
    #[tokio::test]
    async fn exact_update_reuses_encrypted_slug_codec() {
        let slug = crypto::encrypt_combined("updated-slug", &[7; 32]).unwrap();
        let (api, server) = mock(vec![
            json!({"workflow":{"id":FLOW,"title":"updated","encrypted_slug":slug}}),
        ])
        .await;
        let mut client = client(&api);
        let result = client
            .workflows()
            .ask(
                "rename",
                WorkflowAskOptions {
                    exact_update: Some(WorkflowAskUpdate {
                        workflow_id: FLOW.into(),
                        patch: WorkflowPatch {
                            title: Some("updated".into()),
                            slug: Some("updated-slug".into()),
                            ..Default::default()
                        },
                    }),
                    ..Default::default()
                },
            )
            .await
            .unwrap();
        assert_eq!(result["workflow"]["slug"], "updated-slug");
        let request = server.await.unwrap();
        let body: Value =
            serde_json::from_str(request[0].split("\r\n\r\n").nth(1).unwrap()).unwrap();
        assert!(body["exact_update"]["patch"].get("slug").is_none());
        assert_eq!(
            crypto::decrypt_combined(
                body["exact_update"]["patch"]["encrypted_slug"]
                    .as_str()
                    .unwrap(),
                &[7; 32]
            )
            .unwrap(),
            "updated-slug"
        );
    }
}

// Field codec only; caller retains scope, owner resolution and dispatch guards.
fn project_item_wire(workflow_id: &str, title: &str, folder: Option<&str>, key: &[u8; 32]) -> Result<Value> {
    Ok(json!({"project_item_id":uuid::Uuid::new_v4().to_string(),"folder_id":folder,"item_type":"workflow","target_id":workflow_id,"target_id_encrypted":crypto::server_fields::encrypt_text(workflow_id,key, &[])?,"encrypted_display_name":crypto::server_fields::encrypt_text(title,key, &[])?,"encrypted_note":crypto::server_fields::encrypt_text("",key, &[])?,"encrypted_metadata":crypto::server_fields::encrypt_text(r#"{"storage":"save_only_in_openmates","source":"sdk_add_to_project"}"#,key, &[])?,"created_at":now(),"updated_at":now(),"position":now()}))
}
#[cfg(all(test, not(target_arch = "wasm32")))]
mod field_interop_tests {
    use super::*;
    use crate::work::task_crypto::field_interop_support::{assert_web, case};
    #[test]
    fn actual_workflow_project_item_fields_read_in_web_legacy_decoders() {
        let key = [34; 32];
        let raw = project_item_wire("workflow-fixture", "Private workflow", None, &key).unwrap();
        let mut cases = vec![];
        for (field, expected) in [("target_id_encrypted", "workflow-fixture"), ("encrypted_display_name", "Private workflow"), ("encrypted_note", ""), ("encrypted_metadata", r#"{"storage":"save_only_in_openmates","source":"sdk_add_to_project"}"#)] {
            cases.push(case(field, "object-text", raw[field].as_str().unwrap(), &key, expected.as_bytes(), ""));
        }
        assert_eq!(raw["target_id"], "workflow-fixture");
        assert_eq!(raw["item_type"], "workflow");
        assert!(raw["folder_id"].is_null());
        assert_web(cases);
    }
}
