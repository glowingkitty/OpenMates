//! Canonical Task ask orchestration: resolve exact targets locally, encrypt all
//! mutations locally, and use the existing automatic proposal-planning route.
use super::*;
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct TaskAskOptions {
    pub create: TaskCreate,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct TaskProposalContext {
    pub chat_id: Option<String>,
    pub project_ids: Vec<String>,
}
#[derive(Clone, Serialize, Deserialize)]
pub struct TaskProposal {
    pub title: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub assignee_type: Option<String>,
}
#[derive(Clone, Copy, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskExtractionMode {
    #[default]
    Create,
    Update,
}
impl Tasks<'_> {
    fn ask_policy(&self, text: &str) -> Result<()> {
        self.backend.verify_private_operation()?;
        if text.trim().is_empty() || text.chars().count() > 20_000 {
            return Err(Error::Invalid(
                "Task instructions require 1–20,000 characters.",
            ));
        }
        if self.filters.team_id.is_some() {
            return Err(Error::Unavailable {
                code: "team_task_ask_unavailable",
                reason: "TEAM_TASK_ASK_NOT_SUPPORTED",
            });
        }
        Ok(())
    }
    async fn proposal_context(
        &mut self,
        mut context: TaskProposalContext,
    ) -> Result<TaskProposalContext> {
        if let Some(chat) = &mut context.chat_id {
            *chat = self.reference("chat", chat).await?;
        }
        for project in &mut context.project_ids {
            *project = self.reference("project", project).await?;
        }
        Ok(context)
    }
    /// Plan Task proposals through existing automatic routing; does not persist.
    pub async fn plan_ask(
        &mut self,
        instruction: &str,
        context: TaskProposalContext,
    ) -> Result<Vec<TaskProposal>> {
        self.ask_policy(instruction)?;
        let context = self.proposal_context(context).await?;
        let value=self.backend.request(Method::POST,"/v1/user-tasks/ask/plan",Some(json!({"instruction":instruction,"context_chat_id":context.chat_id,"project_ids":context.project_ids})),None).await?;
        proposals(value)
    }
    /// Extract proposals from corrected text without applying durable changes.
    pub async fn extract_proposals(
        &mut self,
        text: &str,
        mode: TaskExtractionMode,
        context: TaskProposalContext,
    ) -> Result<Vec<TaskProposal>> {
        self.ask_policy(text)?;
        let context = self.proposal_context(context).await?;
        let value=self.backend.request(Method::POST,"/v1/user-tasks/extract",Some(json!({"corrected_text":text,"mode":mode,"context_chat_id":context.chat_id,"project_ids":context.project_ids})),None).await?;
        proposals(value)
    }
    /// Apply an explicit exact-target edit/delete, or plan and encrypt creates.
    /// Ambiguous mutation requests retain the server's actionable chat fallback.
    pub async fn ask(&mut self, instruction: &str, options: TaskAskOptions) -> Result<Value> {
        self.ask_policy(instruction)?;
        let mut payload = json!({"instruction":instruction});
        let mut headers = None;
        if let Some(target) = target(instruction) {
            let previous = self.filters.status.take();
            let resolved = self.resolve(&target).await;
            self.filters.status = previous;
            match resolved {
                Ok(task) => {
                    readonly(&task)?;
                    headers = Some(self.owner_headers(Some(&task), false)?);
                    if exact_delete(instruction) {
                        payload["exact_delete"] =
                            json!({"task_id":task.raw["task_id"],"version":task.raw["version"]});
                    } else {
                        let patch = TaskPatch {
                            title: rename(instruction),
                            status: status(instruction).map(str::to_owned),
                            ..Default::default()
                        };
                        if patch.title.is_some() || patch.status.is_some() {
                            let (master, wrapping) = self.keys().await?;
                            payload["encrypted_update"] = json!({"task_id":task.raw["task_id"],"patch":encrypt_patch(&task,&patch,&master,&wrapping)?});
                        }
                    }
                }
                Err(Error::Invalid(_)) => {}
                Err(error) => return Err(error),
            }
        } else if !mutation(instruction) {
            let proposal = if short(instruction) {
                vec![TaskProposal {
                    title: instruction.into(),
                    description: None,
                    status: None,
                    assignee_type: None,
                }]
            } else {
                let proposal = self
                    .plan_ask(
                        instruction,
                        TaskProposalContext {
                            chat_id: options.create.primary_chat_id.clone(),
                            project_ids: options.create.linked_project_ids.clone(),
                        },
                    )
                    .await?;
                if proposal.is_empty() {
                    split(instruction)
                } else {
                    proposal
                }
            };
            let mut encrypted = vec![];
            for proposal in proposal {
                let mut create = options.create.clone();
                create.title = proposal.title;
                create.description = proposal.description.unwrap_or_default();
                create.status = proposal.status.or(create.status);
                create.assign = proposal.assignee_type.or(create.assign);
                let create = self.canonical_create(create).await?;
                let (master, wrapping) = self.keys().await?;
                encrypted.push(encrypt_create(&create, &master, &wrapping, None)?);
            }
            payload["encrypted_creates"] = json!(encrypted);
        }
        let value = self
            .backend
            .request(
                Method::POST,
                "/v1/user-tasks/ask",
                Some(payload),
                headers.as_ref(),
            )
            .await?;
        let (master, wrapping) = self.keys().await?;
        let mut output = sanitize(&value);
        if let Some(raw) = value.get("task").filter(|v| v.is_object()) {
            output["task"] = decrypt(raw.clone(), &master, &wrapping, None)?.public;
        }
        if let Some(rows) = value.get("tasks").and_then(Value::as_array) {
            output["tasks"] = json!(
                rows.iter()
                    .map(|row| decrypt(row.clone(), &master, &wrapping, None).map(|t| t.public))
                    .collect::<Result<Vec<_>>>()?
            );
        }
        Ok(output)
    }
}
fn proposals(value: Value) -> Result<Vec<TaskProposal>> {
    let rows = value.get("proposed_tasks").ok_or(Error::Protocol)?;
    let rows: Vec<TaskProposal> =
        serde_json::from_value(rows.clone()).map_err(|_| Error::Protocol)?;
    if rows.len() > 100
        || rows
            .iter()
            .any(|row| row.title.trim().is_empty() || row.title.len() > 100_000)
    {
        return Err(Error::Protocol);
    }
    Ok(rows)
}
fn regex(pattern: &str) -> regex::Regex {
    regex::Regex::new(pattern).expect("constant Task ask expression")
}
fn target(text: &str) -> Option<String> {
    let pattern = regex(r#"(?i)@task:("[^"]+"|'[^']+'|[^\s,;]+)"#);
    let matched = pattern.captures(text)?.get(1)?.as_str().trim();
    let matched = strip_quotes(matched)
        .trim_end_matches(['.', ')', '!', '?'])
        .trim();
    (!matched.is_empty()).then(|| matched.into())
}
fn strip_quotes(text: &str) -> &str {
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
    let value = strip_quotes(pattern.captures(text)?.get(1)?.as_str().trim())
        .trim_end_matches('.')
        .trim();
    (!value.is_empty()).then(|| value.into())
}
fn status(text: &str) -> Option<&'static str> {
    for (pattern, status) in [
        (r"(?i)\bbacklog\b", "backlog"),
        (r"(?i)\b(to\s*do|todo)\b", "todo"),
        (r"(?i)\b(in[-_\s]?progress|start|started)\b", "in_progress"),
        (r"(?i)\b(block|blocked)\b", "blocked"),
        (r"(?i)\b(done|complete|completed|finish|finished)\b", "done"),
    ] {
        if regex(pattern).is_match(text) {
            return Some(status);
        }
    }
    None
}
fn exact_delete(text: &str) -> bool {
    regex(r"(?i)\bdelete\b[\s\S]*@task:|\bremove\s+@task:").is_match(text)
}
fn mutation(text: &str) -> bool {
    regex(r"(?i)\b(mark|delete|remove|finish|complete|completed|done|blocked?)\b").is_match(text)
}
fn short(text: &str) -> bool {
    !text.trim().is_empty()
        && !text.contains('\n')
        && !regex(r"(^|\s)([-*]|\d+\.)\s").is_match(text)
        && text.split_whitespace().count() <= 8
}
fn split(text: &str) -> Vec<TaskProposal> {
    let suffix = text.split_once(':').map(|(_, rest)| rest).unwrap_or(text);
    let rows = suffix
        .split([',', ';'])
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|s| TaskProposal {
            title: s.into(),
            description: None,
            status: None,
            assignee_type: None,
        })
        .collect::<Vec<_>>();
    if rows.is_empty() {
        vec![TaskProposal {
            title: text.into(),
            description: None,
            status: None,
            assignee_type: None,
        }]
    } else {
        rows
    }
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
                .map(|(key, value)| (key.clone(), sanitize(value)))
                .collect(),
        ),
        Value::Array(rows) => Value::Array(rows.iter().map(sanitize).collect()),
        _ => value.clone(),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_target_and_mutation_parse_matches_protocol() {
        assert_eq!(
            target("Mark @task:'launch copy' done."),
            Some("launch copy".into())
        );
        assert_eq!(
            target("rename @task:TASK-23 to Better title"),
            Some("TASK-23".into())
        );
        assert_eq!(
            rename("rename @task:TASK-23 to 'Better title'"),
            Some("Better title".into())
        );
        assert_eq!(status("mark @task:TASK-23 done"), Some("done"));
        assert!(exact_delete("delete @task:TASK-23"));
        assert!(mutation("mark all completed"));
        assert!(!short("1. launch\n2. check"));
    }
    #[tokio::test]
    async fn exact_ambiguous_mutation_does_not_create() {
        let (api, server) = super::super::tests::mock(vec![
            json!({"status":"fallback_chat","message":"Select exact tasks"}),
        ])
        .await;
        let value = super::super::tests::client(&api)
            .tasks()
            .ask("mark everything done", TaskAskOptions::default())
            .await
            .unwrap();
        assert_eq!(value["status"], "fallback_chat");
        let request = server.await.unwrap().remove(0);
        let body: Value = serde_json::from_str(request.split_once("\r\n\r\n").unwrap().1).unwrap();
        assert!(body.get("encrypted_creates").is_none());
        assert_eq!(body["instruction"], "mark everything done");
    }
    #[tokio::test]
    async fn short_create_contains_only_ciphertext_private_fields() {
        let (api, server) =
            super::super::tests::mock(vec![json!({"status":"applied","tasks":[]})]).await;
        super::super::tests::client(&api)
            .tasks()
            .ask("Prepare private launch copy", TaskAskOptions::default())
            .await
            .unwrap();
        let request = server.await.unwrap().remove(0);
        let body: Value = serde_json::from_str(request.split_once("\r\n\r\n").unwrap().1).unwrap();
        let create = &body["encrypted_creates"][0];
        assert!(create["encrypted_title"].is_string());
        assert!(create.get("title").is_none());
        assert!(create.get("plaintext_title").is_none());
        assert!(body.get("model").is_none());
        assert!(body.get("provider").is_none());
    }
}
