//! E2B upload consent for the CLI: plain-text request, TTY prompt, exit code 2
//! when it cannot ask, and `settings e2b-upload`. Policy and calls live in the core.
use super::{CliError, CliOutput, Invocation, terminal_text};
use crate::{client::Client, error::Error};
use openmates_sdk::client::{
    E2B_CONSENT_STATUS_PREFIX, E2bConsentChoice, E2bDecision, SendE2bConsentRequest, SendOutcome,
};
use std::io::{BufRead, IsTerminal, Write};
use tokio::sync::mpsc;

const REQUIRED: &str = "e2b_consent_required";
const DECLINED: &str = "e2b_consent_declined";

/// The consent request text shown before anything is uploaded.
pub(super) fn request_text() -> String {
    "OpenMates needs your permission before it sends your code and files to E2B, a cloud sandbox provider, to run them there.\n\
     Privacy policy: https://openmates.org/privacy\n\
     Alternative: run on your own machine instead (`openmates remote-access`).\n\
     Allow it with --allow-e2b-upload, or set the decision once with `openmates settings e2b-upload allow`.\n\
     Nothing was uploaded.\n"
        .to_owned()
}
/// Text for an account that declined sending files to E2B.
pub(super) fn declined_text() -> String {
    "This account declined sending code and files to E2B, so nothing was uploaded.\n\
     Change it with `openmates settings e2b-upload allow`, or run on your own machine (`openmates remote-access`).\n"
        .to_owned()
}
fn refusal(code: &str) -> CliOutput {
    CliOutput {
        stdout: String::new(),
        stderr: if code == DECLINED {
            declined_text()
        } else {
            request_text()
        },
        exit_code: 2,
    }
}
/// The typed consent refusal inside a send failure, if that is what it is.
pub(super) fn refusal_output(error: &CliError) -> Option<CliOutput> {
    let source = match error {
        CliError::Client(source) | CliError::PendingTurn { source, .. } => source,
        _ => return None,
    };
    source
        .sdk_code()
        .filter(|code| matches!(*code, REQUIRED | DECLINED))
        .map(refusal)
}
/// Parse a prompt answer (`1`/`allow`, `2`/`own`, `3`/`not now`).
pub(super) fn parse_choice(answer: &str) -> Option<E2bConsentChoice> {
    match answer.trim().to_ascii_lowercase().as_str() {
        "1" | "a" | "allow" => Some(E2bConsentChoice::Allow),
        "2" | "o" | "own" | "own machine" | "use my own machine" => {
            Some(E2bConsentChoice::OwnMachine)
        }
        "3" | "n" | "not now" | "no" | "" => Some(E2bConsentChoice::NotNow),
        _ => None,
    }
}
pub(super) fn ask(input: &mut impl BufRead, out: &mut impl Write) -> Option<E2bConsentChoice> {
    let _ = write!(
        out,
        "{}\n  1) Allow\n  2) Use my own machine\n  3) Not now\nChoice [3]: ",
        request_text()
    );
    let _ = out.flush();
    let mut line = String::new();
    input.read_line(&mut line).ok()?;
    parse_choice(&line)
}
/// True when the send may ask the user: a TTY on stdin and stderr, no `--json`,
/// and no `--allow-e2b-upload` (which already answers for the caller).
pub(super) fn can_prompt(invocation: &Invocation) -> bool {
    !invocation.boolean("json")
        && !invocation.boolean("allow-e2b-upload")
        && std::io::stdin().is_terminal()
        && std::io::stderr().is_terminal()
}
/// Hand the core a channel for mid-send answers when this run can prompt; the
/// returned sender goes to the stream presenter, which feeds it from [`prompt`].
pub(super) fn attach(
    client: &mut Client,
    invocation: &Invocation,
) -> Option<mpsc::UnboundedSender<(String, E2bConsentChoice)>> {
    if !can_prompt(invocation) {
        return None;
    }
    let (sender, receiver) = mpsc::unbounded_channel();
    client.set_e2b_consent_receiver(receiver);
    Some(sender)
}
/// Ask for the request in a status event off the async runtime and send the
/// choice into the core's channel, so the paused turn continues in this send.
/// An unreadable or invalid answer is treated as "Not now".
pub(super) fn prompt(status: &str, sender: &mpsc::UnboundedSender<(String, E2bConsentChoice)>) {
    let Some(request) = status
        .strip_prefix(E2B_CONSENT_STATUS_PREFIX)
        .and_then(|json| serde_json::from_str::<SendE2bConsentRequest>(json).ok())
    else {
        return;
    };
    let sender = sender.clone();
    let ask_and_send = move || {
        let choice = ask(&mut std::io::stdin().lock(), &mut std::io::stderr())
            .unwrap_or(E2bConsentChoice::NotNow);
        let _ = sender.send((request.request_id, choice));
    };
    match tokio::runtime::Handle::try_current() {
        Ok(handle) => {
            drop(handle.spawn_blocking(ask_and_send));
        }
        Err(_) => ask_and_send(),
    }
}
/// Requests still pending after a send could not be answered mid-send
/// (non-interactive, or the answer channel closed): refuse with exit code 2.
pub(super) fn settle(outcome: &SendOutcome) -> Option<CliOutput> {
    (!outcome.e2b_consent_requests.is_empty()).then(|| refusal(REQUIRED))
}
pub(super) fn supported(invocation: &Invocation) -> bool {
    invocation.command_path() == "settings e2b-upload"
}
fn render(decision: Option<E2bDecision>) -> &'static str {
    match decision {
        Some(E2bDecision::Allowed) => "allowed",
        Some(E2bDecision::Declined) => "declined",
        None => "not decided",
    }
}
/// `settings e2b-upload [allow|decline]`.
pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
) -> Result<CliOutput, CliError> {
    super::handlers::flags(invocation, &[])?;
    let wanted = match invocation.positionals.as_slice() {
        [] => None,
        [word] if word == "allow" => Some(E2bDecision::Allowed),
        [word] if word == "decline" => Some(E2bDecision::Declined),
        _ => {
            return Err(CliError::Invalid(
                "Usage: openmates settings e2b-upload [allow|decline]".into(),
            ));
        }
    };
    let record = match wanted {
        Some(decision) => client.e2b_consent_set(decision).await,
        None => client.e2b_consent_get().await,
    }
    .map_err(|error: Error| CliError::Client(error))?;
    if invocation.boolean("json") {
        return CliOutput::json(
            &serde_json::json!({"decision": record.decision.map(E2bDecision::as_wire), "decided_at": record.decided_at, "version": record.version}),
        );
    }
    Ok(CliOutput::text(terminal_text(&format!(
        "Sending code and files to E2B: {}\nChange it with `openmates settings e2b-upload allow|decline`.",
        render(record.decision)
    ))))
}
#[cfg(test)]
#[path = "e2b_consent_cmd_tests.rs"]
mod tests;
