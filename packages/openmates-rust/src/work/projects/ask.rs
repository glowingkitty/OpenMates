//! Project ask admits only explicit encrypted mutation families.
use super::*;
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ProjectAskOptions {
    pub defaults: ProjectCreate,
    pub create: Option<ProjectCreate>,
    pub update: Option<ProjectAskUpdate>,
    pub updates: Vec<ProjectAskUpdate>,
    pub exact_delete: Option<ProjectAskDelete>,
    pub exact_deletes: Vec<ProjectAskDelete>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectAskUpdate {
    pub project_id: String,
    pub patch: ProjectPatch,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectAskDelete {
    pub project_id: String,
    pub confirmed: bool,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectProposal {
    pub name: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub icon: Option<String>,
    #[serde(default)]
    pub color: Option<String>,
}
impl Projects<'_> {
    fn ask_policy(&self, instruction: &str) -> Result<()> {
        self.scope()?;
        self.backend.verify_private_operation()?;
        if instruction.trim().is_empty() || instruction.chars().count() > 20_000 {
            return Err(Error::Invalid(
                "Project instructions require 1–20,000 characters.",
            ));
        }
        Ok(())
    }
    pub async fn plan_ask(
        &mut self,
        instruction: &str,
        chat_titles: Option<Vec<String>>,
    ) -> Result<ProjectProposal> {
        self.ask_policy(instruction)?;
        let mut payload = json!({"instruction":instruction});
        if let Some(titles) = chat_titles {
            if titles.is_empty()
                || titles.len() > 8
                || titles.iter().any(|s| s.chars().count() > 200)
            {
                return Err(Error::Invalid(
                    "Project title suggestions require 1–8 chat titles of at most 200 characters.",
                ));
            }
            payload["chat_titles"] = json!(titles);
        }
        let data = self
            .backend
            .request(Method::POST, "/v1/projects/ask/plan", Some(payload), None)
            .await?;
        let proposal: ProjectProposal = serde_json::from_value(data["proposed_project"].clone())
            .map_err(|_| Error::Protocol)?;
        if proposal.name.trim().is_empty()
            || proposal.name.len() > 100_000
            || proposal.description.len() > 1_000_000
        {
            return Err(Error::Protocol);
        }
        Ok(proposal)
    }
    pub async fn ask(&mut self, instruction: &str, options: ProjectAskOptions) -> Result<Value> {
        self.ask_policy(instruction)?;
        let operations = usize::from(options.create.is_some())
            + usize::from(options.update.is_some())
            + usize::from(!options.updates.is_empty())
            + usize::from(options.exact_delete.is_some())
            + usize::from(!options.exact_deletes.is_empty());
        if operations > 1 {
            return Err(Error::Invalid("Choose one Project ask operation family."));
        }
        let mut payload = json!({"instruction":instruction});
        let mut keys = std::collections::BTreeMap::<String, Key>::new();
        if let Some(create) = options.create {
            let (wire, key) = self.prepare_create(create).await?;
            keys.insert(string(&wire, "project_id")?.into(), key);
            payload["encrypted_create"] = wire;
        } else if options.update.is_some() || !options.updates.is_empty() {
            let single = options.update.is_some();
            let rows = options.update.map(|v| vec![v]).unwrap_or(options.updates);
            if rows.len() > 100 {
                return Err(Error::Invalid(
                    "Project ask supports at most 100 exact targets.",
                ));
            }
            let mut wire = vec![];
            for update in rows {
                let (project, patch) = self.prepare_patch(&update.project_id, update.patch).await?;
                let id = string(&project.raw, "project_id")?.to_owned();
                if keys.insert(id.clone(), project.key).is_some() {
                    return Err(Error::Invalid("Duplicate Project ask targets."));
                }
                wire.push(json!({"project_id":id,"patch":patch}));
            }
            if single {
                payload["encrypted_update"] = wire.remove(0);
            } else {
                payload["encrypted_updates"] = json!(wire);
            }
        } else if options.exact_delete.is_some() || !options.exact_deletes.is_empty() {
            let single = options.exact_delete.is_some();
            let rows = options
                .exact_delete
                .map(|v| vec![v])
                .unwrap_or(options.exact_deletes);
            if rows.len() > 100 || rows.iter().any(|v| !v.confirmed) {
                return Err(Error::Invalid(
                    "Project deletion requires explicit confirmation for each of at most 100 targets.",
                ));
            }
            let mut wire = vec![];
            for delete in rows {
                let project = self.resolve(&delete.project_id).await?;
                let id = string(&project.raw, "project_id")?.to_owned();
                if keys.insert(id.clone(), project.key).is_some() {
                    return Err(Error::Invalid("Duplicate Project ask targets."));
                }
                wire.push(json!({"project_id":id,"version":project.raw["version"]}));
            }
            if single {
                payload["exact_delete"] = wire.remove(0);
            } else {
                payload["exact_deletes"] = json!(wire);
            }
        } else if !mutation(instruction) {
            let mut create = options.defaults;
            if create.write_mode.is_none() && !create.chat_organization_only {
                return Err(Error::Invalid("Choose an explicit Project write mode."));
            }
            let proposal = self.plan_ask(instruction, None).await?;
            create.name = proposal.name;
            if create.description.is_empty() {
                create.description = proposal.description;
            }
            if create.icon.is_none() {
                create.icon = proposal.icon;
            }
            if create.color.is_none() {
                create.color = proposal.color;
            }
            let (wire, key) = self.prepare_create(create).await?;
            keys.insert(string(&wire, "project_id")?.into(), key);
            payload["encrypted_create"] = wire;
        }
        let route = self.path("/v1/projects/ask", &[]);
        let data = self
            .backend
            .request(Method::POST, &route, Some(payload), None)
            .await?;
        let mut output = sanitize(&data);
        let rows = data["projects"].as_array().cloned().unwrap_or_else(|| {
            data.get("project")
                .filter(|v| v.is_object())
                .cloned()
                .into_iter()
                .collect()
        });
        let mut projects = vec![];
        for row in rows {
            let id = string(&row, "project_id")?;
            let key = if let Some(key) = keys.get(id) {
                key.clone()
            } else {
                return Err(Error::Forbidden);
            };
            projects.push(decode(row, key)?.public);
        }
        output["project"] = if projects.len() == 1 {
            projects[0].clone()
        } else {
            Value::Null
        };
        output["projects"] = json!(projects);
        Ok(output)
    }
}
fn mutation(instruction: &str) -> bool {
    regex::Regex::new(
        r"(?i)\b(archive|unarchive|delete|remove|rename|retitle|pin|unpin|edit|update|change)\b",
    )
    .expect("constant Project mutation pattern")
    .is_match(instruction)
}
fn sanitize(value: &Value) -> Value {
    match value {
        Value::Object(map) => Value::Object(
            map.iter()
                .filter(|(key, _)| {
                    !key.starts_with("encrypted_")
                        && !key.starts_with("hashed_")
                        && key.as_str() != "key_wrappers"
                })
                .map(|(k, v)| (k.clone(), sanitize(v)))
                .collect(),
        ),
        Value::Array(rows) => Value::Array(rows.iter().map(sanitize).collect()),
        _ => value.clone(),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::work::tasks::tests::{client, mock};
    #[tokio::test]
    async fn ambiguous_mutation_is_fallback_and_never_a_new_project() {
        let (api, server) = mock(vec![json!({"fallback_to_chat":true,"applied":false})]).await;
        let mut client = client(&api);
        let result = client
            .projects()
            .ask("delete the old project", Default::default())
            .await
            .unwrap();
        assert_eq!(result["fallback_to_chat"], true);
        let request = server.await.unwrap();
        let payload: Value =
            serde_json::from_str(request[0].split("\r\n\r\n").nth(1).unwrap()).unwrap();
        assert_eq!(payload, json!({"instruction":"delete the old project"}));
    }
    #[tokio::test]
    async fn destructive_and_private_policy_rejections_precede_network() {
        let mut client = client("http://127.0.0.1:1");
        let options = ProjectAskOptions {
            exact_delete: Some(ProjectAskDelete {
                project_id: "project".into(),
                confirmed: false,
            }),
            ..Default::default()
        };
        assert!(matches!(
            client.projects().ask("delete project", options).await,
            Err(Error::Invalid(_))
        ));
        client.set_private_operation_gate(Some(std::sync::Arc::new(|| Err(Error::Forbidden))));
        assert!(matches!(
            client.projects().plan_ask("project", None).await,
            Err(Error::Forbidden)
        ));
    }
}
