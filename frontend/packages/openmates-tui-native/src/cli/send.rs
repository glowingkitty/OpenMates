//! Incremental native chat output. Delivery state is tracked independently from
//! terminal writes so an interrupted submitted turn never becomes a blind retry.
#[cfg(test)]
mod ephemeral_tests;
mod questions;
use super::{CliError, CliOutput, Invocation, terminal_text};
use crate::{client::Client, error::Error, model::StreamUpdate};
use openmates_sdk::client::{SendConsentPolicy, SendOptions, SendOutcome, SendStatus};
use std::io::{self, Write};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

pub(super) fn incognito_history(invocation: &Invocation) -> Result<CliOutput, CliError> {
    super::handlers::flags(invocation, &[])?;
    if !invocation.positionals.is_empty() {
        return Err(CliError::Invalid(
            "Incognito history commands do not take message text.".into(),
        ));
    }
    let message = "Incognito chats are not stored. There is no incognito history to show or clear.";
    if invocation.boolean("json") {
        CliOutput::json(&serde_json::json!({"history":[],"stored":false,"message":message}))
    } else {
        Ok(CliOutput::text(message))
    }
}

#[derive(Default)]
struct Presentation {
    previous: Zeroizing<String>,
    written: bool,
    expects_reply: bool,
    pending: Option<(String, String, bool)>,
    io_failed: bool,
    approve_subchats: bool,
    approve_memories: bool,
    ephemeral: bool,
}
impl Presentation {
    fn content(&mut self, current: &str, writer: &mut impl Write) {
        let delta = current
            .strip_prefix(self.previous.as_str())
            .unwrap_or(current);
        if !delta.is_empty() && !self.io_failed {
            let prefix = if self.written && !current.starts_with(self.previous.as_str()) {
                "\n"
            } else {
                ""
            };
            self.io_failed = write!(writer, "{prefix}{}", terminal_text(delta))
                .and_then(|()| writer.flush())
                .is_err();
            self.written = true;
        }
        self.previous.clear();
        self.previous.push_str(current);
    }
    fn event(
        &mut self,
        event: StreamUpdate,
        json: bool,
        stdout: &mut impl Write,
        stderr: &mut impl Write,
        consent: &mpsc::UnboundedSender<(String, Vec<String>)>,
    ) {
        match event {
            StreamUpdate::Started { expects_reply, .. } => self.expects_reply = expects_reply,
            StreamUpdate::Submitted {
                chat_id,
                message_id,
            } => self.pending = Some((chat_id, message_id, false)),
            StreamUpdate::Admitted {
                chat_id,
                message_id,
            } => self.pending = Some((chat_id, message_id, true)),
            StreamUpdate::Content { content, .. } if !json => self.content(&content, stdout),
            StreamUpdate::Completed { content, .. }
                if !json && self.expects_reply && !content.is_empty() =>
            {
                self.content(&content, stdout)
            }
            StreamUpdate::Consent { request_id, items } => {
                let subchats = !items.is_empty()
                    && items
                        .iter()
                        .all(|item| item.fields["consent_kind"] == "sub_chats");
                let memories = items
                    .iter()
                    .all(|item| item.fields.get("consent_kind").is_none());
                let approved =
                    (subchats && self.approve_subchats) || (memories && self.approve_memories);
                let ids = if approved {
                    items.into_iter().map(|item| item.id).collect()
                } else {
                    vec![]
                };
                let _ = consent.send((request_id, ids));
                let message = match (approved, subchats) {
                    (true, true) => "Approved the requested sub-chat batch using --auto-approve.",
                    (true, false) => {
                        "Approved the requested memory categories using --auto-approve-memories."
                    }
                    (false, _) => {
                        "Requested private context/sub-chat approval was declined; explicit approval flags were not supplied for this request."
                    }
                };
                let _ = writeln!(stderr, "{message}").and_then(|()| stderr.flush());
            }
            StreamUpdate::Status(status) => {
                let _ =
                    writeln!(stderr, "{}", terminal_text(&status)).and_then(|()| stderr.flush());
            }
            _ => {}
        }
    }
    fn failure(self, error: Error) -> CliError {
        if self.ephemeral {
            // Volatile dispatch is never evidence of a saved message. In
            // particular cancellation must not tell users to inspect history.
            return CliError::Client(error);
        }
        // The server explicitly refused the durable preflight: nothing was
        // admitted, so this is not an uncertain turn needing recovery.
        if matches!(error, Error::Unavailable { code: "chat_turn_rejected", .. })
            && !self.pending.as_ref().is_some_and(|(_, _, admitted)| *admitted)
        {
            return CliError::Contract {
                code: "chat_turn_rejected",
                message: "The server rejected this message before saving it; nothing was admitted. Check the chat with `openmates chats show` before sending it again.".into(),
            };
        }
        match self.pending {
            Some((chat_id, message_id, admitted)) => CliError::PendingTurn {
                chat_id,
                message_id,
                admitted,
                source: error,
            },
            None => CliError::Client(error),
        }
    }
    fn finish_outcome(
        &mut self,
        outcome: &SendOutcome,
        json: bool,
        stdout: &mut impl Write,
    ) -> Result<CliOutput, CliError> {
        if json {
            return CliOutput::json(&outcome_json(outcome)?);
        }
        if outcome.message_id.is_some() && !outcome.assistant.is_empty() {
            self.content(&outcome.assistant, stdout);
        }
        if self.io_failed {
            return Err(Error::Io.into());
        }
        let mut text = if self.written {
            "\n".to_owned()
        } else {
            String::new()
        };
        if !outcome.follow_up_suggestions.is_empty() {
            text.push_str("Suggested follow-ups:\n");
            for suggestion in &outcome.follow_up_suggestions {
                text.push_str(&format!("  • {suggestion}\n"));
            }
        }
        if !outcome.recommendations.is_empty() {
            text.push_str("Recommendations:\n");
            for item in &outcome.recommendations {
                let field = |name: &str| terminal_text(item[name].as_str().unwrap_or(""));
                text.push_str(&format!(
                    "  - [{}] {} - {}\n",
                    field("kind"),
                    field("title"),
                    field("summary")
                ));
            }
        }
        for card in &outcome.project_creations {
            text.push_str(&super::projects::card_text(card));
        }
        if !outcome.task_events.is_empty() {
            text.push_str("Task updates:\n");
            for event in &outcome.task_events {
                let id = event["short_id"]
                    .as_str()
                    .or_else(|| event["task_id"].as_str())
                    .unwrap_or("");
                text.push_str(&format!(
                    "  - {id} {}",
                    event["event_type"].as_str().unwrap_or("")
                ));
                if let Some(title) = event["title"].as_str() {
                    text.push_str(&format!(" \"{title}\""));
                }
                if let Some(status) = event["status"].as_str() {
                    text.push_str(&format!(" ({status})"));
                }
                text.push('\n');
            }
        }
        if !outcome.pending_task_update_jobs.is_empty() {
            text.push_str(&format!(
                "Pending encrypted task updates: {}\n",
                outcome.pending_task_update_jobs.len()
            ));
        }
        text.push_str(&format!(
            "{}: {}",
            if self.ephemeral {
                "Chat (not stored)"
            } else {
                "Chat"
            },
            outcome.chat_id
        ));
        let mut output = CliOutput::text(text);
        match outcome.status {
            SendStatus::Queued => output.stderr = "Message queued for this chat. It will run after the active response finishes.\n".into(),
            SendStatus::WaitingForUser => output.stderr = "OpenMates needs more input to continue. Rerun with --json to inspect the structured waiting state.\n".into(),
            SendStatus::Completed=>{},
        }
        Ok(output)
    }
}
/// Presentation-neutral observed send. No final JSON object has been emitted.
/// Existing send and ask callers still finish using the same renderer.
pub(super) struct ObservedSend {
    pub outcome: SendOutcome,
    presentation: Presentation,
}
impl ObservedSend {
    pub(super) fn finish(
        mut self,
        json: bool,
        stdout: &mut impl Write,
    ) -> Result<CliOutput, CliError> {
        self.presentation
            .finish_outcome(&self.outcome, json, stdout)
    }
    #[cfg(test)]
    pub(super) fn synthetic(outcome: SendOutcome) -> Self {
        Self {
            outcome,
            presentation: Presentation::default(),
        }
    }
}
pub(super) fn outcome_json(outcome: &SendOutcome) -> Result<serde_json::Value, CliError> {
    if outcome.status == SendStatus::WaitingForUser
        && let Some(question) = questions::parse(&outcome.assistant)
    {
        return Ok(
            serde_json::json!({"status":"waiting_for_user","chat_id":outcome.chat_id,"message_id":outcome.message_id.as_deref().unwrap_or(""),"parent_id":outcome.chat_id,"question":question}),
        );
    }
    let mut value = serde_json::to_value(outcome).map_err(|_| Error::Protocol)?;
    // Task proposal acceptance is an explicit CLI post-action. That flag
    // is rejected until ported; ordinary sends perform no acceptance.
    value["acceptedTaskProposals"] = serde_json::json!([]);
    Ok(value)
}
#[cfg(test)]
pub(super) fn saved_options_for_test(invocation: &Invocation) -> Result<SendOptions, CliError> {
    options(invocation, false)
}
pub(super) fn validate_saved(invocation: &Invocation) -> Result<(), CliError> {
    options(invocation, false).map(|_| ())
}
fn options(invocation: &Invocation, interactive: bool) -> Result<SendOptions, CliError> {
    let mut allowed = vec![
        "chat",
        "personal",
        "team",
        "auto-approve",
        "auto-approve-memories",
        "no-task-update-jobs",
        "slug",
        "response-timeout-seconds",
        "no-pii-detection",
    ];
    if interactive {
        allowed.extend(["question-json", "answer-json"]);
    }
    if invocation.command_path() == "chats send" {
        allowed.push("incognito");
    }
    super::handlers::flags(invocation, &allowed)?;
    if invocation
        .path
        .get(1)
        .is_some_and(|command| command == "new")
        && invocation.has("chat")
    {
        return Err(CliError::Invalid(
            "--chat applies to chats send; chats new always creates a new chat.".into(),
        ));
    }
    let response_timeout_ms = super::task_input::text(invocation, "response-timeout-seconds")?
        .map(|seconds| {
            seconds
                .parse::<u64>()
                .ok()
                .filter(|value| *value > 0)
                .and_then(|value| value.checked_mul(1000))
                .ok_or_else(|| {
                    CliError::Invalid(
                        "--response-timeout-seconds must be a positive integer up to 86400.".into(),
                    )
                })
        })
        .transpose()?;
    let options = SendOptions {
        slug: super::task_input::text(invocation, "slug")?.map(str::to_owned),
        task_update_jobs: !invocation.boolean("no-task-update-jobs"),
        // The CLI renders the created-Project card and offers `projects undo-create`.
        project_create_requests: true,
        // Assistant Project file tool calls run in this chat; `--auto-approve` also
        // approves always-ask file writes, otherwise they are declined with a notice.
        project_file_jobs: true,
        approve_project_file_writes: invocation.boolean("auto-approve"),
        pii_detection: !invocation.boolean("no-pii-detection"),
        incognito: invocation.command_path() == "chats incognito"
            || invocation.boolean("incognito"),
        response_timeout_ms,
        sub_chat_consent: if invocation.boolean("auto-approve") {
            SendConsentPolicy::ApproveRequested
        } else {
            SendConsentPolicy::Reject
        },
        memory_consent: if invocation.boolean("auto-approve-memories") {
            SendConsentPolicy::ApproveRequested
        } else {
            SendConsentPolicy::Reject
        },
        ..SendOptions::default()
    };
    options
        .validate()
        .map_err(|error| CliError::Invalid(error.to_string()))?;
    if options.slug.is_some() && invocation.text("chat").is_some() {
        return Err(CliError::Invalid(
            "A slug applies only to a new chat.".into(),
        ));
    }
    if options.incognito {
        volatile_options(invocation, &options)?;
    }
    Ok(options)
}
fn volatile_options(invocation: &Invocation, options: &SendOptions) -> Result<(), CliError> {
    if invocation.has("personal") || invocation.has("team") {
        return Err(CliError::Unsupported {
            command: invocation.command_path(),
            reason:
                "Scope flags apply only to saved Chat sends. No volatile request was dispatched."
                    .into(),
        });
    }
    if invocation.has("chat") || options.slug.is_some() {
        return Err(CliError::Unsupported{command:invocation.command_path(),reason:"Volatile chats cannot use a saved chat or slug; native volatile continuation is not implemented.".into()});
    }
    if invocation.boolean("auto-approve") || invocation.boolean("auto-approve-memories") {
        return Err(CliError::Unsupported{command:invocation.command_path(),reason:"Volatile sends cannot approve saved memory or sub-chat operations. No request was dispatched.".into()});
    }
    Ok(())
}
/// Called only by the application after proving that credentials are absent.
/// Identity persistence belongs to the root; text/results remain volatile.
pub async fn execute_anonymous(
    invocation: &Invocation,
    client: &mut Client,
    anonymous_id: &str,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    send_with_writers_mode(
        invocation,
        client,
        Some(anonymous_id),
        cancel,
        &mut io::stdout(),
        &mut io::stderr(),
    )
    .await
}
pub(super) async fn send(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    send_with_writers(
        invocation,
        client,
        cancel,
        &mut io::stdout(),
        &mut io::stderr(),
    )
    .await
}
async fn send_with_writers(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    stdout: &mut impl Write,
    stderr: &mut impl Write,
) -> Result<CliOutput, CliError> {
    send_with_writers_mode(invocation, client, None, cancel, stdout, stderr).await
}
async fn send_with_writers_mode(
    invocation: &Invocation,
    client: &mut Client,
    anonymous_id: Option<&str>,
    cancel: CancellationToken,
    stdout: &mut impl Write,
    stderr: &mut impl Write,
) -> Result<CliOutput, CliError> {
    observe_with_writers_mode(invocation, client, anonymous_id, cancel, stdout, stderr)
        .await?
        .finish(invocation.boolean("json"), stdout)
}
pub(super) async fn observe_saved(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<ObservedSend, CliError> {
    observe_with_writers_mode(
        invocation,
        client,
        None,
        cancel,
        &mut io::stdout(),
        &mut io::stderr(),
    )
    .await
}
async fn observe_with_writers_mode(
    invocation: &Invocation,
    client: &mut Client,
    anonymous_id: Option<&str>,
    cancel: CancellationToken,
    stdout: &mut impl Write,
    stderr: &mut impl Write,
) -> Result<ObservedSend, CliError> {
    if anonymous_id.is_some() {
        if client.session().is_some() {
            return Err(Error::Authentication.into());
        }
        if !matches!(
            invocation.command_path().as_str(),
            "chats new" | "chats send" | "chats incognito"
        ) {
            return Err(CliError::Unsupported {
                command: invocation.command_path(),
                reason: "Anonymous inference supports new volatile text only.".into(),
            });
        }
    }
    let interactive = invocation.command_path() == "chats answer-interactive";
    let mut options = options(invocation, interactive)?;
    let ephemeral = anonymous_id.is_some() || options.incognito;
    if ephemeral {
        volatile_options(invocation, &options)?;
        // Volatile mode itself forbids durable jobs; this is not an opt-out
        // applied to ordinary saved sends.
        options.task_update_jobs = false;
    }
    let text = if interactive {
        // npm exits 1 for every invalid interactive answer (not the usage exit code).
        let answered = (|| -> Result<Zeroizing<String>, CliError> {
            if !invocation.positionals.is_empty()
                || invocation
                    .text("chat")
                    .is_none_or(|value| value.trim().is_empty())
            {
                return Err(CliError::Invalid(
                    "Interactive answers require --chat and no positional message.".into(),
                ));
            }
            let parse = |key: &str| -> Result<serde_json::Value, CliError> {
                let value = invocation
                    .text(key)
                    .ok_or_else(|| CliError::Invalid(format!("Missing --{key}.")))?;
                if value.len() > 1_000_000 {
                    return Err(CliError::Invalid(format!("--{key} exceeds 1 MB.")));
                }
                serde_json::from_str(value)
                    .map_err(|_| CliError::Invalid(format!("--{key} must be valid JSON.")))
            };
            questions::answer(&parse("question-json")?, &parse("answer-json")?)
        })();
        answered.map_err(|error| match error {
            CliError::Invalid(message) => CliError::Contract { code: "invalid_argument", message },
            other => other,
        })?
    } else {
        Zeroizing::new(invocation.positionals.join(" ").trim().to_owned())
    };
    if text.trim().is_empty() {
        return Err(CliError::Invalid("Provide a message.".into()));
    }
    // Display mentions (@Gemini-3.8-Flash, @Sophia, @Web-Search) become wire
    // syntax before encryption; an unknown mention aborts before any dispatch.
    let text = if interactive {
        text
    } else {
        let resolved = client.resolve_mentions(&text).await?;
        if let Some(message) = unresolved_mentions_message(&resolved.unresolved) {
            return Err(CliError::Contract {
                code: "unknown_mention",
                message,
            });
        }
        Zeroizing::new(resolved.processed_message)
    };
    let chat_id = if invocation.path.get(1).is_some_and(|s| s == "new") {
        None
    } else {
        invocation.text("chat")
    };
    // Answering implies the previous reply was read (feature.chat-unread@1):
    // clear the counter before dispatch so only the new reply counts.
    if anonymous_id.is_none()
        && !ephemeral
        && let Some(id) = chat_id.filter(|id| uuid::Uuid::parse_str(id).is_ok())
    {
        client.mark_chat_read(id).await?;
    }
    let (tx, mut updates) = mpsc::channel(64);
    let (consent, receiver) = mpsc::unbounded_channel();
    client.set_consent_receiver(receiver);
    let operation = async {
        match anonymous_id {
            Some(id) => {
                client
                    .send_anonymous(id, &text, options, tx, cancel.clone())
                    .await
            }
            None => {
                client
                    .send(chat_id, &text, options, tx, cancel.clone())
                    .await
            }
        }
    };
    tokio::pin!(operation);
    let mut presentation = Presentation {
        approve_subchats: invocation.boolean("auto-approve"),
        approve_memories: invocation.boolean("auto-approve-memories"),
        ephemeral,
        ..Default::default()
    };
    let mut updates_open = true;
    let json = invocation.boolean("json");
    loop {
        tokio::select! {
            result=&mut operation=>{
                // The send future owns all producers. Drain its queued delivery
                // receipts before classifying an error/cancellation.
                while let Ok(event)=updates.try_recv(){presentation.event(event,json,stdout,stderr,&consent);}
                return match result {
                    Ok(outcome)=>Ok(ObservedSend { outcome, presentation }),
                    Err(error)=>Err(presentation.failure(error)),
                };
            },
            event=updates.recv(),if updates_open=>match event {
                Some(event)=>{presentation.event(event,json,stdout,stderr,&consent);if presentation.io_failed{cancel.cancel();}},
                None=>updates_open=false,
            }
        }
    }
}
/// TypeScript CLI wording for unknown mentions (cli.ts sendMessageStreaming).
pub(crate) fn unresolved_mentions_message(
    unresolved: &[openmates_sdk::mentions::UnresolvedMention],
) -> Option<String> {
    if unresolved.is_empty() {
        return None;
    }
    let mut message = String::new();
    for (index, mention) in unresolved.iter().enumerate() {
        if index > 0 {
            message.push_str("\nError: ");
        }
        message.push_str(&format!("Unknown mention {}", terminal_text(&mention.original)));
        if !mention.suggestions.is_empty() {
            message.push_str(&format!(
                "\n  Did you mean: {}?",
                terminal_text(&mention.suggestions.join(", "))
            ));
        }
    }
    message.push_str("\n\nNo message was sent. Check the mention name or remove the @.");
    Some(message)
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{Value, json};
    #[test]
    fn unknown_mentions_are_reported_with_suggestions_and_known_ones_are_silent() {
        use openmates_sdk::mentions::UnresolvedMention;
        assert!(unresolved_mentions_message(&[]).is_none());
        let message = unresolved_mentions_message(&[
            UnresolvedMention { original: "@Sophie".into(), suggestions: vec!["@Sophia".into()] },
            UnresolvedMention { original: "@Nope".into(), suggestions: vec![] },
        ])
        .unwrap();
        assert!(message.starts_with("Unknown mention @Sophie\n  Did you mean: @Sophia?"));
        assert!(message.contains("\nError: Unknown mention @Nope\n\nNo message was sent."));
    }
    fn invocation(flags: &[(&str, Value)]) -> Invocation {
        Invocation {
            path: vec!["chats".into(), "send".into()],
            positionals: vec!["hello".into()],
            flags: flags
                .iter()
                .map(|(key, value)| (key.to_string(), value.clone()))
                .collect(),
        }
    }
    fn outcome(status: &str, assistant: &str) -> SendOutcome {
        serde_json::from_value(json!({"status":status,"chatId":"chat","messageId":"assistant","userMessageId":"human","assistant":assistant,"category":"science","modelName":"observed automatic model","mateName":"Scarlett","followUpSuggestions":["Next 界"],"suggestedFollowupMessage":null,"taskProposals":[{"title":"Review only"}],"taskUpdateProposals":[],"taskEvents":[{"event_id":"event","task_id":"task","event_type":"blocked"}],"pendingTaskUpdateJobs":[{"job_id":"pending","revision":2}],"subChatEvents":[{"type":"sub_chat_progress","payload":{"status":"running"}}],"appSettingsMemoryRequests":[{"requestId":"request","requestedKeys":["app-category"],"approvedKeys":[],"entryCount":0}],"tokenUsage":{"promptTokens":4,"completionTokens":2},"promptBudget":{"systemPromptTokens":1}})).unwrap()
    }
    // contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
    #[test]
    fn parsed_saved_new_and_send_accept_scope_without_losing_timeout_or_admitting_unported_options()
    {
        let team = "33333333-3333-4333-8333-333333333333";
        let message = "Synthetic question <<<TEST_MOCK:hidden_chats_3:slow>>>";
        for command in ["new", "send"] {
            for scope in [vec!["--personal"], vec!["--team", team]] {
                let mut args = vec!["openmates", "chats", command, message];
                args.extend(scope.iter().copied());
                let parse = |tail: &[&str]| {
                    let mut values = args
                        .iter()
                        .map(|value| (*value).to_owned())
                        .collect::<Vec<_>>();
                    values.extend(tail.iter().map(|value| (*value).to_owned()));
                    super::super::parse_from(values)
                        .unwrap_or_else(|error| panic!("{error}"))
                        .invocation
                        .expect("saved send invocation")
                };
                let invocation = parse(&["--response-timeout-seconds", "60"]);
                let selected = options(&invocation, false)
                    .unwrap_or_else(|error| panic!("saved scope is supported: {error}"));
                assert_eq!(invocation.positionals, [message]);
                assert_eq!(invocation.boolean("personal"), scope[0] == "--personal");
                assert_eq!(
                    invocation.text("team"),
                    if scope[0] == "--team" {
                        Some(team)
                    } else {
                        None
                    }
                );
                assert_eq!(selected.response_timeout_ms, Some(60_000));
                assert!(selected.task_update_jobs && selected.pii_detection && !selected.incognito);
                for timeout in ["0", "-1", "86401", "one"] {
                    assert!(matches!(
                        options(&parse(&["--response-timeout-seconds", timeout]), false),
                        Err(CliError::Invalid(_))
                    ));
                }
                for unported in [
                    vec!["--project", "synthetic"],
                    vec!["--accept-task-proposals"],
                ] {
                    assert!(matches!(
                        options(&parse(&unported), false),
                        Err(CliError::Unsupported { .. })
                    ));
                }
                // Anonymous new/send share options(), but cannot silently
                // ignore a selected scope once volatile admission is chosen.
                assert!(matches!(
                    volatile_options(&invocation, &selected),
                    Err(CliError::Unsupported { .. })
                ));
            }
        }
    }
    #[tokio::test]
    async fn parsed_saved_send_conflicting_scopes_still_fail_before_authentication_or_transport() {
        for command in ["new", "send"] {
            let invocation = super::super::parse_from([
                "openmates",
                "chats",
                command,
                "synthetic question",
                "--personal",
                "--team",
                "33333333-3333-4333-8333-333333333333",
            ])
            .unwrap_or_else(|error| panic!("{error}"))
            .invocation
            .expect("saved send invocation");
            let mut client = Client::new("http://127.0.0.1:1", None).expect("inert Client");
            assert!(matches!(
                super::super::execute(&invocation, &mut client, CancellationToken::new()).await,
                Err(CliError::Invalid(_))
            ));
            assert!(client.session().is_none());
        }
    }
    #[test]
    fn parsed_incognito_scope_flags_remain_refused_before_dispatch() {
        for (command, tail) in [("incognito", vec![]), ("send", vec!["--incognito"])] {
            for scope in [
                vec!["--personal"],
                vec!["--team", "33333333-3333-4333-8333-333333333333"],
            ] {
                let mut args = vec!["openmates", "chats", command, "synthetic question"];
                args.extend(tail.iter().copied());
                args.extend(scope.iter().copied());
                let invocation = super::super::parse_from(args)
                    .unwrap_or_else(|error| panic!("{error}"))
                    .invocation
                    .expect("volatile invocation");
                assert!(matches!(
                    options(&invocation, false),
                    Err(CliError::Unsupported { .. })
                ));
            }
        }
    }
    #[tokio::test]
    async fn native_default_and_explicit_task_job_flags_reach_the_websocket_capability() {
        use futures_util::StreamExt;
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        use tokio_tungstenite::tungstenite::handshake::server::{
            Callback, ErrorResponse, Request, Response,
        };
        struct CapabilityCheck(bool);
        impl Callback for CapabilityCheck {
            fn on_request(
                self,
                request: &Request,
                response: Response,
            ) -> Result<Response, ErrorResponse> {
                let url = url::Url::parse(&format!("http://synthetic{}", request.uri())).unwrap();
                assert_eq!(url.path(), "/v1/ws");
                let capabilities = url
                    .query_pairs()
                    .find(|(key, _)| key == "client_capabilities")
                    .unwrap()
                    .1
                    .into_owned();
                assert_eq!(
                    capabilities
                        .split(',')
                        .any(|value| value == "task_update_jobs"),
                    self.0
                );
                Ok(response)
            }
        }
        for command in ["new", "send"] {
            for flag in [
                None,
                Some("--no-task-update-jobs"),
                Some("--no-task-update-jobs=false"),
            ] {
                let enabled = flag != Some("--no-task-update-jobs");
                let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
                let api = format!("http://{}", listener.local_addr().unwrap());
                let cancel = CancellationToken::new();
                let stop = cancel.clone();
                let server = tokio::spawn(async move {
                    let (mut socket, _) = listener.accept().await.unwrap();
                    let mut bytes = vec![];
                    let (end, length) = loop {
                        let mut part = [0; 4096];
                        let n = socket.read(&mut part).await.unwrap();
                        assert!(n > 0);
                        bytes.extend_from_slice(&part[..n]);
                        if let Some(end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                            let header = std::str::from_utf8(&bytes[..end]).unwrap();
                            assert!(header.starts_with("POST /v1/auth/session HTTP/1.1"));
                            let length = header
                                .lines()
                                .filter_map(|line| line.split_once(':'))
                                .find(|(key, _)| key.eq_ignore_ascii_case("content-length"))
                                .map(|(_, value)| value.trim().parse::<usize>().unwrap())
                                .unwrap_or(0);
                            break (end + 4, length);
                        }
                    };
                    while bytes.len() < end + length {
                        let mut part = [0; 4096];
                        let n = socket.read(&mut part).await.unwrap();
                        assert!(n > 0);
                        bytes.extend_from_slice(&part[..n]);
                    }
                    let body=json!({"success":true,"ws_token":"synthetic-token","user":{"user_id":"synthetic-user"}}).to_string();
                    socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
                    drop(socket);
                    let (socket, _) = listener.accept().await.unwrap();
                    let mut ws =
                        tokio_tungstenite::accept_hdr_async(socket, CapabilityCheck(enabled))
                            .await
                            .unwrap();
                    let lifecycle = ws.next().await.unwrap().unwrap();
                    let lifecycle: Value =
                        serde_json::from_str(lifecycle.to_text().unwrap()).unwrap();
                    assert_eq!(lifecycle["type"], "native_client_lifecycle");
                    let first = ws.next().await.unwrap().unwrap();
                    let first: Value = serde_json::from_str(first.to_text().unwrap()).unwrap();
                    assert_eq!(first["type"], "set_active_chat");
                    let snapshot = ws.next().await.unwrap().unwrap();
                    let snapshot: Value =
                        serde_json::from_str(snapshot.to_text().unwrap()).unwrap();
                    assert_eq!(snapshot["type"], "personal_send_context_snapshot");
                    // End before a privacy receipt or turn admission; this test
                    // proves CLI→SDK options, never submits an inference request.
                    stop.cancel();
                    let _ = ws.next().await;
                });
                let session = openmates_sdk::Session {
                    api_url: api.clone(),
                    session_id: "synthetic".into(),
                    cookies: Default::default(),
                    ws_token: None,
                    master_key: Zeroizing::new([7; 32]),
                    hashed_email: "synthetic-owner".into(),
                    user_email_salt: String::new(),
                    email_encryption_key: None,
                    created_at: 1,
                    paired_session_expires_at: None,
                    active_team_id: None,
                };
                let mut client = Client::new(&api, Some(session)).unwrap();
                let mut args = vec!["openmates", "chats", command, "synthetic message"];
                if let Some(flag) = flag {
                    args.push(flag);
                }
                let parsed = super::super::parse_from(args).unwrap();
                let mut stdout = Writer::default();
                let mut stderr = Writer::default();
                let result = tokio::time::timeout(
                    std::time::Duration::from_secs(5),
                    send_with_writers(
                        parsed.invocation.as_ref().unwrap(),
                        &mut client,
                        cancel,
                        &mut stdout,
                        &mut stderr,
                    ),
                )
                .await
                .unwrap();
                assert!(matches!(result, Err(CliError::Client(Error::Cancelled))));
                assert!(stdout.bytes.is_empty());
                tokio::time::timeout(std::time::Duration::from_secs(5), server)
                    .await
                    .unwrap()
                    .unwrap();
            }
        }
    }
    #[test]
    fn explicit_no_task_jobs_maps_only_supported_options_without_changing_default_mode() {
        assert!(
            options(&invocation(&[]), false)
                .unwrap_or_else(|e| panic!("{e}"))
                .task_update_jobs
        );
        let i = invocation(&[
            ("no-task-update-jobs", json!(true)),
            ("no-pii-detection", json!(true)),
            ("slug", json!("native-chat")),
            ("response-timeout-seconds", json!(12)),
            ("auto-approve", json!(true)),
        ]);
        // Programmatic Invocation requires textual values just like the parser.
        assert!(options(&i, false).is_err());
        let i = invocation(&[
            ("no-task-update-jobs", json!(true)),
            ("no-pii-detection", json!(true)),
            ("slug", json!("native-chat")),
            ("response-timeout-seconds", json!("12")),
            ("auto-approve", json!(true)),
        ]);
        let opts = options(&i, false).unwrap_or_else(|e| panic!("{e}"));
        assert!(!opts.task_update_jobs && !opts.pii_detection && !opts.incognito);
        assert_eq!(opts.response_timeout_ms, Some(12000));
        assert_eq!(opts.slug.as_deref(), Some("native-chat"));
        assert!(
            opts.sub_chat_consent == SendConsentPolicy::ApproveRequested
                && opts.memory_consent == SendConsentPolicy::Reject
        );
        assert!(
            options(&invocation(&[("incognito", json!(true))]), false)
                .unwrap_or_else(|e| panic!("{e}"))
                .incognito
        );
        for flag in ["project", "accept-task-proposals"] {
            assert!(matches!(
                options(&invocation(&[(flag, json!(true))]), false),
                Err(CliError::Unsupported { .. })
            ));
        }
        assert!(
            options(&invocation(&[("slug", json!("chat"))]), false)
                .unwrap_or_else(|e| panic!("{e}"))
                .task_update_jobs
        );
        assert!(
            options(&invocation(&[("no-task-update-jobs", json!(false))]), false)
                .unwrap_or_else(|e| panic!("{e}"))
                .task_update_jobs
        );
        let mut new = invocation(&[("chat", json!("existing"))]);
        new.path[1] = "new".into();
        assert!(matches!(options(&new, false), Err(CliError::Invalid(_))));
        for timeout in ["0", "-1", "86401", "9999999999999999999999", "one"] {
            assert!(
                options(
                    &invocation(&[
                        ("no-task-update-jobs", json!(true)),
                        ("response-timeout-seconds", json!(timeout))
                    ]),
                    false
                )
                .is_err()
            );
        }
    }
    #[test]
    fn observed_json_keeps_canonical_metadata_and_json_stream_has_no_private_chat_snapshot() {
        let result = outcome("completed", "final \u{1b}[31m界");
        let mut state = Presentation::default();
        let mut writer = Writer::default();
        let output = state
            .finish_outcome(&result, true, &mut writer)
            .unwrap_or_else(|e| panic!("{e}"));
        let value: Value = serde_json::from_str(&output.stdout).unwrap();
        assert_eq!(value["chatId"], "chat");
        assert_eq!(value["messageId"], "assistant");
        assert_eq!(value["userMessageId"], "human");
        assert_eq!(value["assistant"], result.assistant);
        assert_eq!(value["modelName"], "observed automatic model");
        assert_eq!(value["pendingTaskUpdateJobs"][0]["job_id"], "pending");
        assert_eq!(value["tokenUsage"]["promptTokens"], 4);
        assert_eq!(
            value["appSettingsMemoryRequests"][0]["approvedKeys"],
            json!([])
        );
        assert_eq!(value["acceptedTaskProposals"], json!([]));
        assert!(
            value
                .as_object()
                .unwrap()
                .contains_key("suggestedFollowupMessage")
        );
        assert!(value.get("chat").is_none() && value.get("messages").is_none());
        assert!(writer.bytes.is_empty());
    }
    #[test]
    fn observed_waiting_question_and_queued_result_use_distinct_legacy_shapes() {
        let mut state = Presentation::default();
        let mut writer = Writer::default();
        let question = "```interactive_question\n{\"id\":\"q\",\"type\":\"rating\",\"question\":\"Rate\"}\n```";
        let output = state
            .finish_outcome(&outcome("waiting_for_user", question), true, &mut writer)
            .unwrap_or_else(|e| panic!("{e}"));
        let value: Value = serde_json::from_str(&output.stdout).unwrap();
        assert_eq!(
            value,
            json!({"status":"waiting_for_user","chat_id":"chat","message_id":"assistant","parent_id":"chat","question":{"id":"q","type":"rating","question":"Rate"}})
        );
        let mut queued = outcome("queued", "");
        queued.message_id = None;
        queued.queue_mode = Some(openmates_sdk::client::SendQueueMode::Steer);
        queued.queue_revision = Some(7);
        let output = state
            .finish_outcome(&queued, true, &mut writer)
            .unwrap_or_else(|e| panic!("{e}"));
        let value: Value = serde_json::from_str(&output.stdout).unwrap();
        assert_eq!(value["status"], "queued");
        assert_eq!(value["queueMode"], "steer");
        assert_eq!(value["queueRevision"], 7);
        assert!(value["messageId"].is_null());
        let output = state
            .finish_outcome(&queued, false, &mut writer)
            .unwrap_or_else(|e| panic!("{e}"));
        assert!(output.stderr.contains("queued"));
        assert!(writer.bytes.is_empty());
    }
    #[derive(Default)]
    struct Writer {
        bytes: Vec<u8>,
        flushes: usize,
    }
    impl Write for Writer {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            self.bytes.extend(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> io::Result<()> {
            self.flushes += 1;
            Ok(())
        }
    }
    #[test]
    fn approval_flags_are_independent_and_return_only_current_requested_ids() {
        for (subchats, memories) in [(false, false), (true, false), (false, true), (true, true)] {
            let mut state = Presentation {
                approve_subchats: subchats,
                approve_memories: memories,
                ..Default::default()
            };
            let (consent, mut receiver) = mpsc::unbounded_channel();
            let mut out = Writer::default();
            let mut err = Writer::default();
            for subchat in [false, true] {
                let item = crate::model::Item {
                    id: if subchat {
                        "start_sub_chats"
                    } else {
                        "health-medications"
                    }
                    .into(),
                    fields: if subchat {
                        serde_json::json!({"consent_kind":"sub_chats","entries":[{"prompt":"private proposal"}]})
                    } else {
                        serde_json::json!({"entries":[{"private":"memory"}]})
                    },
                    ..Default::default()
                };
                let expected = if (subchat && subchats) || (!subchat && memories) {
                    vec![item.id.clone()]
                } else {
                    vec![]
                };
                state.event(
                    StreamUpdate::Consent {
                        request_id: "fresh-request".into(),
                        items: vec![item],
                    },
                    true,
                    &mut out,
                    &mut err,
                    &consent,
                );
                let (id, approved) = receiver.try_recv().unwrap();
                assert_eq!(id, "fresh-request");
                assert_eq!(approved, expected);
            }
            assert!(out.bytes.is_empty());
            assert!(!String::from_utf8_lossy(&err.bytes).contains("private proposal"));
            assert!(!String::from_utf8_lossy(&err.bytes).contains("health-medications"));
        }
    }
    #[tokio::test]
    async fn invalid_interactive_answer_is_rejected_before_authentication_or_transport() {
        let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
        let invocation = Invocation {
            path: vec!["chats".into(),"answer-interactive".into()],
            positionals: vec![],
            flags: [
                ("chat".into(),serde_json::json!("chat")),
                ("question-json".into(),serde_json::json!(r#"{"id":"q","type":"choice","question":"Pick","options":[{"id":"a","text":"A"}]}"#)),
                ("answer-json".into(),serde_json::json!(r#"{"selection":["unrequested"]}"#)),
            ].into_iter().collect(),
        };
        let mut out = Writer::default();
        let mut err = Writer::default();
        let result = send_with_writers(
            &invocation,
            &mut client,
            CancellationToken::new(),
            &mut out,
            &mut err,
        )
        .await;
        assert!(matches!(
            result,
            Err(CliError::Contract { code: "invalid_argument", .. })
        ));
        assert!(out.bytes.is_empty() && err.bytes.is_empty());
    }
    #[test]
    fn cumulative_content_flushes_incrementally_without_duplicates_or_terminal_escapes() {
        let mut state = Presentation::default();
        let mut writer = Writer::default();
        state.content("Hello 界", &mut writer);
        assert_eq!(String::from_utf8_lossy(&writer.bytes), "Hello 界");
        state.content("Hello 界\u{1b}[31m!", &mut writer);
        assert_eq!(
            String::from_utf8_lossy(&writer.bytes),
            "Hello 界\\u001b[31m!"
        );
        assert_eq!(writer.flushes, 2);
    }
    #[test]
    fn json_stream_does_not_write_content_and_final_output_is_one_object() {
        let mut state = Presentation::default();
        let mut out = Writer::default();
        let mut err = Writer::default();
        let (consent, _) = mpsc::unbounded_channel();
        state.event(
            StreamUpdate::Content {
                content: "private response".into(),
                thinking: "hidden".into(),
                mate: String::new(),
            },
            true,
            &mut out,
            &mut err,
            &consent,
        );
        assert!(out.bytes.is_empty());
        let result = state
            .finish_outcome(&outcome("completed", "private response"), true, &mut out)
            .ok()
            .unwrap();
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(&result.stdout).unwrap()["chatId"],
            "chat"
        );
    }
    #[test]
    fn queued_submission_changes_cancellation_disposition_before_failure() {
        let mut state = Presentation::default();
        let mut out = Writer::default();
        let mut err = Writer::default();
        let (consent, _) = mpsc::unbounded_channel();
        state.event(
            StreamUpdate::Submitted {
                chat_id: "chat".into(),
                message_id: "human".into(),
            },
            true,
            &mut out,
            &mut err,
            &consent,
        );
        let error = state.failure(Error::Cancelled);
        assert!(matches!(
            error,
            CliError::PendingTurn {
                admitted: false,
                ..
            }
        ));
        assert_eq!(error.exit_code(), 130);
        assert!(error.to_string().contains("do not resend"));
        assert!(matches!(
            Presentation::default().failure(Error::Offline),
            CliError::Client(Error::Offline)
        ));
    }
    #[test]
    fn rejected_preflight_is_a_specific_error_not_turn_recovery() {
        let rejected = Error::Unavailable { code: "chat_turn_rejected", reason: "SERVER_REJECTED_TURN_BEFORE_ADMISSION" };
        let submitted = Presentation { pending: Some(("chat".into(), "human".into(), false)), ..Default::default() };
        let error = submitted.failure(rejected);
        assert_eq!(error.code(), "chat_turn_rejected");
        assert_eq!(error.exit_code(), 1);
        assert!(error.to_string().contains("nothing was admitted"));
        // An acknowledged turn keeps the recovery guidance.
        let admitted = Presentation { pending: Some(("chat".into(), "human".into(), true)), ..Default::default() };
        assert_eq!(admitted.failure(rejected).code(), "turn_recovery_required");
    }
    #[test]
    fn normal_team_submission_never_renders_previous_assistant_response() {
        let mut state = Presentation::default();
        let mut out = Writer::default();
        let mut result = outcome("completed", "");
        result.message_id = None;
        result.chat.messages.push(crate::model::Message {
            role: "assistant".into(),
            content: "Previous response".into(),
            ..Default::default()
        });
        state.finish_outcome(&result, false, &mut out).ok().unwrap();
        assert!(out.bytes.is_empty());
    }
}
