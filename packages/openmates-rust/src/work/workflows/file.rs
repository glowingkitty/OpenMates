//! Portable definitions contain no account bindings, credentials or runtime state.
use super::*;
use regex::Regex;
#[cfg(feature="workflow-yaml")]
use unicode_normalization::UnicodeNormalization;
pub const WORKFLOW_FILE_MAX_BYTES: usize = 1_048_576;
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowFileDocument {
    pub format: String,
    pub format_version: u32,
    pub workflow: WorkflowFileDefinition,
    pub binding_requirements: Vec<WorkflowFileBinding>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowFileDefinition {
    pub title: String,
    pub description: Option<String>,
    pub run_content_retention: WorkflowRetention,
    pub graph: WorkflowGraph,
}
#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkflowBindingType {
    Schedule,
    AppSkill,
    ChatDestination,
    NotificationPreferences,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowFileBinding {
    pub r#type: WorkflowBindingType,
    pub node_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub app_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub skill_id: Option<String>,
}
const FORBIDDEN: &[&str] = &[
    "token",
    "accesstoken",
    "refreshtoken",
    "authtoken",
    "bearertoken",
    "secret",
    "credential",
    "credentials",
    "password",
    "apikey",
    "privatekey",
    "vaultkey",
    "masterkey",
    "encryptionkey",
    "authorization",
    "grant",
    "grantid",
    "accountid",
    "connectedaccountid",
    "connectionid",
    "provideruserid",
    "userid",
    "ownerid",
    "ownerhash",
    "teamid",
    "projectid",
    "workflowid",
    "versionid",
    "runid",
    "chatid",
    "sourcechatid",
    "encryptedgraphblobref",
    "encryptedcontentref",
    "fragmentkey",
    "shortkey",
    "templatekey",
    "nextrunat",
    "providerresponse",
    "runhistory",
    "deliveryhistory",
    "cookie",
    "sessioncookie",
    "sessionid",
    "encryptedkey",
    "encryptedpayload",
    "ciphertext",
    "vault",
    "claimtoken",
    "deliveryid",
    "encryptedgraphref",
    "lastrunat",
];
const SUFFIXES: &[&str] = &[
    "accesstoken",
    "refreshtoken",
    "authtoken",
    "bearertoken",
    "sessiontoken",
    "apikey",
    "privatekey",
    "clientsecret",
    "secret",
    "password",
    "credential",
    "credentials",
    "authorization",
    "vaultkey",
    "masterkey",
    "encryptionkey",
];
fn portable(value: &Value, depth: usize, left: &mut usize) -> Result<()> {
    if depth > 64 || *left == 0 {
        return Err(Error::Invalid("Workflow file is too complex."));
    }
    *left -= 1;
    match value {
        Value::Array(values) => {
            for value in values {
                portable(value, depth + 1, left)?
            }
        }
        Value::Object(values) => {
            for (key, value) in values {
                let normalized = key
                    .chars()
                    .filter(char::is_ascii_alphanumeric)
                    .flat_map(char::to_lowercase)
                    .collect::<String>();
                if ["__proto__", "constructor", "prototype"].contains(&key.as_str())
                    || FORBIDDEN.contains(&normalized.as_str())
                    || SUFFIXES.iter().any(|suffix| normalized.ends_with(suffix))
                {
                    return Err(Error::Invalid(
                        "Workflow file contains an account-specific or private field.",
                    ));
                }
                portable(value, depth + 1, left)?
            }
        }
        _ => {}
    }
    Ok(())
}
pub(super) fn validate_portable_value(value: &Value) -> Result<()> {
    portable(value, 0, &mut 50_000)
}
pub fn validate_workflow_file(document: &WorkflowFileDocument) -> Result<()> {
    if document.format != "openmates-workflow" || document.format_version != 1 {
        return Err(Error::Invalid(
            "Unsupported portable Workflow file format or version.",
        ));
    }
    validate_title(
        &document.workflow.title,
        document.workflow.description.as_deref(),
    )?;
    let graph = &document.workflow.graph;
    if graph.version == 0 {
        return Err(Error::Invalid(
            "Workflow file graph version must be positive.",
        ));
    }
    let mut ids = std::collections::BTreeSet::new();
    for node in &graph.nodes {
        if node.id.is_empty() || !ids.insert(node.id.as_str()) {
            return Err(Error::Invalid(
                "Workflow file contains duplicate or empty step identifiers.",
            ));
        }
    }
    if graph
        .trigger_node_id
        .as_ref()
        .is_some_and(|id| !ids.contains(id.as_str()))
        || graph
            .edges
            .iter()
            .any(|edge| !ids.contains(edge.from.as_str()) || !ids.contains(edge.to.as_str()))
        || document
            .binding_requirements
            .iter()
            .any(|binding| !ids.contains(binding.node_id.as_str()))
    {
        return Err(Error::Invalid("Workflow file references a missing step."));
    }
    let value = serde_json::to_value(document)?;
    validate_portable_value(&value)?;
    if serde_json::to_vec(&value)?.len() > WORKFLOW_FILE_MAX_BYTES {
        return Err(Error::Invalid("Workflow file exceeds the file size limit."));
    }
    Ok(())
}
fn rewrite(value: &mut Value, expression: &Regex, ids: &BTreeMap<String, String>) {
    match value {
        Value::String(text) => {
            *text = expression
                .replace_all(text, |capture: &regex::Captures<'_>| {
                    format!(
                        "{}{}{}",
                        &capture[1],
                        ids.get(&capture[2])
                            .map(String::as_str)
                            .unwrap_or(&capture[2]),
                        &capture[3]
                    )
                })
                .into_owned()
        }
        Value::Array(values) => {
            for value in values {
                rewrite(value, expression, ids)
            }
        }
        Value::Object(values) => {
            for value in values.values_mut() {
                rewrite(value, expression, ids)
            }
        }
        _ => {}
    }
}
/// Build a shareable saved definition, remapping all graph references and review bindings.
pub fn build_workflow_export(workflow: &Value) -> Result<WorkflowFileDocument> {
    let title = string(workflow, "title")?.to_owned();
    let mut graph: WorkflowGraph = serde_json::from_value(workflow["graph"].clone())
        .map_err(|_| Error::Invalid("Invalid typed Workflow graph."))?;
    let original_ids = graph
        .nodes
        .iter()
        .map(|node| node.id.clone())
        .collect::<Vec<_>>();
    let original_edges = graph
        .edges
        .iter()
        .map(|edge| (edge.from.clone(), edge.to.clone()))
        .collect::<Vec<_>>();
    let original_trigger = graph.trigger_node_id.clone();
    let ids = graph
        .nodes
        .iter()
        .enumerate()
        .map(|(index, node)| (node.id.clone(), format!("step_{}", index + 1)))
        .collect::<BTreeMap<_, _>>();
    if ids.len() != graph.nodes.len() {
        return Err(Error::Invalid(
            "Workflow graph has duplicate step identifiers.",
        ));
    }
    let original: Vec<WorkflowFileBinding> = serde_json::from_value(
        workflow
            .get("binding_requirements")
            .cloned()
            .unwrap_or(json!([])),
    )
    .map_err(|_| Error::Protocol)?;
    let mut bindings = vec![];
    for node in &mut graph.nodes {
        let kind = match node.r#type {
            WorkflowNodeType::ScheduleTrigger => Some(WorkflowBindingType::Schedule),
            WorkflowNodeType::AppSkillAction => Some(WorkflowBindingType::AppSkill),
            WorkflowNodeType::SendNotification | WorkflowNodeType::SendEmailNotification => {
                Some(WorkflowBindingType::NotificationPreferences)
            }
            WorkflowNodeType::SendChatMessage => {
                let required =
                    node.config.get("chat_id").is_some_and(|v| {
                        v != &Value::Null && v != &json!("") && v != &json!(false)
                    }) || node.config.get("destination_required") == Some(&Value::Bool(true))
                        || original.iter().any(|b| {
                            b.r#type == WorkflowBindingType::ChatDestination && b.node_id == node.id
                        });
                node.config.remove("chat_id");
                if required {
                    node.config
                        .insert("destination_required".into(), json!(true));
                    Some(WorkflowBindingType::ChatDestination)
                } else {
                    None
                }
            }
            _ => None,
        };
        if let Some(kind) = kind {
            let app_id = if kind == WorkflowBindingType::AppSkill {
                Some(
                    node.config
                        .get("app_id")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .into(),
                )
            } else {
                None
            };
            let skill_id = if kind == WorkflowBindingType::AppSkill {
                Some(
                    node.config
                        .get("skill_id")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .into(),
                )
            } else {
                None
            };
            bindings.push(WorkflowFileBinding {
                r#type: kind,
                node_id: ids[&node.id].clone(),
                app_id,
                skill_id,
            });
        }
    }
    if !ids.is_empty() {
        let mut keys = ids.keys().collect::<Vec<_>>();
        keys.sort_by_key(|id| std::cmp::Reverse(id.len()));
        let alternatives = keys
            .into_iter()
            .map(|id| regex::escape(id))
            .collect::<Vec<_>>()
            .join("|");
        let expression = Regex::new(&format!(
            r"(\$nodes\.|\{{\{{\s*steps\.|\$items\.|\{{\{{\s*items\.)({alternatives})([.}}\s]|$)"
        ))
        .map_err(|_| Error::Protocol)?;
        let mut value = serde_json::to_value(&graph)?;
        rewrite(&mut value, &expression, &ids);
        graph = serde_json::from_value(value)?;
    }
    graph.trigger_node_id = original_trigger.map(|id| ids.get(&id).cloned().unwrap_or(id));
    for (index, node) in graph.nodes.iter_mut().enumerate() {
        node.id = ids[&original_ids[index]].clone();
    }
    for (index, edge) in graph.edges.iter_mut().enumerate() {
        edge.from = ids
            .get(&original_edges[index].0)
            .cloned()
            .unwrap_or_else(|| original_edges[index].0.clone());
        edge.to = ids
            .get(&original_edges[index].1)
            .cloned()
            .unwrap_or_else(|| original_edges[index].1.clone());
    }
    graph.ui_layout = graph
        .ui_layout
        .into_iter()
        .map(|(id, value)| (ids.get(&id).cloned().unwrap_or(id), value))
        .collect();
    let document = WorkflowFileDocument {
        format: "openmates-workflow".into(),
        format_version: 1,
        workflow: WorkflowFileDefinition {
            title,
            description: workflow["description"].as_str().map(str::to_owned),
            run_content_retention: serde_json::from_value(
                workflow
                    .get("run_content_retention")
                    .cloned()
                    .unwrap_or(json!("last_5")),
            )
            .map_err(|_| Error::Protocol)?,
            graph,
        },
        binding_requirements: bindings,
    };
    validate_workflow_file(&document)?;
    Ok(document)
}
impl Workflows<'_> {
    pub async fn export_file(&mut self, id: &str) -> Result<WorkflowFileDocument> {
        let workflow = self.get(id).await?;
        if workflow["lifecycle"] == "temporary" {
            return Err(Error::Invalid("Save the Workflow before exporting it."));
        }
        build_workflow_export(&workflow)
    }
    pub async fn import_file(&mut self, document: WorkflowFileDocument) -> Result<Value> {
        self.scope(false)?;
        self.backend.verify_private_operation()?;
        validate_workflow_file(&document)?;
        let data = self
            .backend
            .request(
                Method::POST,
                "/v1/workflows/file-import",
                Some(serde_json::to_value(document)?),
                None,
            )
            .await?;
        self.decode(data["workflow"].clone()).await
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn workflow() -> Value {
        json!({"id":"private-workflow-record","title":"Portable","run_content_retention":"last_5","graph":{"version":1,"trigger_node_id":"manual","nodes":[{"id":"manual","type":"manual_trigger","config":{}},{"id":"send","type":"send_chat_message","config":{"chat_id":"private-chat","message":"$nodes.manual.value / {{ steps.manual.output }} / $items.manual.value"}}],"edges":[{"from":"manual","to":"send"}],"ui_layout":{"manual":{"x":1}}}})
    }
    #[test]
    fn export_remaps_references_and_strips_runtime_chat_binding() {
        let document = build_workflow_export(&workflow()).ok().unwrap();
        let value = serde_json::to_value(&document).unwrap();
        assert_eq!(value["workflow"]["graph"]["nodes"][1]["id"], "step_2");
        assert_eq!(
            value["workflow"]["graph"]["nodes"][1]["config"]["message"],
            "$nodes.step_1.value / {{ steps.step_1.output }} / $items.step_1.value"
        );
        assert!(
            value["workflow"]["graph"]["nodes"][1]["config"]
                .get("chat_id")
                .is_none()
        );
        assert_eq!(value["binding_requirements"][0]["node_id"], "step_2");
        assert!(
            value["workflow"]["graph"]["ui_layout"]
                .get("step_1")
                .is_some()
        );
        assert!(
            !serde_json::to_string(&value)
                .unwrap()
                .contains("private-chat")
        );
    }
    #[test]
    fn private_account_fields_and_credentials_are_rejected_but_token_counts_are_portable() {
        for key in [
            "owner_id",
            "provider_api_key",
            "Authorization",
            "refresh_token",
            "project_id",
            "__proto__",
        ] {
            let mut source = workflow();
            source["graph"]["nodes"][0]["config"][key] = json!("private");
            assert!(build_workflow_export(&source).is_err(), "{key}");
        }
        let mut source = workflow();
        source["graph"]["nodes"][0]["config"]["token_count"] = json!(10);
        assert!(build_workflow_export(&source).is_ok());
    }
    #[test]
    fn invalid_links_and_oversize_portable_documents_fail_before_transport() {
        let mut document = build_workflow_export(&workflow()).ok().unwrap();
        document.workflow.graph.edges[0].to = "missing".into();
        assert!(validate_workflow_file(&document).is_err());
        let mut document = build_workflow_export(&workflow()).ok().unwrap();
        document.workflow.graph.nodes[0]
            .config
            .insert("text".into(), json!("x".repeat(WORKFLOW_FILE_MAX_BYTES)));
        assert!(validate_workflow_file(&document).is_err());
    }
}

/// Pure maintained native filename policy. No filesystem, account or IO access.
#[cfg(feature="workflow-yaml")]
pub fn workflow_file_name(title: &str) -> String {
    let name = title
        .nfkc()
        .map(|c| {
            if c.is_control() || "/\\<>:\"|?*".contains(c) {
                '-'
            } else {
                c
            }
        })
        .collect::<String>();
    let name = name
        .trim()
        .trim_matches('.')
        .trim_end_matches(['.', ' '])
        .trim()
        .to_lowercase();
    let name = name
        .strip_suffix(".workflow.yml")
        .or_else(|| name.strip_suffix(".workflow.yaml"))
        .unwrap_or(&name);
    let name = name
        .split_whitespace()
        .collect::<Vec<_>>()
        .join("_")
        .chars()
        .take(100)
        .collect::<String>();
    format!(
        "{}.workflow.yml",
        if name.is_empty() { "workflow" } else { &name }
    )
}
/// Pure portable formatting over caller-owned typed data, never authentication.
/// Actual sync calls supply the document built from their own fresh workflow.
#[cfg(feature="workflow-yaml")]
pub fn serialize_workflow_file(document:&WorkflowFileDocument)->Result<(String,String)>{
    validate_workflow_file(document)?;
    // npm exports omit an unset node title; drop `title: null` here (not in the typed
    // struct, whose JSON wire form must keep it) so exported files match byte-for-key.
    let mut tree=serde_yaml::to_value(document).map_err(|_|Error::Protocol)?;
    if let Some(nodes)=tree.get_mut("workflow").and_then(|w|w.get_mut("graph")).and_then(|g|g.get_mut("nodes")).and_then(|n|n.as_sequence_mut()){
        for node in nodes{
            if let Some(map)=node.as_mapping_mut(){
                if map.get("title").is_some_and(serde_yaml::Value::is_null){map.remove("title");}
            }
        }
    }
    let source=serde_yaml::to_string(&tree).map_err(|_|Error::Protocol)?;
    if source.len()>WORKFLOW_FILE_MAX_BYTES{return Err(Error::Invalid("Workflow export exceeds the file size limit."))}
    Ok((workflow_file_name(&document.workflow.title),source))
}

#[cfg(all(test,feature="workflow-yaml"))]
mod yaml_formatting_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=cli.surface.semantic-parity,auth.secrets.lifecycle
    #[test]
    fn extracted_native_formatter_keeps_filename_and_exact_portable_yaml_bytes(){
        let suite:Value=serde_json::from_str(include_str!("../../../tests/fixtures/workflow-file-sync.json")).unwrap();
        let doc:WorkflowFileDocument=serde_json::from_str(r#"{"format":"openmates-workflow","format_version":1,"workflow":{"title":"Updated","description":null,"run_content_retention":"last_5","graph":{"version":1,"trigger_node_id":null,"nodes":[],"edges":[]}},"binding_requirements":[]}"#).unwrap();
        let(name,yaml)=serialize_workflow_file(&doc).unwrap();
        assert_eq!(name,"updated.workflow.yml");
        assert_eq!(yaml,suite["capabilities"]["work.project-workflow-file-sync.v1"]["expected_yaml"]);
        assert_eq!(workflow_file_name(" Ｍy / Workflow.workflow.yml "),"my_-_workflow.workflow.yml");
    }
}
