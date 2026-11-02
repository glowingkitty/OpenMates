//! Chat and embed Project link adapter (`chats|embeds add-to-project` and
//! `remove-from-project`). Chat selectors are full chat UUIDs; embed selectors
//! use the saved-embed resolver. Project selectors use the existing SDK
//! resolver, with its documented limits. Links never copy or delete targets.
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::{CliError, CliOutput, Invocation};
use crate::{client::Client, error::Error};
use openmates_sdk::work::{ProjectFilters, ProjectItemType, ProjectLink};
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

const REMOTE_COPY: &[&str] = &["repo-copy", "remote-cache-copy", "remote-copy"];

pub(super) fn supported(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        "chats remove-from-project"
            | "chats add-to-project"
            | "embeds add-to-project"
            | "embeds remove-from-project"
    )
}
fn unsupported(i: &Invocation, reason: &str) -> CliError {
    CliError::Unsupported {
        command: i.command_path(),
        reason: reason.into(),
    }
}
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Kind {
    Chat,
    Embed,
}
impl Kind {
    fn name(self) -> &'static str {
        match self {
            Kind::Chat => "chat",
            Kind::Embed => "embed",
        }
    }
    fn item_type(self) -> ProjectItemType {
        match self {
            Kind::Chat => ProjectItemType::Chat,
            Kind::Embed => ProjectItemType::Embed,
        }
    }
}
struct Request<'a> {
    kind: Kind,
    add: bool,
    target: String,
    project: &'a str,
}
fn arguments(i: &Invocation) -> Result<Request<'_>, CliError> {
    if !supported(i) {
        return Err(unsupported(
            i,
            "This adapter only links or unlinks a chat or embed in a Project.",
        ));
    }
    let kind = if i.path[0] == "chats" {
        Kind::Chat
    } else {
        Kind::Embed
    };
    let add = i.path[1] == "add-to-project";
    let mut allowed = vec!["personal", "team"];
    if add {
        allowed.push("folder");
        if kind == Kind::Chat {
            allowed.push("openmates-only");
            allowed.extend_from_slice(REMOTE_COPY);
        }
    }
    super::handlers::flags(i, &allowed)?;
    let command = format!(
        "{} {}",
        if kind == Kind::Chat { "Chat" } else { "Embed" },
        i.path[1]
    );
    if i.has("api-key") {
        return Err(unsupported(
            i,
            &format!(
                "{command} requires an authenticated Cookie session; API-key credentials are not supported."
            ),
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
            &format!(
                "Native {} {} currently supports Personal Cookie sessions. Team and Direct links are not ported.",
                i.path[0], i.path[1]
            ),
        ));
    }
    let remote = REMOTE_COPY.iter().filter(|flag| i.boolean(flag)).count();
    if i.boolean("openmates-only") && remote > 0 {
        return Err(CliError::Invalid(
            "Choose either --openmates-only or a remote-copy mode, not both.".into(),
        ));
    }
    if i.boolean("repo-copy") && i.boolean("remote-cache-copy") {
        return Err(CliError::Invalid(
            "Choose only one remote-copy mode: --repo-copy or --remote-cache-copy.".into(),
        ));
    }
    if remote > 0 {
        return Err(unsupported(
            i,
            "Remote-copy proposals are not ported; use the default encrypted OpenMates Project link.",
        ));
    }
    if i.has("folder")
        && i.text("folder")
            .is_none_or(|folder| folder.trim().is_empty())
    {
        return Err(CliError::Invalid("--folder requires a folder ID.".into()));
    }
    if i.positionals.len() != 2 || i.positionals.iter().any(|v| v.trim().is_empty()) {
        return Err(CliError::Invalid(format!(
            "Supply exactly <{}> and <project-selector>.",
            if kind == Kind::Chat {
                "full-chat-uuid"
            } else {
                "embed-id"
            }
        )));
    }
    let target = match kind {
        Kind::Chat => uuid::Uuid::parse_str(&i.positionals[0]).ok().filter(|id| id.to_string() == i.positionals[0].to_ascii_lowercase()).ok_or_else(|| unsupported(i, "Use the full hyphenated chat UUID. Short IDs, slugs, titles and last are not ported for this command."))?.to_string(),
        Kind::Embed => i.positionals[0].clone(),
    };
    Ok(Request {
        kind,
        add,
        target,
        project: &i.positionals[1],
    })
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
    /// Canonical chat ID and its decrypted title (the link display name).
    async fn chat(&mut self, id: &str) -> Result<(String, String), Error>;
    /// Canonical embed ID and its display name (preview, type or ID).
    async fn embed(&mut self, selector: &str) -> Result<(String, String), Error>;
    async fn unlink(
        &mut self,
        project: &str,
        kind: ProjectItemType,
        target: &str,
        confirmed: bool,
    ) -> Result<Value, Error>;
    async fn link(&mut self, project: &str, link: ProjectLink) -> Result<Value, Error>;
}
struct Cookie<'a>(&'a mut Client);
impl Cookie<'_> {
    fn projects(&mut self) -> openmates_sdk::work::Projects<'_> {
        self.0.projects().with_filters(ProjectFilters {
            personal: true,
            ..Default::default()
        })
    }
}
impl Backend for Cookie<'_> {
    fn context(&self) -> Context {
        match self.0.session() {
            None => Context::Missing,
            Some(session) if session.active_team_id.is_some() => Context::Team,
            Some(_) => Context::Personal,
        }
    }
    async fn project(&mut self, selector: &str) -> Result<Value, Error> {
        self.projects().show(selector).await
    }
    async fn chat(&mut self, id: &str) -> Result<(String, String), Error> {
        let chat = self.0.open_chat(id).await?;
        Ok((chat.id, chat.title))
    }
    async fn embed(&mut self, selector: &str) -> Result<(String, String), Error> {
        self.0.ensure_saved_embed_selector().await?;
        let read = self.0.saved_embed_selector(selector).await?;
        let value: Value = serde_json::from_str(&read.json(self.0)?)?;
        let id = value["embed_id"]
            .as_str()
            .filter(|id| !id.is_empty())
            .ok_or(Error::Protocol)?
            .to_owned();
        let name = [&value["text_preview"], &value["type"]]
            .into_iter()
            .filter_map(Value::as_str)
            .find(|text| !text.is_empty())
            .unwrap_or(&id)
            .to_owned();
        Ok((id, name))
    }
    async fn unlink(
        &mut self,
        project: &str,
        kind: ProjectItemType,
        target: &str,
        confirmed: bool,
    ) -> Result<Value, Error> {
        self.projects()
            .unlink_item(project, kind, target, confirmed)
            .await
    }
    async fn link(&mut self, project: &str, link: ProjectLink) -> Result<Value, Error> {
        self.projects().link_item(project, link).await
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
    kind: Kind,
    project: &str,
    target: &str,
    receipt: Value,
) -> Result<CliOutput, CliError> {
    let deleted = receipt["deleted"].as_bool().ok_or(Error::Protocol)?;
    let count = receipt["deleted_count"].as_u64().ok_or(Error::Protocol)?;
    if receipt["project_id"].as_str() != Some(project)
        || receipt["target_id"].as_str() != Some(target)
        || deleted != (count > 0)
    {
        return Err(Error::Protocol.into());
    }
    let name = kind.name();
    if i.boolean("json") {
        CliOutput::json(
            &json!({"objectType":name,"objectId":target,"projectId":project,"deleted":deleted,"deletedCount":count}),
        )
    } else {
        Ok(CliOutput::text(if deleted {
            format!("{name} removed from Project: {project}")
        } else {
            format!("{name} was not linked to Project: {project}")
        }))
    }
}
/// Legacy printAddToProjectResult for the encrypted-link-only storage mode.
fn added(
    i: &Invocation,
    kind: Kind,
    project: &str,
    target: &str,
    receipt: Value,
) -> Result<CliOutput, CliError> {
    if receipt["project_id"].as_str() != Some(project) || !receipt["item"].is_object() {
        return Err(Error::Protocol.into());
    }
    let name = kind.name();
    if i.boolean("json") {
        CliOutput::json(
            &json!({"objectType":name,"objectId":target,"projectId":project,"item":receipt["item"],"targetMode":"save_only_in_openmates","remoteCopyProposal":null,"remote_copy_proposal":null}),
        )
    } else {
        Ok(CliOutput::text(format!(
            "{name} added to Project: {project}\nStorage: encrypted OpenMates Project link only"
        )))
    }
}
async fn execute_backend(
    i: &Invocation,
    backend: &mut impl Backend,
    cancel: &CancellationToken,
) -> Result<CliOutput, CliError> {
    let request = arguments(i)?;
    match backend.context() {
        Context::Missing => return Err(Error::Authentication.into()),
        Context::Team => {
            return Err(unsupported(
                i,
                &format!(
                    "Native {} {} currently supports Personal Cookie sessions. Switch to Personal first.",
                    i.path[0], i.path[1]
                ),
            ));
        }
        Context::Personal => {}
    }
    active(backend, cancel)?;
    // Legacy order: authenticate/resolve the Project before reading the target.
    let project = backend.project(request.project).await?;
    active(backend, cancel)?;
    let project = project["project_id"]
        .as_str()
        .filter(|id| uuid::Uuid::parse_str(id).is_ok())
        .ok_or(Error::Protocol)?
        .to_owned();
    let (target, display) = match request.kind {
        Kind::Chat => {
            let (opened, title) = backend.chat(&request.target).await?;
            if opened != request.target {
                return Err(Error::Forbidden.into());
            }
            (opened, title)
        }
        Kind::Embed => backend.embed(&request.target).await?,
    };
    active(backend, cancel)?;
    if request.add {
        let mut metadata =
            json!({"storage":"save_only_in_openmates","source":"cli_add_to_project"});
        if request.kind == Kind::Chat {
            metadata["remote_copy_proposal"] = Value::Null;
        }
        let receipt = backend
            .link(
                &project,
                ProjectLink {
                    item_type: request.kind.item_type(),
                    target_id: target.clone(),
                    display_name: if display.is_empty() {
                        target.clone()
                    } else {
                        display
                    },
                    folder_id: i.text("folder").map(str::to_owned),
                    metadata,
                },
            )
            .await?;
        return added(i, request.kind, &project, &target, receipt);
    }
    // The explicit unlink command is the user's confirmation; no new flag.
    // SDK permissions and the existing endpoint authorize the matching links.
    let receipt = backend
        .unlink(&project, request.kind.item_type(), &target, true)
        .await?;
    // Preserve a known authoritative acknowledgement if cancellation arrives
    // after the write. Never turn it into an implicit retry or resource delete.
    acknowledgement(i, request.kind, &project, &target, receipt)
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
    const EMBED: &str = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
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
        links: Vec<Value>,
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
                links: vec![],
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
        async fn chat(&mut self, id: &str) -> Result<(String, String), Error> {
            assert_eq!(id, CHAT);
            self.record("chat")?;
            Ok((CHAT.into(), "Private chat title".into()))
        }
        async fn embed(&mut self, selector: &str) -> Result<(String, String), Error> {
            assert_eq!(selector, "embed-prefix");
            self.record("embed")?;
            Ok((EMBED.into(), "Private preview".into()))
        }
        async fn link(&mut self, project: &str, link: ProjectLink) -> Result<Value, Error> {
            assert_eq!(project, PROJECT);
            self.record("link")?;
            self.links.push(json!({"type":link.item_type,"target":link.target_id,"name":link.display_name,"folder":link.folder_id,"metadata":link.metadata}));
            Ok(json!({"project_id":PROJECT,"item":{"project_item_id":"server-link"}}))
        }
        async fn unlink(
            &mut self,
            project: &str,
            kind: ProjectItemType,
            chat: &str,
            confirmed: bool,
        ) -> Result<Value, Error> {
            assert_eq!(project, PROJECT);
            assert!(
                matches!(kind, ProjectItemType::Chat) && chat == CHAT
                    || matches!(kind, ProjectItemType::Embed) && chat == EMBED
            );
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
    fn add(path: [&str; 2], target: &str, flags: &[(&str, Value)]) -> Invocation {
        Invocation {
            path: path.iter().map(|v| (*v).into()).collect(),
            positionals: vec![target.into(), "engineering".into()],
            flags: flags
                .iter()
                .map(|(k, v)| ((*k).into(), v.clone()))
                .collect(),
        }
    }
    #[tokio::test]
    async fn chat_and_embed_links_encrypt_display_names_and_match_legacy_output() {
        let cases = [
            (
                ["chats", "add-to-project"],
                CHAT,
                "chat",
                "Private chat title",
                json!({"storage":"save_only_in_openmates","source":"cli_add_to_project","remote_copy_proposal":null}),
            ),
            (
                ["embeds", "add-to-project"],
                "embed-prefix",
                "embed",
                "Private preview",
                json!({"storage":"save_only_in_openmates","source":"cli_add_to_project"}),
            ),
        ];
        for (path, target, kind, name, metadata) in cases {
            let id = if kind == "chat" { CHAT } else { EMBED };
            let mut backend = Fake::new(true, 1);
            let i = add(
                path,
                target,
                &[("json", json!(true)), ("folder", json!("folder-1"))],
            );
            let output = execute_backend(&i, &mut backend, &CancellationToken::new())
                .await
                .ok()
                .unwrap();
            assert_eq!(backend.calls, ["project", kind, "link"]);
            assert_eq!(
                backend.links,
                [
                    json!({"type":kind,"target":id,"name":name,"folder":"folder-1","metadata":metadata})
                ]
            );
            assert_eq!(
                serde_json::from_str::<Value>(&output.stdout).unwrap(),
                json!({"objectType":kind,"objectId":id,"projectId":PROJECT,"item":{"project_item_id":"server-link"},"targetMode":"save_only_in_openmates","remoteCopyProposal":null,"remote_copy_proposal":null})
            );
            let mut backend = Fake::new(true, 1);
            let output = execute_backend(
                &add(path, target, &[]),
                &mut backend,
                &CancellationToken::new(),
            )
            .await
            .ok()
            .unwrap();
            assert_eq!(
                output.stdout,
                format!(
                    "{kind} added to Project: {PROJECT}\nStorage: encrypted OpenMates Project link only\n"
                )
            );
            assert!(!output.stdout.contains("Private"));
        }
        let mut backend = Fake::new(true, 1);
        backend.receipt["target_id"] = json!(EMBED);
        let output = execute_backend(
            &add(
                ["embeds", "remove-from-project"],
                "embed-prefix",
                &[("json", json!(true))],
            ),
            &mut backend,
            &CancellationToken::new(),
        )
        .await
        .ok()
        .unwrap();
        assert_eq!(backend.calls, ["project", "embed", "unlink"]);
        assert_eq!(
            serde_json::from_str::<Value>(&output.stdout).unwrap(),
            json!({"objectType":"embed","objectId":EMBED,"projectId":PROJECT,"deleted":true,"deletedCount":1})
        );
    }
    #[tokio::test]
    async fn remote_copy_modes_api_keys_and_bad_links_fail_without_mutation() {
        let path = ["chats", "add-to-project"];
        for (flags, unsupported_mode) in [
            (
                vec![("openmates-only", json!(true)), ("repo-copy", json!(true))],
                false,
            ),
            (
                vec![
                    ("repo-copy", json!(true)),
                    ("remote-cache-copy", json!(true)),
                ],
                false,
            ),
            (vec![("folder", json!(" "))], false),
            (vec![("remote-copy", json!(true))], true),
            (vec![("api-key", json!("synthetic-secret"))], true),
        ] {
            let mut backend = Fake::new(true, 1);
            let result = execute_backend(
                &add(path, CHAT, &flags),
                &mut backend,
                &CancellationToken::new(),
            )
            .await;
            if unsupported_mode {
                assert!(matches!(result, Err(CliError::Unsupported { .. })));
            } else {
                assert!(matches!(result, Err(CliError::Invalid(_))));
            }
            assert!(backend.calls.is_empty());
        }
        // Embed links accept no chat storage-mode flags.
        let mut backend = Fake::new(true, 1);
        assert!(
            execute_backend(
                &add(
                    ["embeds", "add-to-project"],
                    "embed-prefix",
                    &[("openmates-only", json!(true))]
                ),
                &mut backend,
                &CancellationToken::new()
            )
            .await
            .is_err()
        );
        assert!(backend.calls.is_empty());
        let mut backend = Fake::new(true, 1);
        backend.failure = Some("link");
        assert!(
            execute_backend(
                &add(path, CHAT, &[]),
                &mut backend,
                &CancellationToken::new()
            )
            .await
            .is_err()
        );
        assert_eq!(backend.calls, ["project", "chat", "link"]);
    }
    #[test]
    fn real_parser_routes_legacy_project_link_syntax() {
        for (arguments, path, positionals) in [
            (
                vec!["openmates", "chats", CHAT, "add-to-project", "engineering"],
                ["chats", "add-to-project"],
                [CHAT, "engineering"],
            ),
            (
                vec![
                    "openmates",
                    "embeds",
                    "add-to-project",
                    EMBED,
                    "engineering",
                ],
                ["embeds", "add-to-project"],
                [EMBED, "engineering"],
            ),
            (
                vec![
                    "openmates",
                    "embeds",
                    "remove-from-project",
                    EMBED,
                    "engineering",
                ],
                ["embeds", "remove-from-project"],
                [EMBED, "engineering"],
            ),
        ] {
            let parsed = super::super::parse_from(arguments)
                .unwrap_or_else(|error| panic!("{error}"))
                .invocation
                .expect("project link invocation");
            assert_eq!(parsed.path, path);
            assert_eq!(parsed.positionals, positionals);
            assert!(supported(&parsed));
            assert!(super::super::handlers::requirements(&parsed).supported);
        }
    }
}
