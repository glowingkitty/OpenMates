//! Native parity for the npm CLI's utility commands: `update`/`upgrade`,
//! `benchmark prompt-budget compare`, `apps examples`, `finance
//! check-accounts` and the `settings memories` help root. Local commands run
//! before credential storage; `update` performs its own registry read without
//! an account; Finance runs through the authenticated session.
use super::{CliError, CliOutput, Invocation};
use crate::client::Client;

#[path = "utility/examples.rs"]
mod examples;
#[path = "utility/finance.rs"]
mod finance;
#[path = "utility/prompt_budget.rs"]
mod prompt_budget;
#[path = "utility/proton.rs"]
mod proton;
#[path = "utility/revolut.rs"]
mod revolut;
#[path = "utility/self_update.rs"]
mod self_update;

const MEMORIES_HELP: &str = "Memories commands:\n  openmates settings memories list [--app-id <id>] [--item-type <type>] [--json]\n  openmates settings memories types [--app-id <id>] [--json]\n  openmates settings memories create --app-id <id> --item-type <type> --data '<json>'\n  openmates settings memories update --id <id> --app-id <id> --item-type <type> --data '<json>' [--version <n>]\n  openmates settings memories delete --id <entry-id>\n\nExamples:\n  openmates settings memories types --app-id code\n  openmates settings memories list --app-id code\n  openmates settings memories create --app-id code --item-type preferred_tech --data '{\"name\":\"Python\",\"proficiency\":\"advanced\"}'\n  openmates settings memories delete --id <uuid>";

fn local(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        "benchmark prompt-budget compare" | "apps examples" | "settings memories"
    )
}
/// Commands that need no account but do perform a network read.
pub(super) fn is_network_public(i: &Invocation) -> bool {
    self_update::supported(i)
}
pub(super) fn is_public(i: &Invocation) -> bool {
    local(i) || is_network_public(i)
}
/// npm refuses credit-spending benchmark runs without `--confirm-spend-credits`
/// (or `--dry-run`) before any network call. The runners themselves are not
/// ported, so confirmed or dry-run invocations still report unsupported. The refusal is
/// a pre-flight answer from `public`, deliberately not part of `is_public`/`supported`
/// (the catalog keeps these benchmark rows unsupported).
fn spend_refusal(i: &Invocation) -> Option<&'static str> {
    if i.boolean("dry-run") || i.boolean("confirm-spend-credits") {
        return None;
    }
    match i.command_path().as_str() {
        "benchmark model" if !i.positionals.is_empty() => Some(
            "Benchmark runs spend real credits from the logged-in account. Rerun with --confirm-spend-credits, or use --dry-run to preview the plan.",
        ),
        "benchmark prompt-budget" if i.positionals.is_empty() => Some(
            "Prompt-budget benchmark runs spend real credits from the logged-in account. Rerun with --confirm-spend-credits, or use --dry-run to preview the plan.",
        ),
        _ => None,
    }
}
pub(super) fn supported(i: &Invocation) -> bool {
    is_public(i) || finance::supported(i) || revolut::supported(i) || proton::supported(i)
}
/// Synchronous local handlers; run before any credential storage is opened.
pub(super) fn public(i: &Invocation) -> Option<Result<CliOutput, CliError>> {
    if let Some(message) = spend_refusal(i) {
        return Some(Err(CliError::Contract {
            code: "command_failed",
            message: message.into(),
        }));
    }
    if !local(i) {
        return None;
    }
    Some(match i.command_path().as_str() {
        "benchmark prompt-budget compare" => prompt_budget::compare(i),
        "apps examples" => examples::execute(i),
        _ => memories_help(i),
    })
}
fn memories_help(i: &Invocation) -> Result<CliOutput, CliError> {
    match i.positionals.first().map(String::as_str) {
        None | Some("help") => Ok(CliOutput::text(MEMORIES_HELP)),
        Some(action) => Err(CliError::Invalid(format!(
            "Unknown memories action '{action}'. Run 'openmates settings memories help'."
        ))),
    }
}
pub(super) async fn execute_public(i: &Invocation) -> Result<CliOutput, CliError> {
    self_update::execute(i).await
}
pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    if proton::supported(i) {
        return proton::execute(i, client).await;
    }
    if revolut::supported(i) {
        return revolut::execute(i, client).await;
    }
    finance::execute(i, client).await
}

/// `finance check-accounts` under an explicit `--api-key` (CSV statements only).
pub(super) fn finance_key_supported(i: &Invocation) -> bool {
    finance::supported(i)
}
pub(super) async fn execute_finance_key(
    i: &Invocation,
    sdk: &openmates_sdk::sdk::OpenMates,
) -> Result<CliOutput, CliError> {
    finance::execute_key(i, sdk).await
}

/// JavaScript `String(number)` for finite values that fit the JSON artifacts.
pub(super) fn js_number(value: f64) -> String {
    if value.fract() == 0.0 && value.abs() < 1e21 {
        format!("{}", value as i64)
    } else {
        format!("{value}")
    }
}
/// JSON number that serializes like `JSON.stringify` (integers without `.0`).
pub(super) fn json_number(value: f64) -> serde_json::Value {
    if value.fract() == 0.0 && value.abs() < 9.0e15 {
        serde_json::Value::from(value as i64)
    } else {
        serde_json::Number::from_f64(value)
            .map(serde_json::Value::Number)
            .unwrap_or(serde_json::Value::Null)
    }
}

#[cfg(test)]
#[path = "utility/tests.rs"]
mod tests;
