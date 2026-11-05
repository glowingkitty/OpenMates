//! Native command parser and dispatcher. The migration inventory is the command
//! catalog; an unported operation always fails explicitly, never delegates to npm.
mod account;
mod apps_run;
mod generated_files;
pub use apps_run::execute_sdk_apps;
mod chat_project;
mod chat_work;
mod codex;
mod context;
mod global_history;
mod full_chat_read;
mod drafts;
mod embed_commands;
mod embed_share;
pub use embed_share::execute_admitted as execute_cookie_embed_share_admitted;
pub use embed_commands::{execute_sdk_embeds, execute_sdk_embeds_with_gate, supported as sdk_embeds_supported};
pub use drafts::execute_sdk_drafts;
mod goal_chat;
pub use chat_work::normalize as normalize_chat_work;
pub mod docs;
mod group_help;
mod handlers;
mod mentions_cmd;
#[cfg(test)]
mod parity_test_support;
pub(crate) use handlers::admitted_whoami_output;
pub(crate) use full_chat_read::{is_full_json as is_full_json_show, options as full_chat_read_options};
pub use handlers::{is_direct_apps_command,execute_direct_apps_admitted};
mod history;
mod parity_chat_recovery;
mod parity_extras;
mod parser;
mod plans;
mod projects;
mod send;
pub mod signup;
mod utility;
pub use send::execute_anonymous;
mod task_input;
pub(crate) mod task_queue;
mod tasks;
mod workflows;
pub use global_history::execute_sdk_global_history;
pub use plans::execute_sdk_plans_with_delivery;
pub use projects::execute_sdk_projects_with_delivery;
pub use workflows::execute_sdk_workflows;
pub mod trusted_account;
pub mod private_path;
use crate::error::Error;
pub use handlers::{
    ApplicationRecoveryContext, ListReadDiagnosticStage, execute, execute_public, execute_with_delivery,
    execute_with_foreground_recovery, execute_with_foreground_recovery_admitted, requirements, validate_application_saved_read,
};
/// Existing informational security actions require neither credentials nor a
/// network request. The application supplies its explicit browser target.
pub fn web_only_account(
    invocation: &Invocation,
    application_url: &str,
) -> Option<Result<CliOutput, CliError>> {
    account::web_only(invocation, application_url)
}
pub use parser::{command, parse_from};
use serde::Deserialize;
use serde_json::Value;
use std::{collections::BTreeMap, path::PathBuf, sync::OnceLock};
pub use tasks::{execute_sdk_tasks, execute_sdk_tasks_with_delivery};
use zeroize::{Zeroize, Zeroizing};

pub struct GlobalArgs {
    pub demo: bool,
    pub api_url: Option<String>,
    pub state_dir: Option<PathBuf>,
    pub encrypted_vault: bool,
    pub profile: Option<String>,
    pub json: bool,
    pub api_key: Option<Zeroizing<String>>,
}
pub struct ParsedCli {
    pub globals: GlobalArgs,
    pub invocation: Option<Invocation>,
    pub version_requested: bool,
}
/// Intentionally no Debug: prompts, passcodes and --input may contain private data.
pub struct Invocation {
    pub path: Vec<String>,
    pub positionals: Vec<String>,
    pub flags: BTreeMap<String, Value>,
}
impl Invocation {
    pub fn command_path(&self) -> String {
        self.path.join(" ")
    }
    pub fn text(&self, key: &str) -> Option<&str> {
        self.flags.get(key).and_then(|v| {
            v.as_str()
                .or_else(|| v.as_array().and_then(|a| a.last()).and_then(Value::as_str))
        })
    }
    pub fn boolean(&self, key: &str) -> bool {
        self.flags
            .get(key)
            .is_some_and(|v| v == true || v.as_str() == Some("true"))
    }
    pub fn values(&self, key: &str) -> Vec<&str> {
        match self.flags.get(key) {
            Some(Value::Array(values)) => values.iter().filter_map(Value::as_str).collect(),
            Some(Value::String(value)) => vec![value],
            _ => vec![],
        }
    }
    pub fn has(&self, key: &str) -> bool {
        self.flags.contains_key(key)
    }
}
fn erase(value: &mut Value) {
    match value {
        Value::String(text) => text.zeroize(),
        Value::Array(values) => values.iter_mut().for_each(erase),
        Value::Object(values) => values.values_mut().for_each(erase),
        _ => {}
    }
}
impl Drop for Invocation {
    fn drop(&mut self) {
        self.positionals.zeroize();
        self.flags.values_mut().for_each(erase);
    }
}
pub struct CliOutput {
    pub stdout: String,
    pub stderr: String,
    pub exit_code: u8,
}
impl CliOutput {
    pub fn text(text: impl Into<String>) -> Self {
        let mut stdout = terminal_text(&text.into());
        if !stdout.ends_with('\n') {
            stdout.push('\n');
        }
        Self {
            stdout,
            stderr: String::new(),
            exit_code: 0,
        }
    }
    pub fn json(value: &Value) -> Result<Self, CliError> {
        let mut stdout =
            serde_json::to_string_pretty(value).map_err(|_| CliError::Client(Error::Protocol))?;
        stdout.push('\n');
        Ok(Self {
            stdout,
            stderr: String::new(),
            exit_code: 0,
        })
    }
}
pub enum CliError {
    Invalid(String),
    Contract {
        code: &'static str,
        message: String,
    },
    Unsupported {
        command: String,
        reason: String,
    },
    Client(Error),
    WorkflowWait {
        workflow_id: String,
        accepted_run: Value,
        idempotency_key: String,
        source: Error,
    },
    PendingTask {
        delivery_id: String,
        task_id: String,
        source: Error,
        retry_at: Option<u64>,
        persistent: bool,
    },
    RecoveryRequired {
        chat_id: Option<String>,
        source: Error,
    },
    PendingTurn {
        chat_id: String,
        message_id: String,
        admitted: bool,
        source: Error,
    },
}
/// Wipe owned private diagnostic fields when a restricting output fence fails
/// or its future is dropped. Accepted errors transfer to the normal formatter.
#[doc(hidden)]
pub fn erase_error(error:&mut CliError) {
    match error {
        CliError::Invalid(message)|CliError::Contract{message,..}=>message.zeroize(),
        CliError::Unsupported{command,reason}=>{command.zeroize();reason.zeroize();},
        CliError::WorkflowWait{workflow_id,accepted_run,idempotency_key,..}=>{workflow_id.zeroize();erase(accepted_run);idempotency_key.zeroize();},
        CliError::PendingTask{delivery_id,task_id,..}=>{delivery_id.zeroize();task_id.zeroize();},
        CliError::RecoveryRequired{chat_id,..}=>{if let Some(id)=chat_id{id.zeroize();}},
        CliError::PendingTurn{chat_id,message_id,..}=>{chat_id.zeroize();message_id.zeroize();},
        CliError::Client(_)=>{},
    }
}
fn client_error_code(error: &Error) -> &'static str {
    match error {
        Error::Invalid(_) => "invalid_argument",
        Error::Crypto => "decryption_failed",
        Error::Authentication => "authentication_required",
        Error::TwoFactorRequired => "two_factor_required",
        Error::SignupRequired => "signup_required",
        Error::Unavailable { code, .. } => code,
        Error::Locked => "credential_store_locked",
        Error::Offline => "offline",
        Error::Forbidden => "forbidden",
        Error::Conflict => "conflict",
        Error::Expired => "session_expired",
        Error::Cancelled => "cancelled",
        Error::Io => "local_io_failed",
        Error::Protocol => "invalid_server_response",
    }
}
impl CliError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::Invalid(_) => "invalid_argument",
            Self::Contract { code, .. } => code,
            Self::PendingTask {
                source: Error::Conflict,
                ..
            } => "task_delivery_conflict",
            Self::PendingTask {
                source: Error::Offline | Error::Io | Error::Protocol,
                ..
            } => "task_delivery_pending",
            Self::PendingTask { source, .. } => client_error_code(source),
            Self::Unsupported { .. } => "native_command_unsupported",
            Self::WorkflowWait { .. } => "workflow_wait_failed",
            Self::PendingTurn { .. } | Self::RecoveryRequired { .. } => "turn_recovery_required",
            Self::Client(error) => client_error_code(error),
        }
    }
    pub fn structured_error(&self) -> Value {
        let mut value = serde_json::json!({"error":{"code":self.code(),"message":terminal_text(&self.to_string())}});
        match self {
            Self::WorkflowWait {
                workflow_id,
                accepted_run,
                idempotency_key,
                source,
            } => {
                value["error"]["workflow_id"] = serde_json::json!(workflow_id);
                value["error"]["run_id"] = accepted_run
                    .get("id")
                    .or_else(|| accepted_run.get("run_id"))
                    .cloned()
                    .unwrap_or(Value::Null);
                value["error"]["accepted_run"] = accepted_run.clone();
                value["error"]["idempotency_key"] = serde_json::json!(idempotency_key);
                value["error"]["cause"] = serde_json::json!(client_error_code(source));
            }
            Self::PendingTask {
                delivery_id,
                task_id,
                retry_at,
                persistent,
                ..
            } => {
                value["error"]["delivery_id"] = serde_json::json!(delivery_id);
                value["error"]["task_id"] = serde_json::json!(task_id);
                value["error"]["retry_at"] = serde_json::json!(retry_at);
                value["error"]["persistent"] = serde_json::json!(persistent);
                value["error"]["recovery_required"] = Value::Bool(true);
            }
            Self::Client(Error::Unavailable { reason, .. }) => {
                value["error"]["reason"] = serde_json::json!(reason)
            }
            Self::PendingTurn {
                chat_id,
                message_id,
                admitted,
                ..
            } => {
                value["error"]["chat_id"] = serde_json::json!(chat_id);
                value["error"]["message_id"] = serde_json::json!(message_id);
                value["error"]["admitted"] = serde_json::json!(admitted);
                value["error"]["recovery_required"] = Value::Bool(true);
            }
            Self::RecoveryRequired { chat_id, .. } => {
                value["error"]["chat_id"] = serde_json::json!(chat_id);
                value["error"]["admitted"] = Value::Null;
                value["error"]["recovery_required"] = Value::Bool(true);
            }
            _ => {}
        }
        value
    }
    pub fn exit_code(&self) -> u8 {
        if matches!(
            self,
            Self::Client(Error::Cancelled)
                | Self::WorkflowWait {
                    source: Error::Cancelled,
                    ..
                }
                | Self::PendingTask {
                    source: Error::Cancelled,
                    ..
                }
                | Self::RecoveryRequired {
                    source: Error::Cancelled,
                    ..
                }
                | Self::PendingTurn {
                    source: Error::Cancelled,
                    ..
                }
        ) {
            130
        } else if matches!(self, Self::Invalid(_)) {
            2
        } else {
            1
        }
    }
}
impl std::fmt::Display for CliError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Invalid(message) | Self::Contract { message, .. } => f.write_str(message),
            Self::Client(error) => error.fmt(f),
            Self::WorkflowWait {
                workflow_id,
                accepted_run,
                idempotency_key,
                source,
            } => write!(
                f,
                "{source} Workflow {workflow_id}; accepted run {}. Inspect run-show before retrying; reuse idempotency key {idempotency_key} to avoid rerunning skills.",
                accepted_run["id"]
                    .as_str()
                    .or_else(|| accepted_run["run_id"].as_str())
                    .unwrap_or("unknown")
            ),
            Self::PendingTask {
                delivery_id,
                task_id,
                source: Error::Conflict,
                ..
            } => write!(
                f,
                "The Task changed while delivery was uncertain. The original encrypted operation was preserved. Task ID: {task_id}; delivery ID: {delivery_id}. Review the current Task and retained operation before retrying."
            ),
            Self::PendingTask {
                delivery_id,
                task_id,
                source,
                ..
            } => write!(
                f,
                "{source} The original encrypted Task operation was retained. Task ID: {task_id}; delivery ID: {delivery_id}. Retry the original command with --delivery-id {delivery_id}; do not submit a new mutation."
            ),
            Self::RecoveryRequired { chat_id, source } => write!(
                f,
                "{source} The send outcome is unknown{}. Inspect the chat history before sending again; the turn may already be persisted.",
                chat_id
                    .as_ref()
                    .map(|id| format!(" for chat {id}"))
                    .unwrap_or_default()
            ),
            Self::PendingTurn {
                chat_id,
                message_id,
                admitted,
                source,
            } => write!(
                f,
                "{source} {} User message {message_id} in chat {chat_id}. Inspect the chat history to recover this turn; do not resend it blindly.",
                if *admitted {
                    "The server acknowledged this turn."
                } else {
                    "This turn may already be persisted."
                }
            ),
            Self::Unsupported { command, reason } => write!(
                f,
                "'{command}' is not implemented in the native CLI yet. {reason} The existing TypeScript CLI remains available; no alternate runtime was invoked."
            ),
        }
    }
}
impl From<Error> for CliError {
    fn from(error: Error) -> Self {
        Self::Client(error)
    }
}
pub struct Requirements {
    pub authenticated: bool,
    pub interactive: bool,
    pub supported: bool,
}
#[derive(Deserialize)]
pub(crate) struct Catalog {
    pub commands: Vec<CommandRecord>,
    pub flags: Vec<FlagRecord>,
    pub global_flags: Vec<String>,
    pub family_flags: BTreeMap<String, Vec<String>>,
}
#[derive(Deserialize)]
pub(crate) struct CommandRecord {
    pub path: Vec<String>,
    pub summary: String,
    pub usages: Vec<String>,
    pub flags: Vec<String>,
    pub positionals: Vec<Positional>,
    pub implementation: Implementation,
    #[serde(default)]
    pub skill_schema: Option<Value>,
    #[serde(default)]
    pub app: Option<String>,
    #[serde(default)]
    pub skill: Option<String>,
}
#[derive(Deserialize)]
pub(crate) struct Implementation {
    pub handler: Option<String>,
    pub status: String,
}
#[derive(Deserialize)]
pub(crate) struct Positional {
    pub name: String,
    pub required: bool,
    pub variadic: bool,
    pub at: usize,
}
#[derive(Deserialize)]
pub(crate) struct FlagRecord {
    pub long: String,
    pub arity: String,
    #[serde(default)]
    pub arity_overrides: BTreeMap<String, String>,
    #[serde(default)]
    pub sensitive: bool,
}
pub(crate) fn catalog() -> &'static Catalog {
    static CATALOG: OnceLock<Catalog> = OnceLock::new();
    CATALOG.get_or_init(|| {
        serde_json::from_str(include_str!("../../assets/cli-command-catalog.json"))
            .expect("maintained CLI inventory must be valid")
    })
}
pub(crate) fn record(path: &[String]) -> Option<&'static CommandRecord> {
    catalog().commands.iter().find(|r| r.path == path)
}

/// Render untrusted account/chat text without terminal escapes or bidi overrides.
fn terminal_text(text: &str) -> String {
    let mut result = String::with_capacity(text.len());
    for character in text.chars() {
        if (character.is_control() && !matches!(character, '\n' | '\t'))
            || matches!(character, '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}')
        {
            result.push_str(&format!("\\u{:04x}", character as u32));
        } else {
            result.push(character);
        }
    }
    result
}

#[cfg(test)]
mod catalog_drift_tests;
#[cfg(test)]
mod catalog_tests {
    use super::*;
    use sha2::{Digest, Sha256};
    #[test]
    fn inventory_is_consistent_and_source_snapshots_are_current() {
        let raw: Value =
            serde_json::from_str(include_str!("../../assets/cli-command-catalog.json")).unwrap();
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
        // Preserve the repository audit in checkouts. Extracted Cargo packages
        // have no legacy source tree; their portable input closure is checked
        // by scripts/check_rust_cli_package.py before packaging instead.
        if root.join(".git").exists() || root.join("pnpm-workspace.yaml").is_file() {
            for source in raw["source_snapshots"].as_array().unwrap() {
                let path = source["path"].as_str().unwrap();
                let bytes = std::fs::read(root.join(path)).unwrap();
                assert_eq!(
                    format!("{:x}", Sha256::digest(bytes)),
                    source["sha256"].as_str().unwrap(),
                    "Review the CLI catalog after changing {path}"
                );
            }
        }
        let declared = catalog();
        let unique = declared
            .commands
            .iter()
            .map(|record| record.path.join(" "))
            .collect::<std::collections::BTreeSet<_>>();
        assert_eq!(unique.len(), declared.commands.len());
        assert_eq!(
            raw["coverage"]["command_patterns"],
            serde_json::json!(declared.commands.len())
        );
        assert_eq!(raw["coverage"]["feature_complete"], Value::Bool(false));
        for record in &declared.commands {
            assert!(
                record
                    .flags
                    .iter()
                    .all(|name| declared.flags.iter().any(|flag| &flag.long == name))
            );
        }
    }
    #[test]
    fn human_text_cannot_execute_terminal_controls_and_json_preserves_content() {
        let text = "Title\u{1b}]52;c;private\u{7}\u{202e}\nUnicode 界";
        let output = CliOutput::text(text);
        assert!(!output.stdout.contains('\u{1b}'));
        assert!(output.stdout.contains("\\u001b"));
        let json_output = CliOutput::json(&serde_json::json!({"text":text}))
            .ok()
            .unwrap();
        let value: Value = serde_json::from_str(&json_output.stdout).unwrap();
        assert_eq!(value["text"], text);
    }
}
