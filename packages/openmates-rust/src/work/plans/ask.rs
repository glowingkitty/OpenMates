//! Plan ask uses canonical proposal planning and locally encrypted mutations.
use super::*;
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PlanAskOptions {
    pub defaults: PlanCreate,
    pub create: Option<PlanCreate>,
    pub update: Option<PlanAskUpdate>,
    pub updates: Vec<PlanAskUpdate>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PlanAskUpdate {
    pub plan_id: String,
    pub patch: PlanPatch,
}
#[derive(Clone, Serialize, Deserialize)]
pub struct PlanProposal {
    pub title: String,
    #[serde(default)]
    pub summary: String,
    #[serde(default)]
    pub goal: String,
}
impl Plans<'_> {
    fn ask_policy(&self, instruction: &str) -> Result<()> {
        self.scope()?;
        self.tasks.backend.verify_private_operation()?;
        if instruction.trim().is_empty() || instruction.chars().count() > 20_000 {
            return Err(Error::Invalid(
                "Plan instructions require 1–20,000 characters.",
            ));
        }
        Ok(())
    }
    pub async fn plan_ask(&mut self, instruction: &str) -> Result<PlanProposal> {
        self.ask_policy(instruction)?;
        let value = self
            .tasks
            .backend
            .request(
                Method::POST,
                "/v1/user-plans/ask/plan",
                Some(json!({"instruction":instruction})),
                None,
            )
            .await?;
        let proposal: PlanProposal =
            serde_json::from_value(value["proposed_plan"].clone()).map_err(|_| Error::Protocol)?;
        if proposal.title.trim().is_empty()
            || proposal.title.len() > 100_000
            || proposal.goal.len() > 1_000_000
            || proposal.summary.len() > 1_000_000
        {
            return Err(Error::Protocol);
        }
        Ok(proposal)
    }
    pub async fn ask(&mut self, instruction: &str, options: PlanAskOptions) -> Result<Value> {
        self.ask_policy(instruction)?;
        let mut payload = json!({"instruction":instruction});
        let operations = usize::from(options.create.is_some())
            + usize::from(options.update.is_some())
            + usize::from(!options.updates.is_empty());
        if operations > 1 {
            return Err(Error::Invalid("Choose one Plan ask operation family."));
        }
        if let Some(create) = options.create {
            payload["encrypted_create"] = self.prepare_create_wire(create).await?;
        } else if let Some(update) = options.update {
            let (id, patch) = self
                .prepare_patch_wire(&update.plan_id, update.patch)
                .await?;
            payload["encrypted_update"] = json!({"plan_id":id,"patch":patch});
        } else if !options.updates.is_empty() {
            if options.updates.len() > 100 {
                return Err(Error::Invalid(
                    "Plan ask supports at most 100 exact updates.",
                ));
            }
            let mut rows = vec![];
            let mut ids = std::collections::BTreeSet::new();
            for update in options.updates {
                let (id, patch) = self
                    .prepare_patch_wire(&update.plan_id, update.patch)
                    .await?;
                if !ids.insert(id.clone()) {
                    return Err(Error::Invalid("Duplicate Plan ask targets."));
                }
                rows.push(json!({"plan_id":id,"patch":patch}));
            }
            payload["encrypted_updates"] = json!(rows);
        } else if let Some(target) = target(instruction) {
            let previous = self.filters.status.take();
            let plan = self.resolve(&target).await;
            self.filters.status = previous;
            match plan {
                Ok(plan) => {
                    let patch = PlanPatch {
                        title: rename(instruction),
                        status: status(instruction).map(str::to_owned),
                        ..Default::default()
                    };
                    if patch.title.is_some() || patch.status.is_some() {
                        let master = self.tasks.backend.master().await?;
                        payload["encrypted_update"] = json!({"plan_id":plan.raw["plan_id"],"patch":encode_patch(&plan,&patch,&master)?});
                    }
                }
                Err(Error::Invalid(_)) => {}
                Err(error) => return Err(error),
            }
        } else if !mutation(instruction) {
            let mut create = options.defaults;
            if create.linked_project_ids.is_empty() {
                return Err(Error::Invalid(
                    "Creating a Plan requires at least one Project link.",
                ));
            }
            let proposal = if short(instruction) {
                PlanProposal {
                    title: instruction.into(),
                    summary: String::new(),
                    goal: instruction.into(),
                }
            } else {
                self.plan_ask(instruction).await?
            };
            create.title = proposal.title;
            if create.goal.trim().is_empty() {
                create.goal = if !proposal.goal.trim().is_empty() {
                    proposal.goal
                } else if !proposal.summary.trim().is_empty() {
                    proposal.summary
                } else {
                    create.title.clone()
                };
            }
            payload["encrypted_create"] = self.prepare_create_wire(create).await?;
        }
        let value = self
            .tasks
            .backend
            .request(Method::POST, "/v1/user-plans/ask", Some(payload), None)
            .await?;
        let master = self.tasks.backend.master().await?;
        let mut output = sanitize(&value);
        if let Some(plan) = value.get("plan").filter(|p| p.is_object()) {
            output["plan"] = decode(plan.clone(), &master)?.public;
        }
        if let Some(plans) = value.get("plans").and_then(Value::as_array) {
            output["plans"] = json!(
                plans
                    .iter()
                    .map(|p| decode(p.clone(), &master).map(|p| p.public))
                    .collect::<Result<Vec<_>>>()?
            );
        }
        Ok(output)
    }
}
fn regex(pattern: &str) -> regex::Regex {
    regex::Regex::new(pattern).expect("constant Plan ask pattern")
}
fn target(text: &str) -> Option<String> {
    let pattern = regex(r#"(?i)@plan:("[^"]+"|'[^']+'|[^\s,;]+)"#);
    let value = strip(pattern.captures(text)?.get(1)?.as_str().trim())
        .trim_end_matches(['.', ')', '!', '?'])
        .trim();
    (!value.is_empty()).then(|| value.into())
}
fn strip(text: &str) -> &str {
    if text.len() >= 2
        && ((text.starts_with('"') && text.ends_with('"'))
            || (text.starts_with('\'') && text.ends_with('\'')))
    {
        &text[1..text.len() - 1]
    } else {
        text
    }
}
fn rename(text: &str) -> Option<String> {
    if !regex(r"(?i)\b(rename|retitle|title|name|call)\b").is_match(text) {
        return None;
    }
    let pattern = regex(r"(?i)\bto\s+(.+)$");
    let value = strip(pattern.captures(text)?.get(1)?.as_str().trim())
        .trim_end_matches('.')
        .trim();
    (!value.is_empty()).then(|| value.into())
}
fn status(text: &str) -> Option<&'static str> {
    for (pattern, status) in [
        (r"(?i)\bunarchive\b", "active"),
        (r"(?i)\barchive|archived\b", "archived"),
        (r"(?i)\bactivate|resume|start\b", "active"),
        (r"(?i)\bcomplete|completed|done\b", "completed"),
        (r"(?i)\bblock|blocked\b", "blocked"),
    ] {
        if regex(pattern).is_match(text) {
            return Some(status);
        }
    }
    None
}
fn mutation(text: &str) -> bool {
    regex(r"(?i)\b(archive|unarchive|delete|remove|rename|retitle|activate|resume|complete|completed|done|blocked?)\b").is_match(text)
}
fn short(text: &str) -> bool {
    !text.trim().is_empty()
        && !text.contains('\n')
        && !regex(r"(^|\s)([-*]|\d+\.)\s").is_match(text)
        && text.split_whitespace().count() <= 8
}
fn sanitize(value: &Value) -> Value {
    match value {
        Value::Object(map) => Value::Object(
            map.iter()
                .filter(|(key, _)| {
                    !key.starts_with("encrypted_")
                        && !key.starts_with("hashed_")
                        && key.as_str() != "linked_project_hashes"
                })
                .map(|(key, v)| (key.clone(), sanitize(v)))
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
    const PROJECT: &str = "bbaaccdd-1111-4111-8111-aabbccddeeff";
    #[test]
    fn target_and_status_preserve_existing_plan_ask_rules() {
        assert_eq!(
            target("rename @plan:'launch plan' to Better scope"),
            Some("launch plan".into())
        );
        assert_eq!(
            rename("rename @plan:PLAN-ABCD to 'Better scope'"),
            Some("Better scope".into())
        );
        assert_eq!(status("unarchive @plan:PLAN-ABCD"), Some("active"));
        assert_eq!(status("complete @plan:PLAN-ABCD"), Some("completed"));
        assert!(mutation("rename all plans"));
    }
    #[tokio::test]
    async fn ambiguous_mutation_preserves_server_fallback_without_creates() {
        let (api, server) = mock(vec![
            json!({"outcome":"fallback_to_chat","fallback_message":"Select an exact Plan"}),
        ])
        .await;
        let result = client(&api)
            .plans()
            .ask("archive all plans", PlanAskOptions::default())
            .await
            .unwrap();
        assert_eq!(result["outcome"], "fallback_to_chat");
        let request = server.await.unwrap().remove(0);
        let body: Value = serde_json::from_str(request.split_once("\r\n\r\n").unwrap().1).unwrap();
        assert_eq!(body, json!({"instruction":"archive all plans"}));
    }
    #[tokio::test]
    async fn short_plan_create_wraps_fresh_project_key_and_never_posts_private_fields() {
        let(api,server)=mock(vec![json!({"project":{"project_id":PROJECT,"encrypted_project_key":crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap()}}),json!({"outcome":"applied","plans":[]})]).await;
        let options = PlanAskOptions {
            defaults: PlanCreate {
                linked_project_ids: vec![PROJECT.into()],
                ..Default::default()
            },
            ..Default::default()
        };
        client(&api)
            .plans()
            .ask("Prepare private launch plan", options)
            .await
            .unwrap();
        let requests = server.await.unwrap();
        assert_eq!(requests.len(), 2);
        assert!(requests[1].starts_with("POST /v1/user-plans/ask "));
        let body: Value =
            serde_json::from_str(requests[1].split_once("\r\n\r\n").unwrap().1).unwrap();
        let create = &body["encrypted_create"];
        assert!(create.get("title").is_none());
        assert!(create.get("goal").is_none());
        let wrapper = create["key_wrappers"]
            .as_array()
            .unwrap()
            .iter()
            .find(|w| w["key_type"] == "master")
            .unwrap();
        let key = key_bytes(
            &crypto::decrypt_bytes(wrapper["encrypted_plan_key"].as_str().unwrap(), &[7; 32])
                .unwrap(),
        )
        .unwrap();
        assert_eq!(
            crypto::decrypt_combined(create["encrypted_title"].as_str().unwrap(), &key).unwrap(),
            "Prepare private launch plan"
        );
        assert!(body.get("model").is_none());
        assert!(body.get("provider").is_none());
    }
}
