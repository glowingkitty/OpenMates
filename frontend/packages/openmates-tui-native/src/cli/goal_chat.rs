//! Goal-chat orchestration over the existing saved-send and encrypted Plan APIs.
//! Saved-chat recovery remains explicit while Plan acknowledgements are pending.
use super::{CliError, CliOutput, Invocation, send, task_input};
use crate::{client::Client, error::Error};
use openmates_sdk::work::{PlanCreate, PlanFilters, ProjectFilters};
use serde_json::Value;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;
#[cfg(test)]
mod tests;

pub(super) fn supported(i: &Invocation) -> bool {
    i.command_path() == "chat" && i.has("goal")
}
struct Arguments {
    goal: Zeroizing<String>,
    title: Zeroizing<String>,
    status: Option<String>,
    projects: Vec<String>,
    send: Invocation,
}
fn arguments(i: &Invocation) -> Result<Arguments, CliError> {
    if !supported(i) || !i.positionals.is_empty() {
        return Err(CliError::Invalid(
            "Use chat --goal <goal> --project <id>; positional chat messages are not supported."
                .into(),
        ));
    }
    // Repeated Project selectors retain the existing Plan CSV/dedup rules.
    let mut checked = Invocation {
        path: i.path.clone(),
        positionals: vec![],
        flags: i.flags.clone(),
    };
    for key in ["project", "projects"] {
        checked.flags.remove(key);
    }
    super::handlers::flags(
        &checked,
        &[
            "goal",
            "message",
            "title",
            "status",
            "summary",
            "personal",
            "team",
            "auto-approve",
            "auto-approve-memories",
            "accept-task-proposals",
            "no-pii-detection",
            "response-timeout-seconds",
        ],
    )?;
    if i.has("api-key") {
        return Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "Goal chat requires a paired Cookie session; API-key clients must use the SDK."
                .into(),
        });
    }
    if i.boolean("accept-task-proposals") {
        return Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "Native Task proposal acceptance is not ported. No chat or Plan was created."
                .into(),
        });
    }
    if i.boolean("personal") && i.has("team") {
        return Err(CliError::Invalid(
            "Choose --personal or --team, not both.".into(),
        ));
    }
    if i.has("team") {
        task_input::required(i, "team")?;
    }
    let goal = Zeroizing::new(task_input::required(i, "goal")?.trim().to_owned());
    let title = Zeroizing::new(
        task_input::text(i, "title")?
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .unwrap_or(goal.as_str())
            .to_owned(),
    );
    if goal.len() > 1_000_000 || title.len() > 1_000_000 {
        return Err(CliError::Invalid(
            "Plan text exceeds the supported limit.".into(),
        ));
    }
    openmates_sdk::crypto::normalize_object_slug(title.as_str())?;
    let status = task_input::text(i, "status")?
        .map(|s| {
            if [
                "draft",
                "checking_assumptions",
                "awaiting_confirmation",
                "active",
                "executing",
                "running_checks",
                "blocked",
                "completed",
                "archived",
            ]
            .contains(&s)
            {
                Ok(s.to_owned())
            } else {
                Err(CliError::Invalid("Unknown Plan status.".into()))
            }
        })
        .transpose()?;
    for key in ["project", "projects"] {
        if i.has(key) && i.values(key).is_empty() {
            return Err(CliError::Invalid("Project links require a value.".into()));
        }
    }
    let projects = task_input::ids(i, &["project", "projects"]);
    if projects.is_empty() {
        return Err(CliError::Invalid(
            "Creating a Plan requires --project <id>.".into(),
        ));
    }
    let message = task_input::text(i, "message")?
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or(goal.as_str())
        .to_owned();
    // --summary was advertised but unused by the legacy goal path. Accept it
    // without adding a new Plan field or changing the inference message.
    let mut flags = i.flags.clone();
    for key in [
        "goal",
        "message",
        "title",
        "status",
        "summary",
        "project",
        "projects",
        "personal",
        "team",
        "accept-task-proposals",
    ] {
        flags.remove(key);
    }
    let send = Invocation {
        path: vec!["chats".into(), "new".into()],
        positionals: vec![message],
        flags,
    };
    // Validate timeout/options before any Project lookup or inference.
    send::validate_saved(&send)?;
    Ok(Arguments {
        goal,
        title,
        status,
        projects,
        send,
    })
}
trait Backend {
    fn admission(&self) -> Result<(), Error>;
    async fn project(&mut self, selector: &str) -> Result<String, Error>;
    async fn send(
        &mut self,
        i: &Invocation,
        cancel: CancellationToken,
    ) -> Result<send::ObservedSend, CliError>;
    async fn plan(&mut self, input: PlanCreate) -> Result<Value, Error>;
}
struct Cookie<'a>(&'a mut Client);
impl Backend for Cookie<'_> {
    fn admission(&self) -> Result<(), Error> {
        let session = self.0.session().ok_or(Error::Authentication)?;
        if session.is_expired() {
            return Err(Error::Expired);
        }
        if session.active_team_id.is_some() {
            // Match Plans::scope exactly: the server accepts Plan writes only
            // from the personal owner, so a Team goal chat fails before
            // inference. No automatic Personal fallback.
            return Err(Error::Unavailable {
                code: "team_plan_writes_unavailable",
                reason: "TEAM_PLAN_WRITES_PERSONAL_OWNER_ONLY",
            });
        }
        Ok(())
    }
    async fn project(&mut self, selector: &str) -> Result<String, Error> {
        let value = self
            .0
            .projects()
            .with_filters(ProjectFilters {
                personal: true,
                ..Default::default()
            })
            .show(selector)
            .await?;
        let id = value["project_id"]
            .as_str()
            .filter(|s| uuid::Uuid::parse_str(s).is_ok())
            .ok_or(Error::Protocol)?;
        Ok(id.to_owned())
    }
    async fn send(
        &mut self,
        i: &Invocation,
        cancel: CancellationToken,
    ) -> Result<send::ObservedSend, CliError> {
        send::observe_saved(i, self.0, cancel).await
    }
    async fn plan(&mut self, input: PlanCreate) -> Result<Value, Error> {
        self.0
            .plans()
            .with_filters(PlanFilters {
                personal: true,
                ..Default::default()
            })
            .create(input)
            .await
    }
}
fn active(backend: &impl Backend, cancel: &CancellationToken) -> Result<(), Error> {
    if cancel.is_cancelled() {
        return Err(Error::Cancelled);
    }
    backend.admission()
}
fn recovery(chat_id: &str, source: Error) -> CliError {
    // Preserve exit130 and saved-chat recovery. Never rerun inference or blindly
    // retry a Plan whose response may have been lost; inspect chat/Plan history.
    CliError::RecoveryRequired {
        chat_id: Some(chat_id.to_owned()),
        source,
    }
}
fn json_result(
    outcome: &openmates_sdk::client::SendOutcome,
    plan: Value,
) -> Result<CliOutput, CliError> {
    let mut value = send::outcome_json(outcome)?;
    value["chat_id"] = Value::String(outcome.chat_id.clone());
    value["plan"] = plan;
    CliOutput::json(&value)
}
async fn execute_backend(
    i: &Invocation,
    backend: &mut impl Backend,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    execute_with_writer(i, backend, cancel, &mut std::io::stdout()).await
}
async fn execute_with_writer(
    i: &Invocation,
    backend: &mut impl Backend,
    cancel: CancellationToken,
    stdout: &mut impl std::io::Write,
) -> Result<CliOutput, CliError> {
    let args = arguments(i)?;
    active(backend, &cancel)?;
    let mut projects = vec![];
    for selector in &args.projects {
        let id = backend.project(selector).await?;
        active(backend, &cancel)?;
        if !projects.contains(&id) {
            projects.push(id);
        }
    }
    // Selected Projects link the Plan; legacy goal-chat does not bind the send
    // itself to a Project. The existing SDK's Project-send gap is not bypassed.
    let observed = backend.send(&args.send, cancel.clone()).await?;
    let chat_id = observed.outcome.chat_id.clone();
    if uuid::Uuid::parse_str(&chat_id).is_err() {
        return Err(CliError::RecoveryRequired {
            chat_id: None,
            source: Error::Protocol,
        });
    }
    active(backend, &cancel).map_err(|e| recovery(&chat_id, e))?;
    let input = PlanCreate {
        title: args.title.to_string(),
        goal: args.goal.to_string(),
        status: args.status,
        primary_chat_id: Some(chat_id.clone()),
        linked_project_ids: projects,
        ..Default::default()
    };
    // One send, then one Plan mutation. No retry on any failure boundary.
    // Retain the saved UUID locally while an acknowledgement is pending. The
    // application may drop a slow cancelled command after its grace period;
    // return recovery here first, without relying on the generic drop fallback.
    // Dropping this HTTP future does not prove the Plan was rejected remotely.
    let plan = tokio::select! {
        biased;
        _ = cancel.cancelled() => return Err(recovery(&chat_id, Error::Cancelled)),
        result = backend.plan(input) => result.map_err(|e| recovery(&chat_id, e))?,
    };
    active(backend, &cancel).map_err(|e| recovery(&chat_id, e))?;
    if i.boolean("json") {
        return json_result(&observed.outcome, plan);
    }
    let mut output = observed
        .finish(false, stdout)
        .map_err(|error| match error {
            CliError::Client(source) => recovery(&chat_id, source),
            other => other,
        })?;
    let id = plan["short_id"]
        .as_str()
        .or_else(|| plan["plan_id"].as_str())
        .ok_or_else(|| recovery(&chat_id, Error::Protocol))?;
    let status = plan["status"]
        .as_str()
        .ok_or_else(|| recovery(&chat_id, Error::Protocol))?;
    output.stdout.push_str(&super::terminal_text(&format!("\nPlan attached: {id} ({})\nPlan:     openmates plans show {id}\nContinue: openmates chats send --chat {} \"your message\"\n", status.replace('_', " "), &chat_id[..8])));
    Ok(output)
}
pub(super) async fn execute(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    execute_backend(i, &mut Cookie(client), cancel).await
}
