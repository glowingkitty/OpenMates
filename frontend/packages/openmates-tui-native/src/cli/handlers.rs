use super::*;
use crate::{
    client::Client,
    model::{Chat, Item, Mutation, Workspace},
};
use serde_json::json;
use tokio_util::sync::CancellationToken;
#[cfg(test)]
#[path = "chat_search_tests.rs"]
mod chat_search_tests;
#[cfg(test)]
#[path = "draft_clear_tests.rs"]
mod draft_clear_tests;
#[cfg(test)]
#[path = "saved_show_tests.rs"]
mod saved_show_tests;
const GLOBALS: &[&str] = &[
    "json",
    "profile",
    "api-url",
    "api-key",
    "state-dir",
    "encrypted-vault",
    "demo",
];
fn unsupported(invocation: &Invocation, reason: impl Into<String>) -> CliError {
    CliError::Unsupported {
        command: invocation.command_path(),
        reason: reason.into(),
    }
}
fn supported(invocation: &Invocation) -> bool {
    if invocation.command_path() == "chat" {
        return super::goal_chat::supported(invocation);
    }
    if invocation.command_path()=="embeds share" || super::embed_commands::supported(invocation)
        || super::drafts::supported(invocation)
        || super::global_history::supported(invocation)
        || super::tasks::supported(invocation)
        || super::plans::supported(invocation)
        || super::projects::supported(invocation)
        || super::workflows::supported(invocation)
        || super::account::supported(invocation)
        || super::mentions_cmd::supported(invocation)
        || super::group_help::is_root(invocation)
        || super::chat_work::supported(invocation)
        || super::chat_project::supported(invocation)
        || super::goal_chat::supported(invocation)
        || super::context::supported(invocation)
        || super::docs::is_public(invocation)
        || super::parity_extras::supported(invocation)
        || super::utility::supported(invocation)
        || matches!(
            invocation.command_path().as_str(),
            "wiki search" | "wiki show"
        )
    {
        return true;
    }
    record(&invocation.path).is_some_and(|record| record.implementation.handler.is_some())
        || matches!(
            invocation.path.first().map(String::as_str),
            Some("login" | "server" | "signup" | "tui")
        )
}
pub fn requirements(invocation: &Invocation) -> Requirements {
    let local = matches!(
        invocation.command_path().as_str(),
        "support"
            | "version"
            | "chats incognito-history"
            | "chats incognito-clear"
            | "feedback assistant-response"
            | "apps run"
    ) || invocation.command_path() == "drafts"
        || super::docs::is_public(invocation)
        || super::parity_extras::is_public(invocation)
        || super::group_help::is_root(invocation)
        || !supported(invocation)
        || invocation.path.first().is_some_and(|v| v == "server");
    Requirements {
        authenticated: !local,
        interactive: matches!(
            invocation.command_path().as_str(),
            "login" | "tui" | "tasks resume"
        ),
        supported: supported(invocation),
    }
}
/// Run before opening credential storage. Help is handled directly by Clap.
pub fn execute_public(invocation: &Invocation) -> Option<Result<CliOutput, CliError>> {
    if invocation.command_path()=="embeds share" { if let Some(result)=super::embed_share::preflight(invocation){return Some(result);} }
    if let Some(output) = super::apps_run::public(invocation) { return Some(output); }
    if let Some(output) = super::utility::public(invocation) { return Some(output); }
    if let Some(output) = super::group_help::public(invocation) { return Some(output); }
    if let Some(output) = super::drafts::public(invocation) { return Some(output); }
    if let Some(help) = super::docs::public_help(invocation) {
        return Some(help);
    }
    if let Some(help) = super::parity_extras::help(invocation) {
        return Some(help);
    }
    let path = invocation.command_path();
    if invocation.positionals.is_empty()
        && record(&invocation.path).is_none_or(|record| record.implementation.handler.is_none())
        && catalog().commands.iter().any(|record| {
            record.path.len() > invocation.path.len() && record.path.starts_with(&invocation.path)
        })
    {
        let mut help = command();
        let mut current = &mut help;
        for segment in &invocation.path {
            current = match current.find_subcommand_mut(segment) {
                Some(command) => command,
                None => {
                    return Some(Err(unsupported(
                        invocation,
                        "Command group is not declared.",
                    )));
                }
            };
        }
        return Some(Ok(CliOutput::text(current.render_long_help().to_string())));
    }
    Some(match path.as_str() {
        "chats incognito-history" | "chats incognito-clear" => {
            super::send::incognito_history(invocation)
        }
        "version" => {
            let version = env!("CARGO_PKG_VERSION");
            if invocation.boolean("json") {
                CliOutput::json(
                    &json!({"command":"version","channel":if version.contains('-'){"dev"}else{"stable"},"current_version":version,"latest_version":null,"update_available":null,"check_error":"Native update availability checks are not implemented yet.","upgrade_command":null,"implementation":"rust"}),
                )
            } else {
                Ok(CliOutput::text(format!(
                    "OpenMates CLI {version} (Rust)\nNative update availability check is not implemented yet."
                )))
            }
        }
        "support" => {
            if invocation.boolean("json") {
                CliOutput::json(
                    &json!({"url":"https://app.openmates.org/#settings/support","voluntary":true,"message":"Financial support is voluntary and helps keep OpenMates maintained."}),
                )
            } else {
                Ok(CliOutput::text(
                    "Support OpenMates development:\n  https://app.openmates.org/#settings/support\n\nFinancial support is voluntary and helps keep OpenMates maintained.",
                ))
            }
        }
        "feedback assistant-response" => {
            let rating = invocation.text("rating").and_then(|v| v.parse::<u8>().ok());
            match rating {
                Some(rating @ 1..=5) => {
                    let mut decision = json!({"rating":rating,"action":if rating<=3{"report_issue"}else{"thanks"},"message":"Thanks for the feedback!"});
                    if rating <= 3 {
                        decision["reportTitle"] = json!("Assistant response quality bad:");
                    }
                    if invocation.boolean("json") {
                        CliOutput::json(&decision)
                    } else {
                        Ok(CliOutput::text(if rating <= 3 {
                            "Thanks for the feedback!\nReport issue title: Assistant response quality bad:\nOpen the report issue form and include the affected assistant response."
                        } else {
                            "Thanks for the feedback!"
                        }))
                    }
                }
                _ => Err(CliError::Invalid(
                    "Rating must be an integer from 1 to 5.".into(),
                )),
            }
        }
        _ => {
            if supported(invocation) {
                return None;
            }
            Err(unsupported(
                invocation,
                "See config/cli-command-catalog.json for migration status.",
            ))
        }
    })
}
pub(super) fn flags(invocation: &Invocation, allowed: &[&str]) -> Result<(), CliError> {
    for key in invocation.flags.keys() {
        if invocation.flags[key].is_array() {
            return Err(CliError::Invalid(format!(
                "Option --{key} must be supplied once for this native handler."
            )));
        }
        if !GLOBALS.contains(&key.as_str()) && !allowed.contains(&key.as_str()) {
            return Err(unsupported(
                invocation,
                format!("Option --{key} is not ported for this native handler."),
            ));
        }
    }
    Ok(())
}
fn positional<'a>(
    invocation: &'a Invocation,
    index: usize,
    label: &str,
) -> Result<&'a str, CliError> {
    invocation
        .positionals
        .get(index)
        .map(String::as_str)
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| CliError::Invalid(format!("Missing {label}.")))
}
fn required<'a>(invocation: &'a Invocation, key: &str) -> Result<&'a str, CliError> {
    invocation
        .text(key)
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| CliError::Invalid(format!("Missing --{key}.")))
}
fn number(
    invocation: &Invocation,
    key: &str,
    default: usize,
    max: usize,
) -> Result<usize, CliError> {
    match invocation.text(key) {
        None => Ok(default),
        Some(value) => value
            .parse()
            .ok()
            .filter(|n| *n > 0 && *n <= max)
            .ok_or_else(|| CliError::Invalid(format!("--{key} must be from 1 to {max}."))),
    }
}
fn status(value: &str) -> Result<&str, CliError> {
    if ["backlog", "todo", "in_progress", "blocked", "done"].contains(&value) {
        Ok(value)
    } else {
        Err(CliError::Invalid("Unknown Task status.".into()))
    }
}
pub(super) fn output(
    invocation: &Invocation,
    value: Value,
    text: String,
) -> Result<CliOutput, CliError> {
    if invocation.boolean("json") {
        CliOutput::json(&value)
    } else {
        Ok(CliOutput::text(text))
    }
}
fn item_text(item: &Item) -> String {
    let mut text = format!("{}\nID: {}", item.title, item.id);
    if !item.status.is_empty() {
        text.push_str(&format!("\nStatus: {}", item.status));
    }
    if !item.description.is_empty() {
        text.push_str(&format!("\n\n{}", item.description));
    }
    text
}
fn list_output(
    invocation: &Invocation,
    name: &str,
    items: Vec<Item>,
) -> Result<CliOutput, CliError> {
    let text = if items.is_empty() {
        format!("No {name} found.")
    } else {
        items
            .iter()
            .map(|item| {
                format!(
                    "{}  {}{}",
                    item.id,
                    item.title,
                    if item.status.is_empty() {
                        String::new()
                    } else {
                        format!("  [{}]", item.status)
                    }
                )
            })
            .collect::<Vec<_>>()
            .join("\n")
    };
    let mut value = json!({name:items});
    if name == "chats" && invocation.boolean("json") {
        for row in value["chats"]
            .as_array_mut()
            .ok_or(CliError::Client(Error::Protocol))?
        {
            // Display strings cannot distinguish untitled, draft/locked
            // fallbacks, or a genuinely empty/user-named title. Require the
            // shared SDK's explicit nullable provenance; never infer it here.
            let title = row["fields"]
                .get("chat_list_title")
                .filter(|title| title.is_null() || title.is_string())
                .ok_or(CliError::Client(Error::Protocol))?
                .clone();
            row["title"] = title;
        }
    }
    output(invocation, value, text)
}
// Human rendering keeps its existing bounded lane; JSON selects its own
// source-compatible latest-30 or explicit strict full-history read.
fn bounded_human_show(invocation:&Invocation)->bool {
    invocation.command_path()=="chats show" && !invocation.boolean("json") && !invocation.boolean("all")
}
pub(super) fn saved_show_flags(invocation:&Invocation)->Result<(),CliError> {
    if invocation.command_path()=="chats show" && invocation.boolean("json") {flags(invocation,&["personal","team","all","raw"])}
    else if invocation.command_path()=="chats show" {flags(invocation,&["personal","team","all"])}
    else {flags(invocation,&["personal","team"])}
}
fn bounded_show_text(read:&openmates_sdk::client::saved_chat_read::SavedChatRead)->String {
    let mut text=chat_text(&read.window.chat);
    if read.window.oversized_message {
        text.push_str("\nA saved message exceeds the bounded window size and was omitted.\n");
    }
    text.push_str(&format!("\nShowing {} messages from a bounded window.",read.window.chat.messages.len()));
    if read.window.has_more_before { text.push_str(" Use --all to request full history."); }
    text.push('\n');
    text
}
fn chat_text(chat: &Chat) -> String {
    let mut out = format!("{}\nChat: {}\n", chat.title, chat.id);
    for message in &chat.messages {
        out.push_str(&format!(
            "\n{}\n{}\n",
            if message.role == "user" {
                "You"
            } else if message.sender.is_empty() {
                "Assistant"
            } else {
                &message.sender
            },
            message.content
        ));
    }
    out
}
async fn mutation(
    invocation: &Invocation,
    client: &mut Client,
    mutation: Mutation,
) -> Result<CliOutput, CliError> {
    let item = client.mutate(mutation).await?;
    match item {
        Some(item) => {
            let text = item_text(&item);
            output(
                invocation,
                serde_json::to_value(item).map_err(|_| CliError::Client(Error::Protocol))?,
                text,
            )
        }
        None => output(invocation, json!({"success":true}), "Saved.".into()),
    }
}
fn workspace(command: &str) -> Option<Workspace> {
    match command {
        "chats" => Some(Workspace::Chats),
        "tasks" => Some(Workspace::Tasks),
        "projects" => Some(Workspace::Projects),
        "workflows" => Some(Workspace::Workflows),
        "apps" => Some(Workspace::Apps),
        _ => None,
    }
}
/// Execute against a root-owned native Client. The caller persists rotated session
/// state after success or failure; this module never selects a credential profile.
pub async fn execute(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    execute_inner(invocation, client, cancel, None, None, None).await
}
pub async fn execute_with_delivery(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    store: &crate::runtime_store::RuntimeStore,
) -> Result<CliOutput, CliError> {
    execute_inner(invocation, client, cancel, Some(store), None, None).await
}
/// Explicit application-only host context. Direct library execute APIs do not
/// discover credentials, enable foreground recovery, or acquire this context.
/// No Debug: the passphrase belongs to the selected native vault.
/// Native application diagnostic events only; never SDK/read authority.
#[derive(Clone, Copy)]
pub enum ListReadDiagnosticStage {
    RecoveryCheckStarted,
    RecoveryChecked { pending_or_uncertain: bool },
    CachedHit,
    /// Warm list served by one chat sync feed catch-up (architecture.sync@2).
    FeedHit,
    ForegroundStarted,
    PreDispatchPersisted,
    ForegroundFinished,
}

pub struct ApplicationRecoveryContext<'a> {
    list_stage_observer: Option<&'a (dyn Fn(ListReadDiagnosticStage) + Send + Sync)>,
    pub store: &'a crate::runtime_store::RuntimeStore,
    pub passphrase: Option<zeroize::Zeroizing<String>>,
    #[cfg(test)]
    after_recovery_persist: Option<std::sync::Arc<CanonicalPersistenceBarrier>>,
}
impl<'a> ApplicationRecoveryContext<'a> {
    pub fn new(
        store: &'a crate::runtime_store::RuntimeStore,
        passphrase: Option<zeroize::Zeroizing<String>>,
    ) -> Self {
        Self {
            store,
            passphrase,
            list_stage_observer: None,
            #[cfg(test)]
            after_recovery_persist: None,
        }
    }
    /// Explicit application-only observer. None is the ordinary/default path.
    /// Receives fixed control-flow events, never a Client, credential or row.
    pub fn with_list_stage_observer(
        mut self,
        observer: Option<&'a (dyn Fn(ListReadDiagnosticStage) + Send + Sync)>,
    ) -> Self {
        self.list_stage_observer = observer;
        self
    }
    fn observe_list_stage(&self, event: ListReadDiagnosticStage) {
        notify_list_stage(self.list_stage_observer, event);
    }
}
fn notify_list_stage(
    observer: Option<&(dyn Fn(ListReadDiagnosticStage) + Send + Sync)>,
    event: ListReadDiagnosticStage,
) {
    if !cfg!(panic = "unwind") { return; }
    if let Some(observer) = observer {
        // No observer result participates in auth, recovery or publication.
        // Never inspect/format a panic payload; ordinary results remain intact.
        if let Err(payload) = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| observer(event))) {
            // Do not run an untrusted panic payload destructor outside the catch.
            std::mem::forget(payload);
        }
    }
}

pub async fn execute_with_foreground_recovery(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    context: ApplicationRecoveryContext<'_>,
) -> Result<CliOutput, CliError> {
    execute_inner(
        invocation,
        client,
        cancel,
        Some(context.store),
        Some(&context),
        None,
    )
    .await
}
/// Application output carries the exact full-read admission through its final
/// command-runtime save. Direct library execute APIs retain their public shape.
pub async fn execute_with_foreground_recovery_admitted(
    invocation:&Invocation,client:&mut Client,cancel:CancellationToken,
    context:ApplicationRecoveryContext<'_>,
)->Result<(CliOutput,Option<openmates_sdk::client::full_chat_read::FullChatReadAdmission>),CliError> {
    let mut full_read=None;
    let output=execute_inner(invocation,client,cancel,Some(context.store),Some(&context),Some(&mut full_read)).await?;
    Ok((output,full_read))
}
#[derive(PartialEq, Eq)]
enum SavedReadRecovery {
    Inventory,
    Selected(String),
}
fn saved_read_recovery(invocation: &Invocation) -> Result<Option<SavedReadRecovery>, CliError> {
    if matches!(
        invocation.command_path().as_str(),
        "chats show" | "chats messages" | "chats list" | "chats search"
    ) && invocation.has("api-key")
    {
        return Err(unsupported(
            invocation,
            "API-key Chat reads are not ported; Cookie credentials were not used as a fallback.",
        ));
    }
    match invocation.command_path().as_str() {
        "chats show" | "chats messages" => {
            saved_show_flags(invocation)?;
            let id = positional(invocation, 0, "chat ID")?;
            if uuid::Uuid::parse_str(id)
                .ok()
                .is_none_or(|parsed| parsed.hyphenated().to_string() != id)
            {
                return Err(CliError::Invalid(
                    "A canonical full chat ID is required.".into(),
                ));
            }
            Ok(Some(SavedReadRecovery::Selected(id.to_owned())))
        }
        "chats search" => {
            flags(invocation, &["personal", "team"])?;
            if invocation.has("api-key") {
                return Err(unsupported(
                    invocation,
                    "API-key Chat search is not ported; Cookie credentials were not used as a fallback.",
                ));
            }
            if invocation.positionals.join(" ").trim().is_empty() {
                return Err(CliError::Invalid(
                    "Missing search query. Usage: openmates chats search <query>".into(),
                ));
            }
            Ok(Some(SavedReadRecovery::Inventory))
        }
        "chats list" => {
            flags(invocation, &["limit", "page", "status", "personal", "team"])?;
            if let Some(value) = invocation.text("status") {
                status(value)?;
            }
            let limit = number(invocation, "limit", 10, 10000)?;
            let page = number(invocation, "page", 1, 100000)?;
            (page - 1)
                .checked_mul(limit)
                .ok_or_else(|| CliError::Invalid("Page offset is too large.".into()))?;
            Ok(Some(SavedReadRecovery::Inventory))
        }
        _ => Ok(None),
    }
}
/// Pure application preflight before profile unlock/authentication. Only the
/// opted-in saved-read surface is checked; unrelated command paths are inert.
pub fn validate_application_saved_read(invocation: &Invocation) -> Result<(), CliError> {
    saved_read_recovery(invocation).map(|_| ())
}
struct RecoveryReadAdmission {
    api_url: String,
    account_id: String,
    owner: String,
    team_id: Option<String>,
    store_generation: u64,
}
impl RecoveryReadAdmission {
    fn capture(
        client: &Client,
        store: &crate::runtime_store::RuntimeStore,
        cancel: &CancellationToken,
    ) -> Result<Self, Error> {
        let session = client.session().ok_or(Error::Authentication)?;
        let account_id = client.user()["id"]
            .as_str()
            .or_else(|| client.user()["user_id"].as_str())
            .filter(|id| !id.is_empty())
            .ok_or(Error::Authentication)?
            .to_owned();
        let admission = Self {
            api_url: session.api_url.clone(),
            account_id,
            owner: session.hashed_email.clone(),
            team_id: session.active_team_id.clone(),
            store_generation: store.generation(),
        };
        admission.check(client, store, cancel)?;
        Ok(admission)
    }
    fn check(
        &self,
        client: &Client,
        store: &crate::runtime_store::RuntimeStore,
        cancel: &CancellationToken,
    ) -> Result<(), Error> {
        if cancel.is_cancelled() || self.store_generation != store.generation() {
            return Err(Error::Cancelled);
        }
        let session = client.session().ok_or(Error::Authentication)?;
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| Error::Protocol)?
            .as_millis();
        if session
            .paired_session_expires_at
            .is_some_and(|expires| u128::from(expires) <= now)
        {
            return Err(Error::Expired);
        }
        let account = client.user()["id"]
            .as_str()
            .or_else(|| client.user()["user_id"].as_str());
        if session.api_url != self.api_url
            || session.hashed_email != self.owner
            || session.active_team_id != self.team_id
            || account != Some(self.account_id.as_str())
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}
#[cfg(test)]
#[derive(Default)]
struct CanonicalPersistenceBarrier {
    persisted: tokio::sync::Notify,
    resume: tokio::sync::Notify,
}
struct CanonicalReadPersistence<'a> {
    context: &'a ApplicationRecoveryContext<'a>,
    admission: &'a RecoveryReadAdmission,
    #[cfg(test)]
    after_persist: Option<std::sync::Arc<CanonicalPersistenceBarrier>>,
}
impl crate::completion_recovery_adapter::CanonicalRecoveryPersistence
    for CanonicalReadPersistence<'_>
{
    fn persist_reconciled_canonical<'a>(
        &'a mut self,
        client: &'a mut Client,
        _chat_id: &'a str,
        cancel: &'a CancellationToken,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<(), Error>> + Send + 'a>> {
        Box::pin(async move {
            self.admission.check(client, self.context.store, cancel)?;
            // The shared SDK has just freshly reconciled canonical ciphertext.
            // open_chat is deliberately not used as an authentication/freshness
            // fence: that public API may return cached state on Offline.
            crate::session_runtime::persist(
                client,
                self.context.store,
                self.context.passphrase.clone(),
            )
            .await?;
            #[cfg(test)]
            if let Some(barrier) = &self.after_persist {
                barrier.persisted.notify_one();
                barrier.resume.notified().await;
            }
            self.admission.check(client, self.context.store, cancel)
        })
    }
}
async fn recover_saved_read(
    client: &mut Client,
    plan: &SavedReadRecovery,
    context: &ApplicationRecoveryContext<'_>,
    cancel: &CancellationToken,
    inventory: bool,
) -> Result<
    (
        RecoveryReadAdmission,
        Option<crate::client::FreshChatInventory>,
    ),
    Error,
> {
    let admission = RecoveryReadAdmission::capture(client, context.store, cancel)?;
    client.set_foreground_completion_recovery(true)?;
    let mut canonical = CanonicalReadPersistence {
        context,
        admission: &admission,
        #[cfg(test)]
        after_persist: context.after_recovery_persist.clone(),
    };
    let result = crate::completion_recovery_adapter::pump_completion_recovery_for_saved_read(
        client,
        context.store,
        crate::completion_recovery_adapter::CompletionRecoveryPumpOptions {
            selected_chat: match plan {
                SavedReadRecovery::Inventory => None,
                SavedReadRecovery::Selected(id) => Some(id.clone()),
            },
            max_attempts: 8,
        },
        cancel,
        &mut canonical,
        inventory,
    )
    .await;
    let disabled = client.set_foreground_completion_recovery(false);
    match (result, disabled) {
        (Err(error), _) | (Ok(_), Err(error)) => Err(error),
        (Ok(outcome), Ok(())) => {
            // Recovery work may have changed the selected Chat after its read
            // round was sent early; the read then sends it again.
            if outcome.attempted > 0 || outcome.canonical_changed {
                client.discard_chat_details_prefetch();
            }
            admission.check(client, context.store, cancel)?;
            Ok((admission, outcome.fresh_inventory))
        }
    }
}
// A newly sealed SDK receipt cannot survive failed or dropped native final
// publication and later escape through command_runtime's ordinary error save.
struct SavedReadFreshnessPublication<'a> {
    client: &'a mut Client,
    committed: bool,
}
impl Drop for SavedReadFreshnessPublication<'_> {
    fn drop(&mut self) {
        if !self.committed {
            self.client.invalidate_chat_list_freshness();
        }
    }
}
#[cfg(test)]
mod final_read_journal_test_hook {
    use super::*;
    type Gates = Vec<(
        CancellationToken,
        std::sync::Arc<CanonicalPersistenceBarrier>,
    )>;
    static GATES: std::sync::OnceLock<std::sync::Mutex<Gates>> = std::sync::OnceLock::new();
    pub(super) struct Registration(CancellationToken);
    impl Drop for Registration {
        fn drop(&mut self) {
            GATES
                .get_or_init(Default::default)
                .lock()
                .unwrap()
                .retain(|(token, _)| *token != self.0);
        }
    }
    pub(super) fn install(
        cancel: &CancellationToken,
    ) -> (Registration, std::sync::Arc<CanonicalPersistenceBarrier>) {
        let gate = std::sync::Arc::new(CanonicalPersistenceBarrier::default());
        GATES
            .get_or_init(Default::default)
            .lock()
            .unwrap()
            .push((cancel.clone(), gate.clone()));
        (Registration(cancel.clone()), gate)
    }
    pub(super) async fn wait(cancel: &CancellationToken) {
        let gate = {
            let mut gates = GATES.get_or_init(Default::default).lock().unwrap();
            gates
                .iter()
                .position(|(token, _)| token == cancel)
                .map(|index| gates.remove(index).1)
        };
        if let Some(gate) = gate {
            gate.persisted.notify_one();
            gate.resume.notified().await;
        }
    }
}
async fn persist_saved_read_output(
    output: &mut CliOutput,
    client: &mut Client,
    context: &ApplicationRecoveryContext<'_>,
    admission: &RecoveryReadAdmission,
    cancel: &CancellationToken,
) -> Result<(), Error> {
    persist_saved_read_output_with_full_read(output,client,context,admission,cancel,None).await
}
async fn persist_saved_read_output_with_full_read(
    output: &mut CliOutput,
    client: &mut Client,
    context: &ApplicationRecoveryContext<'_>,
    admission: &RecoveryReadAdmission,
    cancel: &CancellationToken,
    full_read: Option<&openmates_sdk::client::full_chat_read::FullChatReadAdmission>,
) -> Result<(), Error> {
    // Final read may have refreshed ciphertext/credentials after the pump.
    // Keep rendered private output wiping across this final durable boundary.
    let mut stdout = zeroize::Zeroizing::new(std::mem::take(&mut output.stdout));
    let mut stderr = zeroize::Zeroizing::new(std::mem::take(&mut output.stderr));
    let mut publication = SavedReadFreshnessPublication {
        client,
        committed: false,
    };
    let client = &mut *publication.client;
    admission.check(client, context.store, cancel)?;
    if let Some(full_read)=full_read {full_read.check(client)?;}
    #[cfg(test)]
    final_read_journal_test_hook::wait(cancel).await;
    // Recheck the global journal after canonical reads, before publishing the
    // final receipt. New or malformed uncertainty cannot be saved as settled.
    if !crate::completion_recovery_adapter::load_pending(client, context.store)
        .await?
        .is_empty()
    {
        client.invalidate_chat_list_freshness();
    }
    admission.check(client, context.store, cancel)?;
    if let Some(full_read)=full_read {full_read.check(client)?;}
    crate::session_runtime::persist(client, context.store, context.passphrase.clone()).await?;
    admission.check(client, context.store, cancel)?;
    if let Some(full_read)=full_read {full_read.check(client)?;}
    publication.committed = true;
    output.stdout = std::mem::take(&mut *stdout);
    output.stderr = std::mem::take(&mut *stderr);
    Ok(())
}
struct ScopedRecoveryClient<'a> {
    client: &'a mut Client,
    original: RecoveryReadAdmission,
}
impl<'a> ScopedRecoveryClient<'a> {
    fn capture(
        client: &'a mut Client,
        context: &ApplicationRecoveryContext<'_>,
        cancel: &CancellationToken,
    ) -> Result<Self, Error> {
        let original = RecoveryReadAdmission::capture(client, context.store, cancel)?;
        Ok(Self { client, original })
    }
    fn restore(&mut self) -> Result<(), Error> {
        // This is synchronous, including in Drop after a forced future drop.
        // No accepted canonical mutation or rotated credential is rolled back.
        self.client.set_foreground_completion_recovery(false)?;
        let Some(session) = self.client.session() else {
            return Ok(());
        };
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| Error::Protocol)?
            .as_millis();
        if session
            .paired_session_expires_at
            .is_some_and(|expires| u128::from(expires) <= now)
        {
            self.client.forget_session();
            return Err(Error::Expired);
        }
        let account = self.client.user()["id"]
            .as_str()
            .or_else(|| self.client.user()["user_id"].as_str());
        if session.api_url != self.original.api_url
            || session.hashed_email != self.original.owner
            || account != Some(self.original.account_id.as_str())
        {
            return Err(Error::Cancelled);
        }
        if session.active_team_id != self.original.team_id {
            self.client.set_team(self.original.team_id.as_deref())?;
        }
        Ok(())
    }
}
impl Drop for ScopedRecoveryClient<'_> {
    fn drop(&mut self) {
        let _ = self.restore();
    }
}
async fn execute_recovering_saved_read(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    store: Option<&crate::runtime_store::RuntimeStore>,
    context: &ApplicationRecoveryContext<'_>,
    plan: &SavedReadRecovery,
    full_read_output: Option<&mut Option<openmates_sdk::client::full_chat_read::FullChatReadAdmission>>,
) -> Result<CliOutput, CliError> {
    let mut scoped = ScopedRecoveryClient::capture(client, context, &cancel)?;
    let mut retained_full_read=None;
    let result = async {
        let client = &mut *scoped.client;
        if invocation.boolean("personal") {
            // The admitted scope is already explicit. Avoid resetting an
            // unchanged Personal context; real transitions still clear all
            // SDK scope/key/proof state through the unchanged public setter.
            if client
                .session()
                .is_some_and(|session| session.active_team_id.is_some())
            {
                client.set_team(None)?;
            }
        } else if let Some(team) = invocation.text("team") {
            client.set_team(Some(team))?;
        }
        client.set_operation_cancel(cancel.clone());
        // Only `chats list` runs the global inventory discovery. A selected
        // `chats show` uses targeted discovery and the concurrent open-chat
        // requests only; a later list syncs again if no fresh receipt remains.
        let request_inventory = invocation.command_path() == "chats list";
        let (admission, fresh_inventory) = Box::pin(recover_saved_read(
            client,
            plan,
            context,
            &cancel,
            request_inventory,
        ))
        .await?;
        let (mut output,mut full_read)=if super::full_chat_read::is_full_json(invocation) {
            let (output,full_read)=super::full_chat_read::execute_admitted(invocation,client,&cancel,fresh_inventory).await?;
            (output,Some(full_read))
        } else {
            (Box::pin(execute_context_with_inventory(invocation,client,cancel.clone(),store,fresh_inventory)).await?,None)
        };
        persist_saved_read_output_with_full_read(&mut output, client, context, &admission, &cancel,full_read.as_ref()).await?;
        // Restoration is synchronous; refusal still wipes both rendered lanes.
        let mut stdout=zeroize::Zeroizing::new(std::mem::take(&mut output.stdout));
        let mut stderr=zeroize::Zeroizing::new(std::mem::take(&mut output.stderr));
        if let Some(full_read)=&mut full_read {
            full_read.restore_team(client,scoped.original.team_id.as_deref())?;
        }
        retained_full_read=full_read;
        output.stdout=std::mem::take(&mut *stdout);output.stderr=std::mem::take(&mut *stderr);
        Ok(output)
    }
    .await;
    let restored = scoped.restore();
    match (result, restored) {
        (Err(error), _) => Err(error),
        (Ok(mut output), Err(error)) => {
            output.stdout.zeroize();
            output.stderr.zeroize();
            Err(error.into())
        }
        (Ok(mut output), Ok(())) => {
            if let Some(full_read)=&retained_full_read {
                if let Err(error)=full_read.check(scoped.client) {
                    output.stdout.zeroize();output.stderr.zeroize();return Err(error.into());
                }
            }
            if let Some(slot)=full_read_output {*slot=retained_full_read;}
            Ok(output)
        },
    }
}
async fn execute_inner(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    store: Option<&crate::runtime_store::RuntimeStore>,
    recovery: Option<&ApplicationRecoveryContext<'_>>,
    full_read_output: Option<&mut Option<openmates_sdk::client::full_chat_read::FullChatReadAdmission>>,
) -> Result<CliOutput, CliError> {
    if let Some(result) = execute_public(invocation) {
        return result;
    }
    if cancel.is_cancelled() {
        return Err(Error::Cancelled.into());
    }
    if invocation.command_path() == "embeds share" {
        return Box::pin(super::embed_share::execute(invocation,client,cancel)).await;
    }
    if invocation.command_path() == "embeds versions show" {
        return Box::pin(super::embed_commands::execute_cookie_version(invocation, client, cancel)).await;
    }
    if super::drafts::supported(invocation) {
        return Box::pin(super::drafts::execute(invocation, client, cancel)).await;
    }
    if super::global_history::supported(invocation) {
        return Box::pin(super::global_history::execute(invocation, client, cancel)).await;
    }
    if invocation.boolean("personal") && invocation.has("team") {
        return Err(CliError::Invalid(
            "Choose --personal or --team, not both.".into(),
        ));
    }
    let recovery_plan = if recovery.is_some() {
        saved_read_recovery(invocation)?
    } else {
        None
    };
    if let (Some(context), Some(plan)) = (recovery, recovery_plan.as_ref()) {
        // architecture.sync@2: with a feed cursor, the cached index plus one
        // feed catch-up replaces both the time-based receipt and phase=all.
        // Boxed: keeps the public dispatch future within its stack bound.
        if let Some(output) = Box::pin(try_feed_chat_list(invocation, client, context, &cancel)).await? {
            return Ok(output);
        }
        if let Some(output) = try_warm_default_list(invocation, client, context, &cancel).await? {
            return Ok(output);
        }
        context.observe_list_stage(ListReadDiagnosticStage::ForegroundStarted);
        crate::session_runtime::revoke_chat_cache_before_dispatch(
            client,
            context.store,
            context.passphrase.clone(),
            &cancel,
        )
        .await?;
        context.observe_list_stage(ListReadDiagnosticStage::PreDispatchPersisted);
        let result = Box::pin(execute_recovering_saved_read(
            invocation, client, cancel, store, context, plan, full_read_output,
        ))
        .await;
        context.observe_list_stage(ListReadDiagnosticStage::ForegroundFinished);
        return result;
    }
    let original_team = client
        .session()
        .and_then(|session| session.active_team_id.clone());
    let scoped_context = invocation.boolean("personal") || invocation.has("team");
    if invocation.boolean("personal") {
        client.set_team(None)?;
    } else if let Some(team) = invocation.text("team") {
        client.set_team(Some(team))?;
    }
    client.set_operation_cancel(cancel.clone());
    // Keep unrelated command families off the caller's async stack frame.
    // Nested polling can otherwise exhaust the default executor thread stack
    // even when each individual stored future is only tens of KiB.
    let result = Box::pin(execute_context(invocation, client, cancel, store)).await;
    if scoped_context && client.session().is_some() {
        client.set_team(original_team.as_deref())?;
    }
    result
}
/// Formatting only, private to the native application crate. Direct handlers
/// always validate; command runtime must consume FreshSessionAdmission.
pub(crate) fn admitted_whoami_output(
    invocation: &Invocation,
    user: &Value,
) -> Result<CliOutput, CliError> {
    if invocation.command_path() != "whoami" {
        return Err(CliError::Invalid(
            "Whoami output requires the whoami command.".into(),
        ));
    }
    flags(invocation, &[])?;
    output(invocation, user.clone(), display_object(user))
}
async fn execute_context(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    store: Option<&crate::runtime_store::RuntimeStore>,
) -> Result<CliOutput, CliError> {
    execute_context_with_inventory(invocation, client, cancel, store, None).await
}
async fn execute_context_with_inventory(
    invocation: &Invocation,
    client: &mut Client,
    cancel: CancellationToken,
    store: Option<&crate::runtime_store::RuntimeStore>,
    fresh_inventory: Option<crate::client::FreshChatInventory>,
) -> Result<CliOutput, CliError> {
    // Scope selection/restoration and cancellation belong to execute_inner.
    // Only normalize syntax here, then reuse the canonical delivery handlers.
    let normalized = super::chat_work::normalize(invocation)?;
    let invocation = normalized.as_ref().unwrap_or(invocation);
    if super::docs::is_public(invocation)
        || matches!(
            invocation.command_path().as_str(),
            "wiki search" | "wiki show"
        )
    {
        return Box::pin(super::docs::execute(invocation, client, cancel)).await;
    }
    if super::goal_chat::supported(invocation) {
        return Box::pin(super::goal_chat::execute(invocation, client, cancel)).await;
    }
    if super::context::supported(invocation) {
        return super::context::execute(invocation, client, cancel);
    }
    if super::parity_extras::supported(invocation) {
        return Box::pin(super::parity_extras::execute(invocation, client)).await;
    }
    if super::utility::supported(invocation) { return Box::pin(super::utility::execute(invocation, client)).await; }
    if super::account::supported(invocation) {
        return Box::pin(super::account::execute(invocation, client)).await;
    }
    if super::mentions_cmd::supported(invocation) {
        return Box::pin(super::mentions_cmd::execute(invocation, client)).await;
    }
    if super::chat_project::supported(invocation) {
        return Box::pin(super::chat_project::execute(invocation, client, cancel)).await;
    }
    let path = invocation.command_path();
    if super::tasks::supported(invocation) {
        return Box::pin(super::tasks::execute(invocation, client, cancel, store)).await;
    }
    if super::plans::supported(invocation) {
        return Box::pin(super::plans::execute(invocation, client, cancel, store)).await;
    }
    if super::projects::supported(invocation) {
        return Box::pin(super::projects::execute(invocation, client, cancel, store)).await;
    }
    if super::workflows::supported(invocation) {
        return Box::pin(super::workflows::execute(invocation, client, cancel)).await;
    }
    match path.as_str() {
        "whoami" => {
            flags(invocation, &[])?;
            client.validate_session().await?;
            admitted_whoami_output(invocation, client.user())
        }
        "logout" => {
            flags(invocation, &[])?;
            client.logout().await?;
            output(invocation, json!({"success":true}), "Logged out.".into())
        }
        "switch-to" => {
            flags(invocation, &[])?;
            let target = positional(invocation, 0, "personal or Team ID")?;
            let team = if target == "personal" {
                None
            } else {
                Some(target)
            };
            client.set_team(team)?;
            client.set_operation_cancel(cancel.clone());
            client.validate_session().await?;
            output(
                invocation,
                json!({"context":if team.is_some(){"team"}else{"personal"},"active_team_id":team}),
                format!("Active context: {}", team.unwrap_or("Personal")),
            )
        }
        "chats search" => {
            flags(invocation, &["personal", "team"])?;
            if invocation.has("api-key") {
                return Err(unsupported(
                    invocation,
                    "API-key Chat search is not ported; Cookie credentials were not used as a fallback.",
                ));
            }
            let query = invocation.positionals.join(" ");
            if query.trim().is_empty() {
                return Err(CliError::Invalid(
                    "Missing search query. Usage: openmates chats search <query>".into(),
                ));
            }
            let results = client.search_chats(&query).await?;
            super::history::chat_search_output(invocation, results)
        }
        "chats list" | "projects list" | "workflows list" | "apps list" => {
            flags(invocation, &["limit", "page", "status", "personal", "team"])?;
            let command = invocation.path[0].as_str();
            let selected_workspace = workspace(command).unwrap();
            let mut items = if command == "chats" {
                match fresh_inventory {
                    Some(proof) => {
                        client
                            .list_with_fresh_chat_inventory(selected_workspace, proof, &cancel)
                            .await?
                    }
                    None => client.list(selected_workspace).await?,
                }
            } else {
                client.list(selected_workspace).await?
            };
            // Same overview order as the feed path (sync.overview.priority-order).
            let items = if command == "chats" { client.order_chat_list_items_now(items) } else { items };
            paginated_list_output(invocation, command, items)
        }
        "chats show" | "chats messages" => {
            saved_show_flags(invocation)?;
            let id = positional(invocation, 0, "chat ID")?;
            if bounded_human_show(invocation) {
                // A viewing page must not consume the full-history terminal
                // proof or mint inventory/cache freshness. Recovery and final
                // plaintext/store publication still wrap this unchanged lane.
                drop(fresh_inventory);
                let read=client.saved_chat_read(id,openmates_sdk::client::saved_chat_read::SavedChatReadOptions {
                    limit:30,
                    // The preserved CLI shows one server-capped viewing page;
                    // it must not refill a short page to the logical30-row budget.
                    max_pages:1,
                    content_mode:openmates_sdk::client::saved_chat_read::SavedChatContentMode::Stored,
                    ..Default::default()
                }).await?;
                return Ok(CliOutput::text(bounded_show_text(&read)));
            }
            if super::full_chat_read::is_full_json(invocation) {
                let (output, _admission) = super::full_chat_read::execute_admitted(
                    invocation, client, &cancel, fresh_inventory,
                ).await?;
                return Ok(output);
            }
            let chat = match fresh_inventory {
                Some(proof) => {
                    client
                        .open_chat_with_fresh_chat_inventory(id, proof, &cancel)
                        .await?
                }
                None => client.open_chat(id).await?,
            };
            let text = chat_text(&chat);
            output(
                invocation,
                serde_json::to_value(chat).map_err(|_| CliError::Client(Error::Protocol))?,
                text,
            )
        }
        "projects show" | "workflows show" => {
            flags(invocation, &["personal", "team"])?;
            let item = client
                .detail(
                    workspace(&invocation.path[0]).unwrap(),
                    positional(invocation, 0, "object ID")?,
                )
                .await?;
            let text = item_text(&item);
            output(
                invocation,
                serde_json::to_value(item).map_err(|_| CliError::Client(Error::Protocol))?,
                text,
            )
        }
        "apps info" => {
            flags(invocation, &[])?;
            let item = client
                .app_detail(positional(invocation, 0, "app ID")?)
                .await?;
            let text = item_text(&item);
            output(
                invocation,
                serde_json::to_value(item).map_err(|_| CliError::Client(Error::Protocol))?,
                text,
            )
        }
        "apps skill-info" => {
            flags(invocation, &[])?;
            let id = format!(
                "skill:{}/{}",
                positional(invocation, 0, "app ID")?,
                positional(invocation, 1, "skill ID")?
            );
            let item = client.app_detail(&id).await?;
            let text = item_text(&item);
            output(
                invocation,
                serde_json::to_value(item).map_err(|_| CliError::Client(Error::Protocol))?,
                text,
            )
        }
        "embeds show" => {
            flags(invocation, &["personal", "team"])?;
            let item = client
                .detail(
                    Workspace::Apps,
                    &format!("embed:{}", positional(invocation, 0, "embed ID")?),
                )
                .await?;
            let text = display_object(&item.fields);
            output(
                invocation,
                serde_json::to_value(item).map_err(|_| CliError::Client(Error::Protocol))?,
                text,
            )
        }
        "chats delete" => {
            flags(invocation, &["yes", "personal", "team"])?;
            if !invocation.boolean("yes") {
                return Err(CliError::Invalid(
                    "Use --yes to confirm chat deletion.".into(),
                ));
            }
            if invocation.positionals.is_empty() {
                return Err(CliError::Invalid("Provide at least one chat ID.".into()));
            }
            for id in &invocation.positionals {
                client
                    .mutate(Mutation::Delete {
                        workspace: Workspace::Chats,
                        id: id.clone(),
                    })
                    .await?;
            }
            output(
                invocation,
                json!({"deleted":invocation.positionals}),
                "Deleted the selected chats.".into(),
            )
        }
        "projects update" | "projects archive" | "projects unarchive" => {
            flags(
                invocation,
                &["name", "description", "pin", "unpin", "personal", "team"],
            )?;
            let mut fields = json!({});
            if invocation.boolean("pin") && invocation.boolean("unpin") {
                return Err(CliError::Invalid("Choose --pin or --unpin.".into()));
            }
            for (name, target) in [("name", "title"), ("description", "description")] {
                if let Some(value) = invocation.text(name) {
                    fields[target] = json!(value);
                }
            }
            if invocation.has("pin") || invocation.has("unpin") {
                fields["pinned"] = json!(invocation.boolean("pin"));
            }
            if path != "projects update" {
                fields["archived"] = json!(path == "projects archive");
            }
            if fields.as_object().unwrap().is_empty() {
                return Err(CliError::Invalid(
                    "Provide a Project field to update.".into(),
                ));
            }
            mutation(
                invocation,
                client,
                Mutation::Update {
                    workspace: Workspace::Projects,
                    id: positional(invocation, 0, "Project ID")?.into(),
                    fields,
                },
            )
            .await
        }
        "projects delete" => {
            flags(invocation, &["confirm", "personal", "team"])?;
            let id = positional(invocation, 0, "Project ID")?;
            if invocation.text("confirm") != Some(id) {
                return Err(CliError::Invalid(
                    "Confirm deletion with --confirm and the exact Project ID.".into(),
                ));
            }
            mutation(
                invocation,
                client,
                Mutation::Delete {
                    workspace: Workspace::Projects,
                    id: id.into(),
                },
            )
            .await
        }
        "workflows create" | "workflows update" => {
            flags(invocation, &["title", "graph", "enabled"])?;
            let graph: Value = serde_json::from_str(required(invocation, "graph")?)
                .map_err(|_| CliError::Invalid("--graph must be valid JSON.".into()))?;
            if !graph.is_object() {
                return Err(CliError::Invalid("--graph must be an object.".into()));
            }
            let mut fields = json!({"graph":graph});
            if let Some(title) = invocation.text("title") {
                fields["title"] = json!(title);
            }
            if invocation.has("enabled") {
                fields["enabled"] = json!(invocation.boolean("enabled"));
            }
            let operation = if path == "workflows create" {
                required(invocation, "title")?;
                Mutation::Create {
                    workspace: Workspace::Workflows,
                    fields,
                }
            } else {
                Mutation::Update {
                    workspace: Workspace::Workflows,
                    id: positional(invocation, 0, "Workflow ID")?.into(),
                    fields,
                }
            };
            mutation(invocation, client, operation).await
        }
        "workflows enable" | "workflows disable" => {
            flags(invocation, &[])?;
            mutation(
                invocation,
                client,
                Mutation::Update {
                    workspace: Workspace::Workflows,
                    id: positional(invocation, 0, "Workflow ID")?.into(),
                    fields: json!({"enabled":path=="workflows enable"}),
                },
            )
            .await
        }
        "workflows delete" => {
            flags(invocation, &["yes"])?;
            if !invocation.boolean("yes") {
                return Err(CliError::Invalid(
                    "Use --yes to delete this Workflow.".into(),
                ));
            }
            mutation(
                invocation,
                client,
                Mutation::Delete {
                    workspace: Workspace::Workflows,
                    id: positional(invocation, 0, "Workflow ID")?.into(),
                },
            )
            .await
        }
        "drafts clear" => {
            flags(invocation, &[])?;
            if invocation.has("api-key") {
                return Err(unsupported(
                    invocation,
                    "API-key draft clearing is not supported; Cookie credentials were not used as a fallback.",
                ));
            }
            if invocation.positionals.len() != 1 {
                return Err(CliError::Invalid(
                    "Provide exactly one full chat ID for draft clear.".into(),
                ));
            }
            let id = positional(invocation, 0, "chat ID")?;
            client.clear_draft(id).await?;
            // Draft commands retain their legacy unconditional JSON contract.
            CliOutput::json(&json!({"success":true,"chat_id":id}))
        }
        "drafts create" | "drafts update" => {
            flags(invocation, &["chat"])?;
            let (update, offset) = if path == "drafts update" {
                (Some(positional(invocation, 0, "chat ID")?), 1)
            } else {
                (invocation.text("chat"), 0)
            };
            let text = invocation
                .positionals
                .get(offset..)
                .unwrap_or(&[])
                .join(" ");
            if text.trim().is_empty() {
                return Err(CliError::Invalid("Provide draft text.".into()));
            }
            let id = client.save_draft(update, &text).await?;
            CliOutput::json(&json!({"chat_id":id,"saved":true}))
        }
        "settings interface language set"
        | "settings interface dark-mode set"
        | "settings account timezone set"
        | "account timezone set" => {
            flags(invocation, &[])?;
            let value = positional(invocation, 0, "setting value")?;
            let (section, value) = if path.contains("language") {
                ("language", json!(value))
            } else if path.contains("dark-mode") {
                (
                    "darkmode",
                    match value {
                        "on" | "true" => json!(true),
                        "off" | "false" => json!(false),
                        _ => return Err(CliError::Invalid("Use on or off.".into())),
                    },
                )
            } else {
                ("timezone", json!(value))
            };
            mutation(
                invocation,
                client,
                Mutation::SetSetting {
                    section: section.into(),
                    fields: json!({"value":value}),
                },
            )
            .await
        }
        "chats download" => {
            flags(invocation, &["output", "overwrite"])?;
            let id = positional(invocation, 0, "chat ID")?;
            let destination = required(invocation, "output")?;
            client
                .download(
                    Workspace::Chats,
                    id,
                    std::path::Path::new(destination),
                    invocation.boolean("overwrite"),
                )
                .await?;
            output(
                invocation,
                json!({"path":destination,"chat_id":id}),
                format!("Saved {destination}"),
            )
        }
        "chats share" => {
            flags(
                invocation,
                &["expires", "password", "include-sensitive-data"],
            )?;
            let duration = invocation
                .text("expires")
                .unwrap_or("86400")
                .parse::<u64>()
                .map_err(|_| CliError::Invalid("--expires must contain seconds.".into()))?;
            let url = client
                .share_chat(
                    positional(invocation, 0, "chat ID")?,
                    duration,
                    invocation.text("password").unwrap_or(""),
                    invocation.boolean("include-sensitive-data"),
                )
                .await?;
            output(invocation, json!({"url":url}), url)
        }
        "chats send" | "chats new" | "chats incognito" | "chats answer-interactive" => {
            Box::pin(super::send::send(invocation, client, cancel)).await
        }
        _ if invocation.path.first().is_some_and(|v| v == "apps") => app(invocation, client).await,
        _ => Err(unsupported(
            invocation,
            "The parser recognizes this operation, but its native handler is pending.",
        )),
    }
}
pub(super) fn display_object(value: &Value) -> String {
    fn add(value: &Value, prefix: &str, rows: &mut Vec<String>) {
        match value {
            Value::Object(object) => {
                for (key, value) in object {
                    if [
                        "password",
                        "session_id",
                        "ws_token",
                        "master_key",
                        "cookies",
                    ]
                    .iter()
                    .any(|secret| key == secret)
                    {
                        continue;
                    }
                    add(
                        value,
                        &if prefix.is_empty() {
                            key.replace('_', " ")
                        } else {
                            format!("{prefix} / {}", key.replace('_', " "))
                        },
                        rows,
                    )
                }
            }
            Value::Array(values) => {
                for (value, index) in values.iter().zip(1..) {
                    add(value, &format!("{prefix} [{index}]"), rows)
                }
            }
            Value::Null => {}
            Value::String(text) => rows.push(format!("{prefix}: {text}")),
            _ => rows.push(format!("{prefix}: {value}")),
        }
    }
    let mut rows = vec![];
    add(value, "", &mut rows);
    rows.join("\n")
}
/// Direct Personal CLI entry installs one exact child before capturing its
/// original restrictive output scope; no post-IO substitute admission is used.
pub fn is_direct_apps_command(invocation:&Invocation)->bool {
    invocation.path.first().is_some_and(|name|name=="apps")
        && record(&invocation.path).is_some_and(|entry|entry.skill_schema.is_some())
}
pub async fn execute_direct_apps_admitted(
    invocation:&Invocation,client:&mut Client,store:&crate::runtime_store::RuntimeStore,cancel:CancellationToken,
)->Result<(Result<CliOutput,CliError>,openmates_sdk::client::DirectAppSkillAdmission),CliError> {
    if !is_direct_apps_command(invocation){return Err(Error::Protocol.into());}
    if cancel.is_cancelled(){return Err(Error::Cancelled.into());}
    client.set_operation_cancel(cancel.clone());
    let admission=client.direct_app_skill_admission()?;
    let store_generation=store.generation();
    let mut output=PendingAppResult(Some(app_with_admission(invocation,client,&admission,Some((store,store_generation))).await));
    if store.generation()!=store_generation{return Err(Error::Cancelled.into());}
    if cancel.is_cancelled(){return Err(Error::Cancelled.into());}
    admission.check(client)?;
    Ok((output.0.take().ok_or(Error::Protocol)?,admission))
}
struct PendingAppResult(Option<Result<CliOutput,CliError>>);
impl Drop for PendingAppResult {
    fn drop(&mut self){if let Some(result)=self.0.as_mut(){match result {
        Ok(output)=>{output.stdout.zeroize();output.stderr.zeroize();},
        Err(error)=>super::erase_error(error),
    }}}
}
struct AppTaskIds(Vec<String>);
impl Drop for AppTaskIds {fn drop(&mut self){self.0.iter_mut().for_each(Zeroize::zeroize);}}
struct AppInput(Value);
impl Drop for AppInput { fn drop(&mut self) { super::erase(&mut self.0); } }
async fn app(invocation: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    let admission=client.direct_app_skill_admission()?;
    let mut output=PendingAppResult(Some(app_with_admission(invocation,client,&admission,None).await));
    admission.check(client)?;
    output.0.take().ok_or(CliError::Client(Error::Protocol))?
}
async fn app_with_admission(invocation:&Invocation,client:&mut Client,
    admission:&openmates_sdk::client::DirectAppSkillAdmission,
    store:Option<(&crate::runtime_store::RuntimeStore,u64)>)->Result<CliOutput,CliError> {
    admission.check(client)?;
    let record = record(&invocation.path);
    let record = record
        .filter(|record| record.skill_schema.is_some())
        .ok_or_else(|| {
            unsupported(
                invocation,
                "Use an explicit generated app-skill command; generic execution is unavailable.",
            )
        })?;
    let (app, skill) = (
        record
            .app
            .as_deref()
            .ok_or(CliError::Client(Error::Protocol))?,
        record
            .skill
            .as_deref()
            .ok_or(CliError::Client(Error::Protocol))?,
    );
    let input = if let Some(input) = invocation.text("input") {
        let value: Value = serde_json::from_str(input)
            .map_err(|_| CliError::Invalid("--input must be valid JSON.".into()))?;
        if !value.is_object() {
            return Err(CliError::Invalid("--input must be an object.".into()));
        }
        flags(invocation, &["input","output","output-dir","filename","no-download"])?;
        value
    } else {
        let schema = record.skill_schema.as_ref().ok_or_else(|| {
            unsupported(
                invocation,
                "Use --input for a skill without generated native flag metadata.",
            )
        })?;
        build_skill_input(invocation, schema)?
    };
    // Noninteractive commands use the existing direct result contract. The
    // Workspace::Apps mutation remains retained for interactive TUI callers.
    let input = AppInput(input);
    super::generated_files::validate(invocation, &input.0)?;
    let mut original_tasks = AppTaskIds(Vec::<String>::new());
    let executed = client.run_direct_app_skill_with_task_receipt(app, skill, input.0.clone(),
        |ids| original_tasks.0.extend_from_slice(ids)).await;
    let mut result = AppInput(match executed {
        Ok(value) => value,
        Err(error) if !original_tasks.0.is_empty() && matches!(error, Error::Offline | Error::Invalid(_)) => {
            // No task key or result graph is saved by this command. Original
            // validated IDs make a timeout actionable without replaying intent.
            admission.check(client)?;
            if store.is_some_and(|(store,generation)|store.generation()!=generation){return Err(Error::Cancelled.into());}
            let message = format!("{error} Original task IDs: {}. Generation was not retried.", original_tasks.0.join(", "));
            original_tasks.0.iter_mut().for_each(Zeroize::zeroize);
            return Err(CliError::Contract { code: "command_failed", message });
        }
        Err(error) => { original_tasks.0.iter_mut().for_each(Zeroize::zeroize); return Err(error.into()); }
    });
    original_tasks.0.iter_mut().for_each(Zeroize::zeroize);
    admission.check(client)?;
    let saved = super::generated_files::finish(invocation, client, admission, store, &input.0, &mut result.0).await?;
    admission.check(client)?;
    if invocation.boolean("json") { return CliOutput::json(&result.0); }
    let mut text = display_object(&result.0);
    for path in saved { text.push_str(&format!("\nSaved {path}")); }
    Ok(CliOutput::text(text))
}
fn build_skill_input(invocation: &Invocation, schema: &Value) -> Result<Value, CliError> {
    let request = schema
        .pointer("/properties/requests")
        .filter(|s| s["type"] == "array");
    let shape = request.and_then(|r| r.get("items")).unwrap_or(schema);
    let properties = shape["properties"]
        .as_object()
        .ok_or_else(|| unsupported(invocation, "Use --input for this schema."))?;
    let names = properties
        .keys()
        .map(|k| k.replace('_', "-"))
        .collect::<Vec<_>>();
    let mut refs = names.iter().map(String::as_str).collect::<Vec<_>>();
    refs.extend_from_slice(super::generated_files::flags());
    flags(invocation, &refs)?;
    let mut input = serde_json::Map::new();
    let mut used_primary = false;
    for (name, definition) in properties {
        let flag = name.replace('_', "-");
        let raw = invocation.text(&flag);
        let value = if let Some(raw) = raw {
            let kind = definition["type"].as_str().unwrap_or("string");
            match kind {
                "string" => json!(raw),
                "boolean" => match raw {
                    "true" => json!(true),
                    "false" => json!(false),
                    _ => {
                        return Err(CliError::Invalid(format!(
                            "--{flag} must be true or false."
                        )));
                    }
                },
                "integer" => json!(
                    raw.parse::<i64>()
                        .map_err(|_| CliError::Invalid(format!("--{flag} must be an integer.")))?
                ),
                "number" => {
                    let value = raw
                        .parse::<f64>()
                        .ok()
                        .filter(|n| n.is_finite())
                        .ok_or_else(|| {
                            CliError::Invalid(format!("--{flag} must be a finite number."))
                        })?;
                    json!(value)
                }
                "array" | "object" => serde_json::from_str(raw)
                    .map_err(|_| CliError::Invalid(format!("--{flag} must be valid JSON.")))?,
                _ => {
                    return Err(unsupported(
                        invocation,
                        format!("Use --input for field {name}."),
                    ));
                }
            }
        } else if !used_primary
            && ["query", "prompt", "text", "location", "expression", "url"].contains(&name.as_str())
            && !invocation.positionals.is_empty()
        {
            used_primary = true;
            json!(invocation.positionals.join(" "))
        } else if ["provider", "model", "provider_id", "model_id"].contains(&name.as_str()) {
            continue;
        } else if let Some(value) = definition.get("default") {
            value.clone()
        } else {
            continue;
        };
        input.insert(name.clone(), value);
    }
    let input = Value::Object(input);
    Ok(if request.is_some() {
        json!({"requests":[input]})
    } else {
        input
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn incognito_history_aliases_are_public_stateless_and_keep_legacy_json() {
        for path in ["incognito-history", "incognito-clear"] {
            let command = invocation(&["chats", path], &[("json", json!(true))], &[]);
            let requirements = requirements(&command);
            assert!(!requirements.authenticated && !requirements.interactive);
            let result = execute_public(&command)
                .unwrap()
                .unwrap_or_else(|error| panic!("{error}"));
            let value: Value = serde_json::from_str(&result.stdout).unwrap();
            assert_eq!(value["history"], json!([]));
            assert_eq!(value["stored"], false);
            assert_eq!(
                value["message"],
                "Incognito chats are not stored. There is no incognito history to show or clear."
            );
            assert_eq!(result.exit_code, 0);
            assert!(result.stderr.is_empty());
        }
        let plain = invocation(&["chat"], &[], &["hello"]);
        assert!(matches!(
            execute_public(&plain),
            Some(Err(CliError::Unsupported { .. }))
        ));
    }
    #[test]
    fn chat_list_json_projects_only_explicit_nullable_title_and_preserves_rows() {
        let values = [
            ("", Value::Null, ""),
            ("", json!(""), ""),
            ("Synthetic title", json!("Synthetic title"), ""),
            ("Draft", json!("Draft"), ""),
            ("Locked chat", json!("Locked chat"), ""),
            ("Synthetic draft preview", Value::Null, "draft"),
            ("Locked chat", Value::Null, "locked"),
        ];
        let items = values
            .iter()
            .enumerate()
            .map(|(index, (display, title, status))| Item {
                id: format!("synthetic-{index}"),
                title: (*display).into(),
                status: (*status).into(),
                fields: json!({"chat_list_title":title,"pinned":true}),
                ..Item::default()
            })
            .collect::<Vec<_>>();
        let before = serde_json::to_value(&items).unwrap();
        let command = invocation(
            &["chats", "list"],
            &[("json", json!(true)), ("limit", json!("100"))],
            &[],
        );
        let output = paginated_list_output(&command, "chats", items.clone())
            .unwrap_or_else(|_| panic!("Synthetic chat list should render"));
        let result: Value = serde_json::from_str(&output.stdout).unwrap();
        assert_eq!(result["chats"].as_array().unwrap().len(), values.len());
        for (index, (_, title, status)) in values.iter().enumerate() {
            assert_eq!(result["chats"][index]["id"], format!("synthetic-{index}"));
            assert_eq!(&result["chats"][index]["title"], title);
            assert_eq!(result["chats"][index]["status"], *status);
            assert_eq!(result["chats"][index]["fields"]["pinned"], true);
        }
        assert_eq!(serde_json::to_value(&items).unwrap(), before);
        let text = list_output(&invocation(&["chats", "list"], &[], &[]), "chats", items)
            .unwrap_or_else(|_| panic!("Synthetic chat text should render"));
        assert!(
            text.stdout
                .contains("synthetic-5  Synthetic draft preview  [draft]")
        );
        assert!(text.stdout.contains("synthetic-6  Locked chat  [locked]"));
    }
    #[test]
    fn chat_json_refuses_missing_or_invalid_nullable_title_provenance() {
        let command = invocation(&["chats", "list"], &[("json", json!(true))], &[]);
        for fields in [
            Value::Null,
            json!({}),
            json!({"chat_list_title":1}),
            json!({"chat_list_title":false}),
            json!({"chat_list_title":{}}),
        ] {
            let item = Item {
                id: "synthetic".into(),
                title: "Draft".into(),
                fields,
                ..Item::default()
            };
            assert!(matches!(
                list_output(&command, "chats", vec![item]),
                Err(CliError::Client(Error::Protocol))
            ));
        }
    }
    #[test]
    fn nonchat_list_json_keeps_string_titles_and_generic_fields_unchanged() {
        for name in ["projects", "workflows", "apps", "tasks"] {
            let item = Item {
                id: "synthetic".into(),
                title: "Display title".into(),
                fields: json!({"chat_list_title":null,"other":"Synthetic data"}),
                ..Item::default()
            };
            let expected = serde_json::to_value(&item).unwrap();
            let output = list_output(
                &invocation(&[name, "list"], &[("json", json!(true))], &[]),
                name,
                vec![item],
            )
            .unwrap_or_else(|_| panic!("Synthetic non-chat list should render"));
            let result: Value = serde_json::from_str(&output.stdout).unwrap();
            assert_eq!(result[name][0], expected);
        }
    }
    #[test]
    fn version_json_preserves_script_fields_and_reports_unknown_updates() {
        let command = invocation(&["version"], &[("json", json!(true))], &[]);
        let output = execute_public(&command)
            .unwrap()
            .unwrap_or_else(|error| panic!("{error}"));
        let value: Value = serde_json::from_str(&output.stdout).unwrap();
        assert_eq!(value["command"], "version");
        assert_eq!(value["current_version"], env!("CARGO_PKG_VERSION"));
        assert!(value["channel"].is_string());
        assert!(value["check_error"].is_string());
        for field in ["latest_version", "update_available", "upgrade_command"] {
            assert!(value.as_object().unwrap().contains_key(field));
            assert!(value[field].is_null());
        }
        assert_eq!(output.exit_code, 0);
        assert!(output.stderr.is_empty());
    }
    fn invocation(path: &[&str], flags: &[(&str, Value)], args: &[&str]) -> Invocation {
        Invocation {
            path: path.iter().map(|v| (*v).into()).collect(),
            flags: flags
                .iter()
                .map(|(k, v)| ((*k).into(), v.clone()))
                .collect(),
            positionals: args.iter().map(|v| (*v).into()).collect(),
        }
    }
    #[tokio::test]
    async fn temporary_scope_does_not_cancel_the_injected_caller_and_restores_original_team() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        const ORIGINAL: &str = "11111111-1111-4111-8111-111111111111";
        const SELECTED: &str = "22222222-2222-4222-8222-222222222222";
        for personal in [true, false] {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let base = format!("http://{}", listener.local_addr().unwrap());
            let wrapped = crate::crypto::encrypt_bytes(&[9; 32], &[7; 32]).unwrap();
            let requests = std::sync::Arc::new(std::sync::Mutex::new(Vec::<String>::new()));
            let received = requests.clone();
            let server = tokio::spawn(async move {
                for _ in 0..if personal { 1 } else { 2 } {
                    let (mut socket, _) = listener.accept().await.unwrap();
                    let mut bytes = vec![];
                    while !bytes.windows(4).any(|part| part == b"\r\n\r\n") {
                        let mut part = [0; 4096];
                        let count = socket.read(&mut part).await.unwrap();
                        assert!(count > 0);
                        bytes.extend_from_slice(&part[..count]);
                    }
                    let header = std::str::from_utf8(&bytes).unwrap();
                    let path = header
                        .lines()
                        .next()
                        .unwrap()
                        .split_whitespace()
                        .nth(1)
                        .unwrap()
                        .to_owned();
                    received.lock().unwrap().push(path.clone());
                    let body = if path.starts_with("/v1/teams/") {
                        assert_eq!(path, format!("/v1/teams/{SELECTED}"));
                        json!({"team":{"team_id":SELECTED,"encrypted_team_key":wrapped}})
                    } else {
                        assert!(path.starts_with("/v1/user-tasks?"));
                        assert_eq!(path.contains(&format!("team_id={SELECTED}")), !personal);
                        json!({"tasks":[],"complete":true})
                    }
                    .to_string();
                    let response = format!(
                        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                        body.len()
                    );
                    socket.write_all(response.as_bytes()).await.unwrap();
                }
            });
            let session = openmates_sdk::Session {
                api_url: base.clone(),
                session_id: "synthetic".into(),
                cookies: BTreeMap::new(),
                ws_token: None,
                master_key: zeroize::Zeroizing::new([7; 32]),
                hashed_email: "synthetic-owner".into(),
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: None,
                active_team_id: Some(ORIGINAL.into()),
            };
            let mut client = Client::new(&base, Some(session)).unwrap();
            let caller = CancellationToken::new();
            client.set_operation_cancel(caller.clone());
            let command = invocation(
                &["tasks", "list"],
                &[
                    (
                        if personal { "personal" } else { "team" },
                        if personal {
                            json!(true)
                        } else {
                            json!(SELECTED)
                        },
                    ),
                    ("json", json!(true)),
                ],
                &[],
            );
            let result = tokio::time::timeout(
                std::time::Duration::from_secs(3),
                execute_inner(&command, &mut client, caller.clone(), None, None, None),
            )
            .await
            .unwrap();
            assert!(
                !caller.is_cancelled(),
                "Changing or restoring a command scope must not cancel its caller root token"
            );
            let result = result
                .ok()
                .expect("synthetic canonical scoped Task list succeeds");
            assert_eq!(
                serde_json::from_str::<Value>(&result.stdout).unwrap()["tasks"],
                json!([])
            );
            assert_eq!(
                client.session().unwrap().active_team_id.as_deref(),
                Some(ORIGINAL)
            );
            tokio::time::timeout(std::time::Duration::from_secs(3), server)
                .await
                .unwrap()
                .unwrap();
            assert_eq!(requests.lock().unwrap().len(), if personal { 1 } else { 2 });
        }
    }
    #[test]
    fn public_dispatch_futures_have_bounded_stack_frames() {
        fn bytes<F: std::future::Future>(_: impl FnOnce() -> F) -> usize {
            std::mem::size_of::<F>()
        }
        let mut client = Client::new("https://synthetic.example", None).unwrap();
        let command = invocation(&["tasks", "list"], &[], &[]);
        let size = bytes(|| execute(&command, &mut client, CancellationToken::new()));
        assert!(size <= 4096, "CLI dispatch future uses {size} stack bytes");
    }
    #[test]
    fn unsupported_is_explicit_before_credentials() {
        let command = invocation(&["teams", "profile-image", "get"], &[], &["team-1"]);
        assert!(!requirements(&command).authenticated);
        let error = execute_public(&command).unwrap().err().unwrap();
        assert_eq!(error.exit_code(), 1);
        assert!(error.to_string().contains("not implemented"));
    }
    #[test]
    fn feedback_matches_existing_contract() {
        for rating in 1..=5 {
            let command = invocation(
                &["feedback", "assistant-response"],
                &[("rating", json!(rating.to_string())), ("json", json!(true))],
                &[],
            );
            let out = execute_public(&command).unwrap().ok().unwrap();
            let value: Value = serde_json::from_str(&out.stdout).unwrap();
            assert_eq!(
                value["action"],
                if rating <= 3 {
                    "report_issue"
                } else {
                    "thanks"
                }
            );
        }
    }
    #[test]
    fn generated_skill_input_preserves_types_and_request_shape() {
        let command = invocation(
            &["apps", "web", "search"],
            &[("count", json!("3"))],
            &["Rust privacy"],
        );
        let schema = json!({"type":"object","properties":{"requests":{"type":"array","items":{"type":"object","properties":{"query":{"type":"string"},"count":{"type":"integer","default":10}}}}}});
        assert_eq!(
            build_skill_input(&command, &schema).ok().unwrap(),
            json!({"requests":[{"query":"Rust privacy","count":3}]})
        );
    }
    #[test]
    fn supported_handler_never_silently_drops_unported_flags() {
        let command = invocation(
            &["projects", "update"],
            &[("icon", json!("unported-icon"))],
            &[],
        );
        assert!(flags(&command, &["name", "description"]).is_err());
    }
}

#[cfg(test)]
#[path = "saved_read_recovery_tests.rs"]
mod saved_read_recovery_tests;

fn paginated_list_output(
    invocation: &Invocation,
    command: &str,
    mut items: Vec<Item>,
) -> Result<CliOutput, CliError> {
    if let Some(filter) = invocation.text("status") {
        status(filter)?;
        items.retain(|item| item.status == filter);
    }
    let limit = number(
        invocation,
        "limit",
        if command == "chats" { 10 } else { 1000 },
        10000,
    )?;
    let page = number(invocation, "page", 1, 100000)?;
    let start = (page - 1)
        .checked_mul(limit)
        .ok_or_else(|| CliError::Invalid("Page offset is too large.".into()))?;
    let items = items
        .into_iter()
        .skip(start)
        .take(limit)
        .collect::<Vec<_>>();
    list_output(invocation, command, items)
}

/// Warm `chats list`: replay the feed from the cached cursor instead of a
/// bounded phased sync. Uncertain recovery state keeps the foreground path.
async fn try_feed_chat_list(
    invocation: &Invocation,
    client: &mut Client,
    context: &ApplicationRecoveryContext<'_>,
    cancel: &CancellationToken,
) -> Result<Option<CliOutput>, CliError> {
    if !crate::session_runtime::same_personal_chat_list_scope(client, invocation) || !client.has_chat_sync_cursor() {
        return Ok(None);
    }
    let admission = RecoveryReadAdmission::capture(client, context.store, cancel)?;
    let pending_or_uncertain =
        match crate::completion_recovery_adapter::load_pending(client, context.store).await {
            Ok(pending) => !pending.is_empty(),
            Err(_) => true,
        };
    if pending_or_uncertain {
        return Ok(None);
    }
    admission.check(client, context.store, cancel)?;
    client.set_operation_cancel(cancel.clone());
    let Some(items) = client.chat_list_from_feed().await? else {
        return Ok(None);
    };
    context.observe_list_stage(ListReadDiagnosticStage::FeedHit);
    let mut output = paginated_list_output(invocation, "chats", items)?;
    persist_saved_read_output(&mut output, client, context, &admission, cancel).await?;
    Ok(Some(output))
}

async fn try_warm_default_list(
    invocation: &Invocation,
    client: &mut Client,
    context: &ApplicationRecoveryContext<'_>,
    cancel: &CancellationToken,
) -> Result<Option<CliOutput>, CliError> {
    if !crate::session_runtime::same_personal_chat_list_scope(client, invocation) {
        return Ok(None);
    }
    let admission = RecoveryReadAdmission::capture(client, context.store, cancel)?;
    // Unknown/malformed local checkpoints must take the existing foreground
    // recovery path. Absence is not inferred from a successful session save.
    context.observe_list_stage(ListReadDiagnosticStage::RecoveryCheckStarted);
    let pending_or_uncertain =
        match crate::completion_recovery_adapter::load_pending(client, context.store).await {
            Ok(pending) => !pending.is_empty(),
            Err(_) => true,
        };
    context.observe_list_stage(ListReadDiagnosticStage::RecoveryChecked { pending_or_uncertain });
    admission.check(client, context.store, cancel)?;
    let Some(items) = client.try_cached_default_chat_list(pending_or_uncertain)? else {
        return Ok(None);
    };
    context.observe_list_stage(ListReadDiagnosticStage::CachedHit);
    let mut output = paginated_list_output(invocation, "chats", items)?;
    persist_saved_read_output(&mut output, client, context, &admission, cancel).await?;
    Ok(Some(output))
}
