//! Account commands route through typed, session-authenticated SDK operations.
//! Aliases retain the existing account/settings vocabulary and JSON envelopes.
//! Inputs are explicit; this module never discovers accounts or reads secrets.
//! API-key mutations require explicit confirmation and server-verified strong proof.
//! Other credentials, payments and account destruction retain their dedicated gates.
//! Public support and assistant feedback remain in the existing public handler.
mod billing;
mod export_archive;
mod export_start;
mod memories;
mod notifications;
mod reminders;
mod settings_extra;
mod settings_more;
#[path = "teams.rs"]
mod teams;
#[path = "ideabucket.rs"]
mod ideabucket;
#[path = "teams_billing.rs"]
mod teams_billing;
#[path = "connected_accounts.rs"]
pub(super) mod connected_accounts;

use super::{CliError, CliOutput, Invocation, handlers};
use crate::client::Client;
use openmates_sdk::account::{
    AccountPreference, AccountRead, ApiKeyCreateConfirmation, ApiKeyRevokeConfirmation,
    INTEREST_TAG_IDS,
};
use serde_json::{Value, json};

fn path(invocation: &Invocation) -> String {
    let parts = if invocation
        .path
        .first()
        .is_some_and(|part| part == "settings")
    {
        &invocation.path[1..]
    } else {
        &invocation.path
    };
    parts.join(" ")
}
pub(super) fn supported(invocation: &Invocation) -> bool {
    reminders::supported(invocation)
        || billing::supported(invocation)
        || settings_more::supported(invocation)
        || settings_extra::supported(invocation)
        || export_start::supported(invocation)
        || notifications::supported(invocation)
        || memories::supported(invocation)
        || is_info(invocation)
        || teams::supported(invocation)
        || ideabucket::supported(invocation)
        || connected_accounts::supported(invocation)
        || teams_billing::supported(invocation)
        || matches!(
        path(invocation).as_str(),
        "whoami"
            | "credits"
            | "account info"
            | "account username set"
            | "account timezone set"
            | "account interests list"
            | "account interests set"
            | "account interests clear"
            | "account chats stats"
            | "account storage overview"
            | "account storage files"
            | "interface language set"
            | "interface dark-mode set"
            | "interface font set"
            | "billing overview"
            | "billing usage"
            | "billing usage summaries"
            | "billing usage daily"
            | "billing usage export"
            | "billing usage overview"
            | "billing usage details"
            | "billing usage chat-total"
            | "developers api-keys list"
            | "developers api-keys create"
            | "developers api-keys revoke"
            | "developers devices"
            | "security sessions"
    )
}
fn arguments(invocation: &Invocation, count: usize, allowed: &[&str]) -> Result<(), CliError> {
    handlers::flags(invocation, allowed)?;
    if invocation.positionals.len() != count
        || invocation.positionals.iter().any(|v| v.trim().is_empty())
    {
        return Err(CliError::Invalid(format!(
            "This account command requires {count} value(s)."
        )));
    }
    Ok(())
}
fn required<'a>(invocation: &'a Invocation, name: &str) -> Result<&'a str, CliError> {
    invocation
        .text(name)
        .filter(|v| !v.trim().is_empty())
        .ok_or_else(|| CliError::Invalid(format!("Missing --{name}.")))
}
fn on_off(value: &str) -> Result<bool, CliError> {
    match value {
        "on" | "true" | "1" => Ok(true),
        "off" | "false" | "0" => Ok(false),
        _ => Err(CliError::Invalid("Dark mode must be on or off.".into())),
    }
}
fn credit_text(value: &Value) -> String {
    let context = if value["context"] == "team" {
        format!(
            "team {}",
            value["active_team_id"].as_str().unwrap_or("unknown")
        )
    } else {
        "personal".into()
    };
    let mut text = format!("Credits\n\nContext: {context}");
    let billing = &value["billing"];
    if let Some(balance) = billing
        .get("balance_credits")
        .or_else(|| billing.get("credits"))
        .or_else(|| billing.get("current_credits"))
    {
        text.push_str(&format!("\nAvailable: {balance} credits"));
    } else {
        text.push_str("\nAvailable credits were not included in the API response.");
    }
    if let Some(tier) = billing.get("payment_tier").or_else(|| billing.get("tier")) {
        text.push_str(&format!(
            "\nPayment tier: {}",
            tier.as_str()
                .map(str::to_owned)
                .unwrap_or_else(|| tier.to_string())
        ));
    }
    text
}
fn interests_output(value: Option<Value>) -> Value {
    let mut value =
        value.unwrap_or_else(|| json!({"version":1,"selectedTagIds":[],"updatedAt":null}));
    value["availableTagIds"] = json!(INTEREST_TAG_IDS);
    value
}
fn interests_text(value: &Value, label: Option<&str>) -> String {
    let selected = value["selectedTagIds"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .collect::<Vec<_>>();
    let prefix = label
        .map(|label| format!("✓ {label}\n"))
        .unwrap_or_default();
    format!(
        "{prefix}Selected interests: {}\nAvailable interests: {}",
        if selected.is_empty() {
            "none".into()
        } else {
            selected.join(", ")
        },
        INTEREST_TAG_IDS.join(", ")
    )
}
fn interest_timestamp() -> Result<String, CliError> {
    time::OffsetDateTime::now_utc()
        .format(&time::format_description::well_known::Rfc3339)
        .map_err(|_| CliError::Client(crate::error::Error::Io))
}
/// Legacy SETTINGS_INFO_COMMANDS: (path, description, web section, reason,
/// examples). Informational only, never an SDK operation or approval.
const INFO: &[(&str, &str, Option<&str>, &str, &[&str])] = &[
    ("account email", "Email changes are web-only", Some("account/email"), "Email changes require a guided identity verification flow.", &["openmates settings account email"]),
    ("security", "Security settings are web-only", Some("account/security"), "Security settings require browser APIs or high-risk reauthentication.", &["openmates settings security"]),
    ("security passkeys", "Passkeys are web-only", Some("account/security/passkeys"), "Passkeys require WebAuthn browser APIs.", &["openmates settings security passkeys"]),
    ("security password", "Password changes are web-only", Some("account/security/password"), "The CLI never asks for account credentials.", &["openmates settings security password"]),
    ("security 2fa", "2FA setup and changes are web-only", Some("account/security/2fa"), "2FA setup requires a guided browser verification flow.", &["openmates settings security 2fa"]),
    ("security recovery-key", "Recovery key settings are web-only", Some("account/security/recovery-key"), "Recovery keys are a high-risk account recovery surface.", &["openmates settings security recovery-key"]),
    ("security sessions", "Session management is web-only", Some("account/security/sessions"), "The CLI is a paired restricted session; approval and revocation stay in the browser.", &["openmates settings security sessions"]),
    ("billing buy-credits", "Credit purchase is web-only", Some("billing/buy-credits"), "Payment checkout must use the browser/payment provider UI.", &["openmates settings billing buy-credits"]),
    ("billing gift-card buy", "Gift card purchase is web-only", Some("billing/gift-cards/buy"), "Payment checkout must use the browser/payment provider UI.", &["openmates settings billing gift-card buy"]),
    ("billing auto-topup monthly", "Monthly auto top-up is web-only for now", Some("billing/auto-topup/monthly"), "Recurring payment setup needs a payment-flow audit before CLI support.", &["openmates settings billing auto-topup monthly"]),
    ("privacy personal-data", "Personal data management is not CLI-ready yet", Some("privacy/hide-personal-data"), "The CLI needs a dedicated encrypted personal-data UX before exposing writes.", &["openmates settings privacy personal-data"]),
    ("shared tip", "Tips are web-only", Some("shared/tip"), "Payment checkout must use the browser/payment provider UI.", &["openmates settings shared tip"]),
    ("developers devices", "Developer devices are web-only", Some("developers/devices"), "Device approvals and revocations are sensitive.", &["openmates settings developers devices"]),
    ("developers webhooks", "Developer webhooks are not CLI-ready yet", Some("developers/webhooks"), "Webhook CRUD needs a backend/API audit before CLI support.", &["openmates settings developers webhooks"]),
    ("support", "Support payments are web-only", Some("support"), "Payment flows must use the browser/payment provider UI.", &["openmates settings support"]),
    ("incognito info", "Explain incognito mode", None, "Incognito chats are sent without saving chat history. The CLI stores no incognito transcript.", &["openmates chats incognito \"Private question\""]),
    ("server", "Server admin settings are web/admin-only", Some("server"), "Use `openmates server --help` for self-hosted terminal server management.", &["openmates server status"]),
];
fn info(invocation: &Invocation) -> Option<&'static (&'static str, &'static str, Option<&'static str>, &'static str, &'static [&'static str])> {
    // Only the settings namespace (and the `account email` alias) is
    // informational; top-level `support`/`server` keep their own commands.
    let settings = invocation.path.first().is_some_and(|p| p == "settings");
    let command = path(invocation);
    INFO.iter()
        .find(|entry| entry.0 == command && (settings || command == "account email"))
}
/// Informational settings commands need no credentials or network.
/// Credential-free account commands (npm's signed-out newsletter actions).
pub(super) fn is_public(invocation: &Invocation) -> bool {
    notifications::is_public(invocation)
}
pub(super) async fn execute_public(
    invocation: &Invocation,
    client: &mut Client,
) -> Result<CliOutput, CliError> {
    notifications::execute(invocation, client).await
}
pub(super) fn is_info(invocation: &Invocation) -> bool {
    info(invocation).is_some()
}
/// Browser-only legacy responses are successful informational output, never
/// SDK operations that imply device/session approval or revocation occurred.
pub(super) fn web_only(
    invocation: &Invocation,
    app_url: &str,
) -> Option<Result<CliOutput, CliError>> {
    let (command, description, section, reason, examples) = info(invocation)?;
    Some((|| {
        arguments(invocation, 0, &[])?;
        let web_url = section
            .map(|section| format!("{}/#settings/{section}", app_url.trim_end_matches('/')));
        let mut text = format!("{description}\n\n{reason}");
        if let Some(url) = &web_url {
            text.push_str(&format!("\n\nOpen in web app:\n  {url}"));
        }
        text.push_str(&format!("\n\nExamples:\n  {}", examples.join("\n  ")));
        handlers::output(
            invocation,
            json!({"command":format!("openmates settings {command}"),"supported_in_cli":false,"description":description,"reason":reason,"web_url":web_url,"examples":examples}),
            text,
        )
    })())
}
fn confirmation(invocation: &Invocation, action: &str) -> Result<(), CliError> {
    if !invocation.boolean("yes") {
        return Err(CliError::Invalid(format!("{action} requires --yes.")));
    }
    Ok(())
}
fn api_key_list_text(value: &Value) -> String {
    let Some(keys) = value["api_keys"].as_array().filter(|keys| !keys.is_empty()) else {
        return "No API keys found.".into();
    };
    let text = |key: &Value, field: &str, fallback: &str| {
        key[field]
            .as_str()
            .filter(|v| !v.is_empty())
            .unwrap_or(fallback)
            .to_owned()
    };
    keys.iter().map(|key| {
        let credits = key["credit_limit"]["credits"].as_number().zip(key["credit_limit"]["period"].as_str())
            .map(|(credits,period)| format!("{credits} credits / {period}")).unwrap_or_else(|| "Unlimited credits".into());
        let mut value = format!("{} ({})\n  Prefix: {}\n  Access: {}\n  Created: {}\n  Last used: {}\n  Credit limit: {}",
            text(key,"name","Unnamed API key"),text(key,"id","unknown"),text(key,"key_prefix","sk-api-..."),
            if key["full_access"]==false{"Restricted access"}else{"Full access"},
            text(key,"created_at","Unknown"),text(key,"last_used_at","Never used"),credits);
        let pending = key["pending_device_count"].as_u64().unwrap_or(0);
        if pending>0 {value.push_str(&format!("\n  Confirm device: {pending} pending request{}",if pending==1{""}else{"s"}));}
        value
    }).collect::<Vec<_>>().join("\n")
}
pub(super) async fn execute(
    invocation: &Invocation,
    client: &mut Client,
) -> Result<CliOutput, CliError> {
    if reminders::supported(invocation) {
        return reminders::execute(invocation, client).await;
    }
    if billing::supported(invocation) {
        return billing::execute(invocation, client).await;
    }
    if settings_more::supported(invocation) {
        return settings_more::execute(invocation, client).await;
    }
    if settings_extra::supported(invocation) {
        return settings_extra::execute(invocation, client).await;
    }
    if export_start::supported(invocation) {
        return export_start::execute(invocation, client).await;
    }
    if notifications::supported(invocation) {
        return notifications::execute(invocation, client).await;
    }
    if memories::supported(invocation) {
        return memories::execute(invocation, client).await;
    }
    if teams::supported(invocation) {
        return teams::execute(invocation, client).await;
    }
    if ideabucket::supported(invocation) {
        return ideabucket::execute(invocation, client).await;
    }
    if teams_billing::supported(invocation) {
        return teams_billing::execute(invocation, client).await;
    }
    if connected_accounts::supported(invocation) {
        return connected_accounts::execute(invocation, client).await;
    }
    let command = path(invocation);
    if let Some(result) = web_only(invocation, &client.application_url()) {
        return result;
    }
    let mut account = client.account();
    let mut mutation = false;
    let mut interests_label = None;
    let value = match command.as_str() {
        "developers api-keys list" => {
            arguments(invocation, 0, &[])?;
            serde_json::to_value(account.list_api_keys().await?)
                .map_err(|_| crate::error::Error::Protocol)?
        }
        "developers api-keys create" => {
            arguments(invocation, invocation.positionals.len(), &["name", "yes"])?;
            if invocation.positionals.len() > 1 {
                return Err(CliError::Invalid(
                    "Provide at most one API key name.".into(),
                ));
            }
            confirmation(
                invocation,
                "Creating a full-access API key with unlimited credits and no expiration",
            )?;
            let name = invocation
                .positionals
                .first()
                .map(String::as_str)
                .or_else(|| invocation.text("name"))
                .unwrap_or("CLI API key");
            let result = account
                .create_full_access_api_key(
                    name,
                    ApiKeyCreateConfirmation::FullAccessUnlimitedNoExpiration,
                )
                .await?;
            let mut value =
                serde_json::to_value(&result).map_err(|_| crate::error::Error::Protocol)?;
            let output = if invocation.boolean("json") {
                CliOutput::json(&value)
            } else {
                Ok(CliOutput::text(format!(
                    "! Full access enabled\n! Credit limit: unlimited\n! Expiration: never\n\nAPI key (shown once):\n{}\n\nStore this securely. OpenMates cannot show it again.",
                    result.api_key.as_str()
                )))
            };
            super::erase(&mut value);
            return output;
        }
        "developers api-keys revoke" => {
            arguments(invocation, 1, &["yes"])?;
            confirmation(invocation, "Revoking an API key")?;
            mutation = true;
            account
                .revoke_api_key(&invocation.positionals[0], ApiKeyRevokeConfirmation::Revoke)
                .await?
        }
        "whoami" | "account info" => {
            arguments(invocation, 0, &[])?;
            account.profile().await?
        }
        "credits" => {
            arguments(invocation, 0, &[])?;
            account.credits().await?
        }
        "account interests list" => {
            arguments(invocation, 0, &[])?;
            interests_output(account.interests().await?)
        }
        "account interests set" => {
            arguments(invocation, invocation.positionals.len(), &[])?;
            if invocation.positionals.is_empty() {
                return Err(CliError::Invalid(
                    "Provide one or more canonical interest tag IDs.".into(),
                ));
            }
            let tags = invocation
                .positionals
                .iter()
                .map(String::as_str)
                .collect::<Vec<_>>();
            let timestamp = interest_timestamp()?;
            interests_label = Some("Interests updated");
            interests_output(Some(account.set_interests(&tags, &timestamp).await?))
        }
        "account interests clear" => {
            arguments(invocation, 0, &["yes"])?;
            if !invocation.boolean("yes") {
                return Err(CliError::Invalid(
                    "Clearing account interests requires --yes.".into(),
                ));
            }
            let timestamp = interest_timestamp()?;
            interests_label = Some("Interests cleared");
            interests_output(Some(account.clear_interests(&timestamp).await?))
        }
        "account username set"
        | "account timezone set"
        | "interface language set"
        | "interface dark-mode set"
        | "interface font set" => {
            arguments(invocation, 1, &[])?;
            mutation = true;
            let value = invocation.positionals[0].as_str();
            let preference = match command.as_str() {
                "account username set" => AccountPreference::Username(value),
                "account timezone set" => AccountPreference::Timezone(value),
                "interface language set" => AccountPreference::Language(value),
                "interface dark-mode set" => AccountPreference::DarkMode(on_off(value)?),
                _ => AccountPreference::Font(value),
            };
            account.update(preference).await?
        }
        _ => {
            let operation = match command.as_str() {
                "account chats stats" => {
                    arguments(invocation, 0, &[])?;
                    AccountRead::ChatStats
                }
                "account storage overview" => {
                    arguments(invocation, 0, &[])?;
                    AccountRead::StorageOverview
                }
                "account storage files" => {
                    arguments(invocation, 0, &["category", "type"])?;
                    AccountRead::StorageFiles {
                        category: invocation
                            .text("category")
                            .or_else(|| invocation.text("type")),
                    }
                }
                "billing overview" => {
                    arguments(invocation, 0, &[])?;
                    AccountRead::Billing
                }
                "billing usage" => {
                    arguments(invocation, 0, &[])?;
                    AccountRead::Usage
                }
                "billing usage summaries" => {
                    arguments(invocation, 0, &[])?;
                    AccountRead::UsageSummaries
                }
                "billing usage daily" => {
                    arguments(invocation, 0, &[])?;
                    AccountRead::UsageDaily
                }
                "billing usage export" => {
                    arguments(invocation, 0, &[])?;
                    AccountRead::UsageExport
                }
                "billing usage overview" => {
                    arguments(invocation, 0, &["granularity"])?;
                    AccountRead::UsageOverview {
                        granularity: invocation.text("granularity"),
                    }
                }
                "billing usage details" => {
                    arguments(invocation, 0, &["type", "identifier", "month"])?;
                    AccountRead::UsageDetails {
                        kind: required(invocation, "type")?,
                        identifier: required(invocation, "identifier")?,
                        year_month: required(invocation, "month")?,
                    }
                }
                "billing usage chat-total" => {
                    arguments(invocation, 0, &["chat-id"])?;
                    AccountRead::UsageChatTotal {
                        chat_id: required(invocation, "chat-id")?,
                    }
                }
                _ => return Err(CliError::Unsupported {
                    command: invocation.command_path(),
                    reason:
                        "This account operation requires its dedicated native verification flow."
                            .into(),
                }),
            };
            account.read(operation).await?
        }
    };
    let text = if command.starts_with("account interests ") {
        interests_text(&value, interests_label)
    } else if command == "developers api-keys list" {
        api_key_list_text(&value)
    } else if command == "credits" {
        credit_text(&value)
    } else {
        let text = handlers::display_object(&value);
        if mutation {
            format!("✓ Settings updated\n{text}")
        } else {
            text
        }
    };
    handlers::output(invocation, value, text)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::collections::BTreeMap;
    fn invocation(path: &str, values: &[&str], flags: &[(&str, Value)]) -> Invocation {
        Invocation {
            path: path.split_whitespace().map(str::to_owned).collect(),
            positionals: values.iter().map(|s| (*s).into()).collect(),
            flags: flags
                .iter()
                .map(|(k, v)| ((*k).into(), v.clone()))
                .collect::<BTreeMap<_, _>>(),
        }
    }
    #[test]
    fn aliases_are_exact_and_sensitive_families_remain_closed() {
        for command in [
            "account info",
            "settings account info",
            "settings account username set",
            "credits",
            "settings billing usage details",
            "account interests list",
            "settings account interests set",
            "settings account interests clear",
            "settings developers api-keys list",
            "settings developers api-keys create",
            "settings developers api-keys revoke",
            "settings developers devices",
            "settings security sessions",
            "settings account delete preview",
            "settings memories list",
            "settings billing invoices list",
            "settings security password",
        ] {
            assert!(supported(&invocation(command, &[], &[])), "{command}");
        }
        for command in [
            "account import chatgpt",
            "settings get",
            "signup",
        ] {
            assert!(!supported(&invocation(command, &[], &[])), "{command}");
        }
    }
    #[test]
    fn browser_only_devices_and_sessions_keep_legacy_json_and_success_exit() {
        for (command, description, reason, section) in [
            (
                "developers devices",
                "Developer devices are web-only",
                "Device approvals and revocations are sensitive.",
                "developers/devices",
            ),
            (
                "security sessions",
                "Session management is web-only",
                "The CLI is a paired restricted session; approval and revocation stay in the browser.",
                "account/security/sessions",
            ),
        ] {
            let invocation = invocation(
                &format!("settings {command}"),
                &[],
                &[("json", json!(true))],
            );
            let output = web_only(&invocation, "https://explicit-app.example/")
                .unwrap()
                .unwrap_or_else(|_| panic!("browser-only output failed"));
            assert_eq!(output.exit_code, 0);
            assert!(output.stderr.is_empty());
            let example = format!("openmates settings {command}");
            assert_eq!(
                serde_json::from_str::<Value>(&output.stdout).unwrap(),
                json!({
                    "command":example,"supported_in_cli":false,"description":description,"reason":reason,
                    "web_url":format!("https://explicit-app.example/#settings/{section}"),"examples":[example]
                })
            );
        }
        assert!(web_only(&invocation("credits", &[], &[]), "https://app.example").is_none());
        assert!(
            web_only(
                &invocation("settings security sessions", &["revoke"], &[]),
                "https://app.example"
            )
            .unwrap()
            .is_err()
        );
    }
    #[tokio::test]
    async fn sensitive_api_key_commands_require_explicit_confirmation_before_sdk_io() {
        let mut client = Client::new("https://never-contact.example.invalid", None).unwrap();
        for command in [
            "settings developers api-keys create",
            "settings developers api-keys revoke",
        ] {
            let values: &[&str] = if command.ends_with("revoke") {
                &["d9b5b8f0-b2f2-4ed9-a1b7-c185480cfe16"]
            } else {
                &[]
            };
            assert!(
                matches!(execute(&invocation(command,values,&[]),&mut client).await,Err(CliError::Invalid(message)) if message.contains("--yes"))
            );
        }
        assert!(matches!(
            execute(
                &invocation(
                    "settings developers api-keys create",
                    &["one", "two"],
                    &[("yes", json!(true))]
                ),
                &mut client
            )
            .await,
            Err(CliError::Invalid(_))
        ));
        let output = execute(
            &invocation("settings developers devices", &[], &[("json", json!(true))]),
            &mut client,
        )
        .await
        .unwrap_or_else(|_| panic!("browser-only execution failed"));
        assert_eq!(output.exit_code, 0);
    }
    #[test]
    fn api_key_list_preserves_policy_labels_and_pending_device_visibility() {
        assert_eq!(
            api_key_list_text(&json!({"api_keys":[]})),
            "No API keys found."
        );
        let output = api_key_list_text(
            &json!({"api_keys":[{"id":"key-id","name":"Integration","key_prefix":"sk-api-abcde...","full_access":false,"created_at":"2026-10-22T10:00:00Z","pending_device_count":2,"credit_limit":{"credits":100,"period":"daily"}}]}),
        );
        assert!(output.contains(
            "Integration (key-id)\n  Prefix: sk-api-abcde...\n  Access: Restricted access"
        ));
        assert!(output.contains("Last used: Never used"));
        assert!(output.contains("Credit limit: 100 credits / daily"));
        assert!(output.contains("Confirm device: 2 pending requests"));
    }
    #[test]
    fn flags_and_positionals_never_silently_drop_requested_behavior() {
        assert!(arguments(&invocation("credits", &["ignored"], &[]), 0, &[]).is_err());
        assert!(
            arguments(
                &invocation("account info", &[], &[("force", json!(true))]),
                0,
                &[]
            )
            .is_err()
        );
        assert!(
            arguments(
                &invocation("account info", &[], &[("json", json!(true))]),
                0,
                &[]
            )
            .is_ok()
        );
        assert!(required(&invocation("billing usage details", &[], &[]), "month").is_err());
        assert!(on_off("false").is_ok_and(|value| !value));
        assert!(on_off("sometimes").is_err());
    }
    #[test]
    fn dark_mode_literals_match_legacy_case_sensitive_contract() {
        for (literal, expected) in [
            ("on", true),
            ("true", true),
            ("1", true),
            ("off", false),
            ("false", false),
            ("0", false),
        ] {
            assert!(on_off(literal).is_ok_and(|value| value == expected));
        }
        for literal in [
            "yes", "no", "ON", "OFF", "True", "False", "TRUE", "FALSE", "", " on", "off ",
        ] {
            assert!(matches!(on_off(literal), Err(CliError::Invalid(_))));
        }
    }
    // contract-test: supporting surface=cli assertions=cli.output.actionable-readable
    #[tokio::test]
    async fn invalid_dark_mode_literals_are_rejected_before_authentication_or_network() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let mut client = Client::new(&api, None).unwrap();
        for literal in ["yes", "no", "ON", "OFF", "True", "False", ""] {
            assert!(matches!(
                execute(
                    &invocation("settings interface dark-mode set", &[literal], &[]),
                    &mut client
                )
                .await,
                Err(CliError::Invalid(_))
            ));
        }
        // Accepted literals reach the typed SDK's authentication gate.
        for literal in ["on", "true", "1", "off", "false", "0"] {
            assert!(matches!(
                execute(
                    &invocation("settings interface dark-mode set", &[literal], &[]),
                    &mut client
                )
                .await,
                Err(CliError::Client(crate::error::Error::Authentication))
            ));
        }
        assert!(
            tokio::time::timeout(std::time::Duration::from_millis(20), listener.accept())
                .await
                .is_err()
        );
    }
    #[test]
    fn credits_text_matches_personal_and_team_response_shapes() {
        assert_eq!(
            credit_text(
                &json!({"context":"personal","active_team_id":null,"billing":{"credits":42,"payment_tier":"pay_per_use"}})
            ),
            "Credits\n\nContext: personal\nAvailable: 42 credits\nPayment tier: pay_per_use"
        );
        assert!(credit_text(&json!({"context":"team","active_team_id":"fixture-team","billing":{"balance_credits":9}})).contains("Context: team fixture-team\nAvailable: 9 credits"));
    }
    #[tokio::test]
    async fn invalid_or_destructive_commands_fail_without_network() {
        let mut client = Client::new("https://api.example.invalid", None).unwrap();
        assert!(matches!(
            execute(&invocation("account username set", &[], &[]), &mut client).await,
            Err(CliError::Invalid(_))
        ));
        assert!(matches!(
            execute(
                &invocation("account delete", &[], &[("yes", json!(true)), ("email-code", json!("1"))]),
                &mut client
            )
            .await,
            Err(CliError::Invalid(_))
        ));
        assert!(matches!(
            execute(
                &invocation("account interests clear", &[], &[]),
                &mut client
            )
            .await,
            Err(CliError::Invalid(_))
        ));
        assert!(matches!(
            execute(&invocation("account interests set", &[], &[]), &mut client).await,
            Err(CliError::Invalid(_))
        ));
    }
    #[test]
    fn interests_json_and_human_output_keep_legacy_shape() {
        let absent = interests_output(None);
        assert_eq!(absent["updatedAt"], Value::Null);
        assert_eq!(absent["availableTagIds"], json!(INTEREST_TAG_IDS));
        assert!(interests_text(&absent, None).starts_with(
            "Selected interests: none\nAvailable interests: marketing, software_development"
        ));
        let set = interests_output(Some(
            json!({"version":1,"selectedTagIds":["privacy_personal_data"],"updatedAt":"2026-10-21T10:00:00Z"}),
        ));
        assert!(
            interests_text(&set, Some("Interests updated"))
                .starts_with("✓ Interests updated\nSelected interests: privacy_personal_data")
        );
        assert!(openmates_sdk::account::normalize_interest_tags(&["run_code"]).is_ok());
    }
}
