//! Chat-to-Project unlink adapter. Selectors are currently full chat UUIDs;
//! Project selectors use the existing SDK resolver, with its documented limits.
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::{CliError, CliOutput, Invocation};
use crate::{client::Client, error::Error};
use openmates_sdk::work::{ProjectFilters, ProjectItemType};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

pub(super) fn supported(i: &Invocation) -> bool {
    i.command_path() == "chats remove-from-project"
}
fn unsupported(i: &Invocation, reason: &str) -> CliError {
    CliError::Unsupported {
        command: i.command_path(),
        reason: reason.into(),
    }
}
fn arguments(i: &Invocation) -> Result<(String, &str), CliError> {
    if !supported(i) {
        return Err(unsupported(
            i,
            "This adapter only removes a chat link from a Project.",
        ));
    }
    super::handlers::flags(i, &["personal", "team"])?;
    if i.has("api-key") {
        return Err(unsupported(
            i,
            "Chat remove-from-project requires an authenticated Cookie session; API-key credentials are not supported.",
        ));
    }
    if i.boolean("personal") && i.has("team") {
        return Err(CliError::Invalid(
            "Choose --personal or --team, not both.".into(),
        ));
    }
    if i.has("team") {
        return Err(unsupported(
            i,
            "Native chat remove-from-project currently supports Personal Cookie sessions. Team and Direct chat links are not ported.",
        ));
    }
    if i.positionals.len() != 2 || i.positionals[1].trim().is_empty() {
        return Err(CliError::Invalid(
            "Supply exactly <full-chat-uuid> and <project-selector>.".into(),
        ));
    }
    let chat = uuid::Uuid::parse_str(&i.positionals[0]).ok().filter(|id| id.to_string() == i.positionals[0].to_ascii_lowercase()).ok_or_else(|| unsupported(i, "Use the full hyphenated chat UUID. Short IDs, slugs, titles and last are not ported for this command."))?;
    Ok((chat.to_string(), &i.positionals[1]))
}
#[derive(Clone, Copy)]
enum Context {
    Missing,
    Personal,
    Team,
}
trait Backend {
    fn context(&self) -> Context;
    async fn project(&mut self, selector: &str) -> Result<Value, Error>;
    async fn chat(&mut self, id: &str) -> Result<String, Error>;
    async fn unlink(
        &mut self,
        project: &str,
        kind: ProjectItemType,
        chat: &str,
        confirmed: bool,
    ) -> Result<Value, Error>;
}
struct Cookie<'a>(&'a mut Client);
impl Backend for Cookie<'_> {
    fn context(&self) -> Context {
        match self.0.session() {
            None => Context::Missing,
            Some(session) if session.active_team_id.is_some() => Context::Team,
            Some(_) => Context::Personal,
        }
    }
    async fn project(&mut self, selector: &str) -> Result<Value, Error> {
        self.0
            .projects()
            .with_filters(ProjectFilters {
                personal: true,
                ..Default::default()
            })
            .show(selector)
            .await
    }
    async fn chat(&mut self, id: &str) -> Result<String, Error> {
        Ok(self.0.open_chat(id).await?.id)
    }
    async fn unlink(
        &mut self,
        project: &str,
        kind: ProjectItemType,
        chat: &str,
        confirmed: bool,
    ) -> Result<Value, Error> {
        self.0
            .projects()
            .with_filters(ProjectFilters {
                personal: true,
                ..Default::default()
            })
            .unlink_item(project, kind, chat, confirmed)
            .await
    }
}
fn active(backend: &impl Backend, cancel: &CancellationToken) -> Result<(), CliError> {
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    match backend.context() {
        Context::Missing => Err(Error::Authentication.into()),
        Context::Team => Err(Error::Forbidden.into()),
        Context::Personal => Ok(()),
    }
}
fn acknowledgement(
    i: &Invocation,
    project: &str,
    chat: &str,
    receipt: Value,
) -> Result<CliOutput, CliError> {
    let deleted = receipt["deleted"].as_bool().ok_or(Error::Protocol)?;
    let count = receipt["deleted_count"].as_u64().ok_or(Error::Protocol)?;
    if receipt["project_id"].as_str() != Some(project)
        || receipt["target_id"].as_str() != Some(chat)
        || deleted != (count > 0)
    {
        return Err(Error::Protocol.into());
    }
    if i.boolean("json") {
        CliOutput::json(
            &json!({"objectType":"chat","objectId":chat,"projectId":project,"deleted":deleted,"deletedCount":count}),
        )
    } else {
        Ok(CliOutput::text(if deleted {
            format!("chat removed from Project: {project}")
        } else {
            format!("chat was not linked to Project: {project}")
        }))
    }
}
async fn execute_backend(
    i: &Invocation,
    backend: &mut impl Backend,
    cancel: &CancellationToken,
) -> Result<CliOutput, CliError> {
    let (chat, selector) = arguments(i)?;
    match backend.context() {
        Context::Missing => return Err(Error::Authentication.into()),
        Context::Team => {
            return Err(unsupported(
                i,
                "Native chat remove-from-project currently supports Personal Cookie sessions. Switch to Personal before unlinking a chat.",
            ));
        }
        Context::Personal => {}
    }
    active(backend, cancel)?;
    // Legacy order: authenticate/resolve the Project before reading the chat.
    let project = backend.project(selector).await?;
    active(backend, cancel)?;
    let project = project["project_id"]
        .as_str()
        .filter(|id| uuid::Uuid::parse_str(id).is_ok())
        .ok_or(Error::Protocol)?
        .to_owned();
    let opened = backend.chat(&chat).await?;
    active(backend, cancel)?;
    if opened != chat {
        return Err(Error::Forbidden.into());
    }
    // The explicit unlink command is the user's confirmation; no new flag.
    // SDK permissions and the existing endpoint authorize the matching links.
    let receipt = backend
        .unlink(&project, ProjectItemType::Chat, &chat, true)
        .await?;
    // Preserve a known authoritative acknowledgement if cancellation arrives
    // after the write. Never turn it into an implicit retry or resource delete.
    acknowledgement(i, &project, &chat, receipt)
}
pub(super) async fn execute(
    i: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    client.set_operation_cancel(cancel.clone());
    execute_backend(i, &mut Cookie(client), &cancel).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    const CHAT: &str = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    const PROJECT: &str = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
    fn invocation(json: bool) -> Invocation {
        Invocation {
            path: vec!["chats".into(), "remove-from-project".into()],
            positionals: vec![CHAT.into(), "engineering".into()],
            flags: if json {
                BTreeMap::from([("json".into(), json!(true))])
            } else {
                BTreeMap::new()
            },
        }
    }
    struct Fake {
        context: Context,
        calls: Vec<String>,
        failure: Option<&'static str>,
        receipt: Value,
        cancel_after: Option<&'static str>,
        context_after: Option<(&'static str, Context)>,
        cancel: CancellationToken,
    }
    impl Fake {
        fn new(deleted: bool, count: u64) -> Self {
            Self {
                context: Context::Personal,
                calls: vec![],
                failure: None,
                receipt: json!({"project_id":PROJECT,"target_id":CHAT,"deleted":deleted,"deleted_count":count,"private_extra":"must not enter output"}),
                cancel_after: None,
                context_after: None,
                cancel: CancellationToken::new(),
            }
        }
        fn record(&mut self, call: &'static str) -> Result<(), Error> {
            self.calls.push(call.into());
            if self.cancel_after == Some(call) {
                self.cancel.cancel();
            }
            if let Some((after, context)) = self.context_after
                && after == call
            {
                self.context = context;
            }
            if self.failure == Some(call) {
                Err(if call == "unlink" {
                    Error::Offline
                } else {
                    Error::Forbidden
                })
            } else {
                Ok(())
            }
        }
    }
    impl Backend for Fake {
        fn context(&self) -> Context {
            self.context
        }
        async fn project(&mut self, selector: &str) -> Result<Value, Error> {
            assert_eq!(selector, "engineering");
            self.record("project")?;
            Ok(json!({"project_id":PROJECT,"name":"private project name"}))
        }
        async fn chat(&mut self, id: &str) -> Result<String, Error> {
            assert_eq!(id, CHAT);
            self.record("chat")?;
            Ok(CHAT.into())
        }
        async fn unlink(
            &mut self,
            project: &str,
            kind: ProjectItemType,
            chat: &str,
            confirmed: bool,
        ) -> Result<Value, Error> {
            assert_eq!(project, PROJECT);
            assert_eq!(chat, CHAT);
            assert!(matches!(kind, ProjectItemType::Chat));
            assert!(confirmed);
            self.record("unlink")?;
            Ok(self.receipt.clone())
        }
    }
    #[tokio::test]
    async fn legacy_acknowledgements_preserve_absent_links_and_exact_output_shape() {
        for (deleted, count) in [(false, 0), (true, 2)] {
            for json_output in [false, true] {
                let i = invocation(json_output);
                let mut backend = Fake::new(deleted, count);
                let cancel = backend.cancel.clone();
                let output = execute_backend(&i, &mut backend, &cancel)
                    .await
                    .ok()
                    .unwrap();
                assert_eq!(backend.calls, ["project", "chat", "unlink"]);
                assert_eq!(output.exit_code, 0);
                assert!(output.stderr.is_empty());
                if json_output {
                    assert_eq!(
                        serde_json::from_str::<Value>(&output.stdout).unwrap(),
                        json!({"objectType":"chat","objectId":CHAT,"projectId":PROJECT,"deleted":deleted,"deletedCount":count})
                    );
                } else {
                    assert_eq!(
                        output.stdout,
                        format!(
                            "chat {} Project: {PROJECT}\n",
                            if deleted {
                                "removed from"
                            } else {
                                "was not linked to"
                            }
                        )
                    );
                }
                assert!(!output.stdout.contains("private"));
            }
        }
    }
    #[tokio::test]
    async fn unsupported_selectors_flags_and_arity_fail_before_reads_or_mutations() {
        for selector in [
            "aaaaaaaa",
            "last",
            "__last__",
            "chat-slug",
            "Private chat title",
            "aaaaaaaaaaaa4aaa8aaaaaaaaaaaaaaa",
        ] {
            let mut i = invocation(false);
            i.positionals[0] = selector.into();
            let mut backend = Fake::new(true, 1);
            assert!(matches!(
                execute_backend(&i, &mut backend, &CancellationToken::new()).await,
                Err(CliError::Unsupported { .. })
            ));
            assert!(backend.calls.is_empty());
        }
        for case in 0..5 {
            let mut i = invocation(false);
            match case {
                0 => {
                    i.positionals.pop();
                }
                1 => i.positionals.push("extra".into()),
                2 => {
                    i.positionals[1] = " ".into();
                }
                3 => {
                    i.flags.insert("confirm".into(), json!(true));
                }
                _ => {
                    i.flags.insert("json".into(), json!([true, false]));
                }
            }
            let mut backend = Fake::new(true, 1);
            assert!(
                execute_backend(&i, &mut backend, &CancellationToken::new())
                    .await
                    .is_err()
            );
            assert!(backend.calls.is_empty());
        }
    }
    #[tokio::test]
    async fn credential_scope_and_cancellation_guards_never_fall_back_to_cookie_requests() {
        for case in 0..5 {
            let mut i = invocation(true);
            let mut backend = Fake::new(true, 1);
            match case {
                0 => {
                    i.flags.insert("api-key".into(), json!("synthetic-secret"));
                }
                1 => backend.context = Context::Team,
                2 => {
                    i.flags.insert("team".into(), json!(PROJECT));
                }
                3 => backend.context = Context::Missing,
                _ => backend.cancel.cancel(),
            }
            let cancel = backend.cancel.clone();
            assert!(execute_backend(&i, &mut backend, &cancel).await.is_err());
            assert!(backend.calls.is_empty());
        }
        let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
        assert!(matches!(
            execute(&invocation(false), &mut client, CancellationToken::new()).await,
            Err(CliError::Client(Error::Authentication))
        ));
    }
    #[tokio::test]
    async fn sdk_failures_and_cancelled_reads_stop_before_any_later_operation() {
        for (failed, calls) in [("project", 1), ("chat", 2), ("unlink", 3)] {
            let mut backend = Fake::new(true, 1);
            backend.failure = Some(failed);
            let cancel = backend.cancel.clone();
            assert!(
                execute_backend(&invocation(true), &mut backend, &cancel)
                    .await
                    .is_err()
            );
            assert_eq!(backend.calls.len(), calls);
        }
        for (after, calls) in [("project", 1), ("chat", 2)] {
            let mut backend = Fake::new(true, 1);
            backend.cancel_after = Some(after);
            let cancel = backend.cancel.clone();
            assert!(matches!(
                execute_backend(&invocation(true), &mut backend, &cancel).await,
                Err(CliError::Client(Error::Cancelled))
            ));
            assert_eq!(backend.calls.len(), calls);
        }
        let mut backend = Fake::new(true, 1);
        backend.cancel_after = Some("unlink");
        let cancel = backend.cancel.clone();
        let output = execute_backend(&invocation(true), &mut backend, &cancel)
            .await
            .ok()
            .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&output.stdout).unwrap()["deleted"],
            true
        );
        assert_eq!(backend.calls, ["project", "chat", "unlink"]);
    }
    #[tokio::test]
    async fn context_drift_after_reads_fails_before_unlink_without_claiming_cancellation() {
        for (after, calls) in [("project", 1), ("chat", 2)] {
            for (context, expected) in [
                (Context::Missing, Error::Authentication),
                (Context::Team, Error::Forbidden),
            ] {
                let mut backend = Fake::new(true, 1);
                backend.context_after = Some((after, context));
                let cancel = backend.cancel.clone();
                assert!(
                    matches!(execute_backend(&invocation(true), &mut backend, &cancel).await, Err(CliError::Client(error)) if error == expected)
                );
                assert_eq!(backend.calls.len(), calls);
                assert!(!backend.calls.iter().any(|call| call == "unlink"));
                assert!(!cancel.is_cancelled());
            }
        }
    }
    #[tokio::test]
    async fn malformed_or_foreign_unlink_receipts_are_errors_without_retry() {
        for (field, value) in [
            ("project_id", json!(CHAT)),
            ("target_id", json!(PROJECT)),
            ("deleted", json!(false)),
            ("deleted", Value::Null),
            ("deleted_count", json!(-1)),
            ("deleted_count", json!("1")),
            ("deleted_count", json!(0)),
        ] {
            let mut backend = Fake::new(true, 1);
            backend.receipt[field] = value;
            assert!(matches!(
                execute_backend(&invocation(true), &mut backend, &CancellationToken::new()).await,
                Err(CliError::Client(Error::Protocol))
            ));
            assert_eq!(backend.calls, ["project", "chat", "unlink"]);
        }
    }
}
