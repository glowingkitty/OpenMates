//! `openmates teams ...` over the SDK Team operations, mirroring npm
//! handleTeams flags, messages and JSON/text output. Team deletion keeps the
//! interactive 2FA/email verification (codes are never accepted as flags).
//! Declared from account.rs so it shares the account dispatch.
use super::{CliError, CliOutput, Invocation, handlers};
use crate::{client::Client, error::Error};
use openmates_sdk::work::{TeamCreate, TeamInvite, TeamUpdate, generated_profile_image};
use serde_json::{Value, json};

const COMMANDS: &[&str] = &[
    "teams list",
    "teams show",
    "teams switch",
    "teams create",
    "teams update",
    "teams delete",
    "teams invite",
    "teams accept-invite",
    "teams decline-invite",
    "teams access-requests",
    "teams approve-access",
    "teams reject-access",
    "teams role",
    "teams remove-member",
    "teams members list",
    "teams members show",
    "teams member list",
    "teams member show",
    "teams profile show",
    "teams profile get",
    "teams profile edit",
    "teams profile-image generated",
    "teams billing",
    "teams storage",
    "teams storage notice",
    "teams usage",
    "teams add-credits",
];
pub(super) fn supported(i: &Invocation) -> bool {
    COMMANDS.contains(&i.command_path().as_str())
}
fn text(stdout: String) -> CliOutput {
    CliOutput {
        stdout,
        stderr: String::new(),
        exit_code: 0,
    }
}
/// Legacy requiredStringFlag message.
fn required<'a>(value: Option<&'a str>, label: &str) -> Result<&'a str, CliError> {
    value
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .ok_or_else(|| CliError::Invalid(format!("Missing {label}.")))
}
fn positional(i: &Invocation, index: usize) -> Option<&str> {
    i.positionals.get(index).map(String::as_str)
}
/// Legacy requireTeamId: --team/--team-id or the first positional.
fn team_id(i: &Invocation) -> Result<&str, CliError> {
    required(i.text("team-id").or(positional(i, 0)), "--team <team-id>")
}
fn id(team: &Value) -> &str {
    team["team_id"]
        .as_str()
        .or(team["id"].as_str())
        .unwrap_or("unknown")
}
/// Legacy printTeamRecord.
fn record(team: &Value, active: Option<&str>) -> String {
    let team_id = id(team);
    let mut out = format!(
        "{}{}\n",
        super::super::terminal_text(team_id),
        if active == Some(team_id) { " *" } else { "" }
    );
    for key in ["slug", "role", "status"] {
        if let Some(value) = team[key].as_str() {
            out.push_str(&format!(
                "  \x1b[2m{key:<16}\x1b[0m {}\n",
                super::super::terminal_text(value)
            ));
        }
    }
    out
}
/// Legacy publicTeamMember.
fn public_member(member: &Value) -> Value {
    json!({"user_id":member["user_id"],"hashed_user_id":member["hashed_user_id"],
        "display_name":member["profile"]["display_name"].as_str().unwrap_or(""),
        "avatar":member["profile"]["avatar"],"role":member["role"],
        "status":member["status"].as_str().unwrap_or(""),"joined_at":member["joined_at"]})
}
fn member_line(member: &Value, with_status: bool) -> String {
    let name = member["display_name"]
        .as_str()
        .filter(|v| !v.is_empty())
        .or(member["user_id"].as_str())
        .unwrap_or("");
    let role = member["role"].as_str().unwrap_or("");
    let line = if with_status {
        let hash = member["hashed_user_id"]
            .as_str()
            .or(member["user_id"].as_str())
            .unwrap_or("");
        format!(
            "{name}  {role}  {}  {hash}",
            member["status"].as_str().unwrap_or("")
        )
    } else {
        format!(
            "{name}  {role}  {}",
            member["user_id"].as_str().unwrap_or("")
        )
    };
    format!("{}\n", super::super::terminal_text(line.trim()))
}
fn pretty(value: &Value) -> Result<CliOutput, CliError> {
    CliOutput::json(value)
}
fn out(i: &Invocation, json_value: Value, human: String) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        CliOutput::json(&json_value)
    } else {
        Ok(text(human))
    }
}
fn role(value: Option<&str>, default_member: bool) -> Result<String, CliError> {
    let role = match value {
        None if default_member => return Ok("member".into()),
        value => required(value, "--role <admin|member|viewer>")?,
    };
    if matches!(role, "admin" | "member" | "viewer") {
        Ok(role.into())
    } else {
        Err(CliError::Invalid(
            "Team role must be admin, member, or viewer.".into(),
        ))
    }
}
/// Legacy parseTeamInviteInput: invite URLs carry the secret in `#key=`.
fn invite_input(value: &str) -> (String, Option<String>) {
    if let Ok(url) = url::Url::parse(value)
        && let Some(id) = url
            .path_segments()
            .and_then(|s| s.filter(|p| !p.is_empty()).last())
    {
        let secret = url
            .fragment()
            .and_then(|f| url::form_urlencoded::parse(f.as_bytes()).find(|(k, _)| k == "key"))
            .map(|(_, v)| v.into_owned());
        return (id.to_owned(), secret);
    }
    (value.to_owned(), None)
}
fn gib(bytes: f64) -> f64 {
    bytes / 1024f64.powi(3)
}
fn iso(seconds: i64) -> String {
    time::OffsetDateTime::from_unix_timestamp(seconds)
        .ok()
        .and_then(|t| {
            t.format(&time::format_description::well_known::Rfc3339)
                .ok()
        })
        .map(|t| {
            if t.ends_with('Z') && !t.contains('.') {
                t.replace('Z', ".000Z")
            } else {
                t
            }
        })
        .unwrap_or_default()
}
/// Legacy printTeamStorageSummary.
fn storage_text(s: &Value) -> String {
    let n = |k: &str| s[k].as_f64().unwrap_or(0.0);
    let mut out = format!(
        "Team storage: {:.2} GiB measured {}\nFree allowance: {:.0} GiB · {} started excess GiB\nWeekly quote: {} team credits ({} per started excess GiB; Sundays at 03:00 UTC)\n",
        gib(n("total_bytes")),
        iso(s["measurement_at"].as_i64().unwrap_or(0)),
        gib(n("free_bytes")),
        s["billable_gib"],
        s["weekly_cost_credits"],
        s["credits_per_started_excess_gib_per_week"]
    );
    out.push_str(match s["billing_status"].as_str() {
        Some("disabled_pending_validation") => {
            "Billing is not yet enabled. This is a price preview, not an invoice.\n"
        }
        Some("unpaid") => "Storage payment is due.\n",
        Some("manual_review") => "Storage payment needs manual review.\n",
        _ => "No storage payment is currently due.\n",
    });
    out
}
/// Legacy printTeamStorageNotice.
fn notice_text(n: &Value) -> String {
    if n["episode_id"].as_str().is_none_or(str::is_empty) {
        return "No active team storage payment notice.\n".into();
    }
    let mut out = format!("Delivered warning rounds: {} / 4\n", n["warning_count"]);
    if let Some(deadline) = n["deadline_at"].as_i64().filter(|d| *d != 0) {
        out.push_str(&format!("Earliest removal deadline: {}\n", iso(deadline)));
    }
    if n["manual_review"] == true {
        out.push_str("Some storage needs manual review and will not be removed automatically.\n");
    }
    out.push_str("Affected units:\n");
    for unit in n["units"].as_array().into_iter().flatten() {
        out.push_str(&format!(
            "  {} · {:.1} MiB · oldest {}\n",
            unit["kind"].as_str().unwrap_or("").replace('_', " "),
            unit["bytes"].as_f64().unwrap_or(0.0) / 1024f64.powi(2),
            iso(unit["oldest_at"].as_i64().unwrap_or(0))
        ));
    }
    if n["has_more"] == true {
        out.push_str(&format!(
            "More affected units available. Next cursor: {}\n",
            n["next_after_unit_id"].as_str().unwrap_or("unavailable")
        ));
    }
    out
}
fn active(client: &Client) -> Option<String> {
    client.session().and_then(|s| s.active_team_id.clone())
}
/// Legacy promptLine: the question on stdout, one stdin line back.
async fn line(question: &str) -> Result<String, CliError> {
    use std::io::Write;
    let mut stdout = std::io::stdout();
    write!(stdout, "{question}")
        .and_then(|()| stdout.flush())
        .map_err(|_| CliError::Client(Error::Io))?;
    let answer = tokio::task::spawn_blocking(|| {
        let mut line = String::new();
        std::io::stdin().read_line(&mut line).map(|_| line)
    })
    .await
    .map_err(|_| CliError::Client(Error::Io))?
    .map_err(|_| CliError::Client(Error::Io))?;
    Ok(answer.trim_end_matches(['\r', '\n']).to_owned())
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    // npm requireTeamId: `--team <team-id>` selects the Team before positionals.
    if let Some(normalized) = team_flag_selector(i) {
        return Box::pin(execute(&normalized, client)).await;
    }
    if matches!(i.command_path().as_str(), "teams list" | "teams show") {
        return list_or_show_published(i, client).await;
    }
    let command = i.command_path();
    let allowed: &[&str] = match command.as_str() {
        "teams create" => &["name", "description", "slug", "switch", "activate"],
        "teams update" => &["name", "description", "slug", "team-id"],
        "teams delete" => &["yes", "confirm", "team-id", "email-code", "totp-code"],
        "teams invite" => &[
            "email",
            "user",
            "role",
            "encrypted-recipient-hint",
            "expires-at",
            "team-id",
        ],
        "teams accept-invite" => &["email", "key", "invite"],
        "teams decline-invite" => &["email", "invite"],
        "teams access-requests" => &["status", "team-id"],
        "teams approve-access" => &["encrypted-team-key", "request", "access-request", "team-id"],
        "teams reject-access" => &["request", "access-request", "team-id"],
        "teams role" => &["user", "role", "team-id"],
        "teams remove-member" => &["user", "team-id"],
        "teams profile edit" => &["name", "avatar"],
        "teams profile-image generated" => &[
            "icon",
            "icon-name",
            "background",
            "background-color",
            "team-id",
        ],
        "teams storage notice" => &["limit", "after-unit-id", "team-id"],
        "teams usage" => &["user", "team-id"],
        _ => &["team-id"],
    };
    handlers::flags(i, allowed)?;
    let current = active(client);
    match command.as_str() {
        "teams add-credits" => Err(CliError::Invalid("Direct team credit grants are disabled. Use 'openmates teams billing bank-transfer create <team-id> --credits <amount>'.".into())),
        "teams list" => {
            let teams = client.teams().list().await?;
            let human = if teams.is_empty() {
                "No teams.\n".to_owned()
            } else {
                teams.iter().map(|t| record(t, current.as_deref())).collect()
            };
            out(i, json!({"teams":teams,"active_team_id":current}), human)
        }
        "teams show" => {
            let team = client.teams().get(team_id(i)?).await?;
            let human = record(&team, current.as_deref());
            out(i, json!({"team":team,"active_team_id":current}), human)
        }
        "teams switch" => {
            let target = team_id(i)?;
            let teams = client.teams().list().await?;
            let mut matches = teams
                .iter()
                .filter(|t| t["team_id"] == target || t["id"] == target || t["slug"] == target)
                .collect::<Vec<_>>();
            matches.dedup_by_key(|t| id(t).to_owned());
            let team = match matches.as_slice() {
                [team] => (*team).clone(),
                [] => return Err(CliError::Invalid(format!("Team '{target}' was not found. Run 'openmates switch-to' to see available targets."))),
                _ => return Err(CliError::Invalid(format!("Team '{target}' is ambiguous."))),
            };
            let team_id = id(&team).to_owned();
            client.set_team(Some(&team_id))?;
            let label = team["slug"].as_str().filter(|s| !s.is_empty()).unwrap_or(&team_id).to_owned();
            out(i, json!({"active_team_id":team_id,"context":"team","target":target,"team":team}), format!("Active team: {}\n", super::super::terminal_text(&label)))
        }
        "teams create" => {
            let name = required(i.text("name"), "--name <name>")?;
            let team = client
                .teams()
                .create(TeamCreate { name, description: i.text("description"), slug: i.text("slug") })
                .await?;
            if i.boolean("switch") || i.boolean("activate") {
                if let Some(team_id) = team["team_id"].as_str().or(team["id"].as_str()) {
                    client.set_team(Some(team_id))?;
                }
            }
            let current = active(client);
            let human = record(&team, current.as_deref());
            out(i, json!({"team":team,"active_team_id":current}), human)
        }
        "teams update" => {
            let team_id = team_id(i)?;
            let input = TeamUpdate { name: i.text("name"), description: i.text("description"), slug: i.text("slug"), profile_image: None };
            if input.name.is_none() && input.description.is_none() && input.slug.is_none() {
                return Err(CliError::Invalid("Nothing to update. Provide --name, --description, or --slug.".into()));
            }
            let team = client.teams().update(team_id, input).await?;
            let human = record(&team, current.as_deref());
            out(i, json!({"team":team}), human)
        }
        "teams profile-image generated" => {
            let team_id = team_id(i)?;
            let image = generated_profile_image(
                i.text("icon").or(i.text("icon-name")),
                i.text("background").or(i.text("background-color")),
            );
            let team = client
                .teams()
                .update(team_id, TeamUpdate { profile_image: Some(image), ..Default::default() })
                .await?;
            let human = record(&team, current.as_deref());
            out(i, json!({"team":team}), human)
        }
        "teams delete" => {
            let team_id = team_id(i)?;
            if i.has("email-code") || i.has("totp-code") {
                return Err(CliError::Invalid("Team deletion verification codes must be entered through interactive prompts, not command-line flags.".into()));
            }
            if !i.boolean("yes") && !i.boolean("confirm") {
                return Err(CliError::Invalid("Deleting a team requires --yes.".into()));
            }
            let mut teams = client.teams();
            if teams.auth_methods().await?["has_2fa"] == true {
                let code = line("Enter 2FA code to delete this team: ").await?;
                teams.verify_totp(code.trim()).await?;
            } else {
                teams.request_delete_email_code().await?;
                let code = line("Enter email verification code to delete this team: ").await?;
                teams.verify_delete_email_code(code.trim()).await?;
            }
            let result = teams.delete(team_id).await?;
            if current.as_deref() == Some(team_id) {
                client.set_team(None)?;
            }
            out(i, result, format!("Team deleted: {team_id}\n"))
        }
        "teams invite" => {
            let team_id = team_id(i)?;
            let expires = i.text("expires-at").map(|v| v.trim().parse::<i64>()).transpose()
                .map_err(|_| CliError::Invalid("--expires-at must be a Unix timestamp.".into()))?;
            let role = role(i.text("role"), true)?;
            let invite = client
                .teams()
                .invite(team_id, TeamInvite { email: i.text("email"), user: i.text("user"), role: &role,
                    encrypted_recipient_hint: i.text("encrypted-recipient-hint"), expires_at: expires })
                .await?;
            if i.boolean("json") { pretty(&json!({"invite":invite})) } else { pretty(&invite) }
        }
        "teams accept-invite" => {
            let raw = required(i.text("invite").or(positional(i, 0)), "<invite-id-or-url>")?;
            let (invite, fragment) = invite_input(raw);
            let secret = i.text("key").map(str::to_owned).or(fragment);
            let result = client.teams().accept_invite(&invite, secret.as_deref(), i.text("email")).await?;
            pretty(&result)
        }
        "teams decline-invite" => {
            let invite = required(i.text("invite").or(positional(i, 0)), "<invite-id>")?;
            let result = client.teams().decline_invite(invite, i.text("email")).await?;
            out(i, result, "Team invite declined.\n".into())
        }
        "teams access-requests" => {
            let requests = client.teams().access_requests(team_id(i)?, i.text("status")).await?;
            if i.boolean("json") { pretty(&json!({"access_requests":requests})) } else { pretty(&requests) }
        }
        "teams approve-access" | "teams reject-access" => {
            let team_id = team_id(i)?;
            let request = required(i.text("request").or(i.text("access-request")).or(positional(i, 1)), "<access-request-id>")?;
            if command == "teams approve-access" {
                let membership = client.teams().approve_access(team_id, request, i.text("encrypted-team-key")).await?;
                if i.boolean("json") { pretty(&json!({"membership":membership})) } else { pretty(&membership) }
            } else {
                let result = client.teams().reject_access(team_id, request).await?;
                out(i, result, format!("Team access request rejected: {request}\n"))
            }
        }
        "teams role" => {
            let team_id = team_id(i)?;
            let user = required(i.text("user").or(positional(i, 1)), "--user <user-id>")?;
            let role = role(i.text("role"), false)?;
            let membership = client.teams().set_role(team_id, user, &role).await?;
            if i.boolean("json") { pretty(&json!({"membership":membership})) } else { pretty(&membership) }
        }
        "teams remove-member" => {
            let team_id = team_id(i)?;
            let user = required(i.text("user").or(positional(i, 1)), "--user <user-id>")?;
            let result = client.teams().remove_member(team_id, user).await?;
            out(i, result, format!("Team member removed: {user}\n"))
        }
        "teams members list" | "teams member list" => {
            let team_id = required(positional(i, 0), "<team-id>")?;
            let members = client.teams().members(team_id).await?.iter().map(public_member).collect::<Vec<_>>();
            let human = if members.is_empty() { "No Team members.\n".into() } else { members.iter().map(|m| member_line(m, true)).collect() };
            out(i, json!({"members":members}), human)
        }
        "teams members show" | "teams member show" => {
            let team_id = required(positional(i, 0), "<team-id>")?;
            let user = required(positional(i, 1), "<member-user-id>")?;
            let member = public_member(&client.teams().member(team_id, user).await?);
            let human = member_line(&member, true);
            out(i, json!({"member":member}), human)
        }
        "teams profile show" | "teams profile get" | "teams profile edit" => {
            let team_id = required(positional(i, 0), "<team-id>")?;
            let identity = client.account().profile().await?;
            let own = required(identity["id"].as_str(), "authenticated user ID")?.to_owned();
            let current_member = client.teams().member(team_id, &own).await?;
            if command != "teams profile edit" {
                let member = public_member(&current_member);
                let human = member_line(&member, false);
                return out(i, json!({"member":member}), human);
            }
            if i.text("name").is_none() && i.text("avatar").is_none() {
                return Err(CliError::Invalid("Provide --name or --avatar.".into()));
            }
            let name = i.text("name").or(current_member["profile"]["display_name"].as_str()).unwrap_or("").to_owned();
            let avatar = i.text("avatar").or(current_member["profile"]["avatar"].as_str()).map(str::to_owned);
            let member = public_member(&client.teams().update_own_profile(team_id, &name, avatar.as_deref()).await?);
            let label = member["display_name"].as_str().filter(|n| !n.is_empty()).or(member["user_id"].as_str()).unwrap_or("").to_owned();
            out(i, json!({"member":member}), format!("Team profile saved: {}\n", super::super::terminal_text(&label)))
        }
        "teams billing" => {
            let billing = client.teams().billing(team_id(i)?).await?;
            if i.boolean("json") { pretty(&json!({"billing":billing})) } else { pretty(&billing) }
        }
        "teams storage" => {
            let storage = client.teams().storage(team_id(i)?).await?;
            let human = storage_text(&storage);
            out(i, json!({"storage":storage}), human)
        }
        "teams storage notice" => {
            let team_id = team_id(i)?;
            let limit = match i.text("limit") {
                None => 50,
                Some(raw) => raw.trim().parse::<f64>().ok().filter(|v| v.fract() == 0.0 && (1.0..=100.0).contains(v))
                    .ok_or_else(|| CliError::Invalid("--limit must be an integer from 1 to 100".into()))? as u32,
            };
            let after = i.text("after-unit-id");
            if after.is_some_and(|a| a.len() != 64 || !a.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))) {
                return Err(CliError::Invalid("--after-unit-id must be a 64-character storage unit cursor".into()));
            }
            let notice = client.teams().storage_notice(team_id, limit, after).await?;
            let human = notice_text(&notice);
            out(i, notice, human)
        }
        "teams usage" => {
            let usage = client.teams().usage(team_id(i)?, i.text("user")).await?;
            if i.boolean("json") { pretty(&json!({"usage":usage})) } else { pretty(&usage) }
        }
        _ => Err(CliError::Unsupported { command, reason: "This Team command is not ported.".into() }),
    }
    .map_err(|error| match error {
        CliError::Client(Error::Invalid(message)) => CliError::Invalid(message.into()),
        other => other,
    })
}

#[cfg(test)]
#[path = "teams_tests.rs"]
mod tests;

/// Commands whose npm handler resolves the Team with requireTeamId.
const TEAM_FLAG_COMMANDS: &[&str] = &[
    "teams show",
    "teams switch",
    "teams update",
    "teams delete",
    "teams invite",
    "teams access-requests",
    "teams approve-access",
    "teams reject-access",
    "teams role",
    "teams remove-member",
    "teams profile-image generated",
    "teams billing",
    "teams storage",
    "teams storage notice",
    "teams usage",
];
/// Rewrite `--team <id>` into the leading Team positional (flag precedence).
fn team_flag_selector(i: &Invocation) -> Option<Invocation> {
    if !TEAM_FLAG_COMMANDS.contains(&i.command_path().as_str()) {
        return None;
    }
    let team = i.text("team")?.to_owned();
    let mut normalized = Invocation {
        path: i.path.clone(),
        positionals: i.positionals.clone(),
        flags: i.flags.clone(),
    };
    normalized.flags.remove("team");
    normalized.positionals.insert(0, team);
    Some(normalized)
}
/// npm listTeams/getTeam: publish the Direct-chat identity alongside the read.
async fn list_or_show_published(
    i: &Invocation,
    client: &mut Client,
) -> Result<CliOutput, CliError> {
    handlers::flags(i, &["team-id"])?;
    let current = active(client);
    if i.command_path() == "teams list" {
        let teams = client.teams().list_published().await?;
        let human = if teams.is_empty() {
            "No teams.\n".to_owned()
        } else {
            teams.iter().map(|t| record(t, current.as_deref())).collect()
        };
        return out(i, json!({"teams":teams,"active_team_id":current}), human);
    }
    let team_id = team_id(i)?;
    let mut teams = client.teams();
    teams.ensure_direct_chat_identity().await?;
    let team = teams.get(team_id).await?;
    let human = record(&team, current.as_deref());
    out(i, json!({"team":team,"active_team_id":current}), human)
}

#[cfg(test)]
#[path = "teams_published_tests.rs"]
mod published_tests;
