//! `projects settings <project> command stop|command-presets|command-resources`
//! (npm `cli.ts` settings branch). Validation order, contract codes, output
//! and file formats follow npm exactly; reusable logic is
//! `openmates_sdk::remote_command` and `Projects::stop_remote_command`.
//!
//! State directory: the attached-source store (`remote-sources.json`) and the
//! preset/resource grant stores are written and read by the npm
//! `remote-access` runtime, which executes the granted commands and is not
//! ported. Grants must therefore land where that runtime looks, so these
//! commands resolve npm `resolveStateDir`: `OPENMATES_STATE_DIR` (absolute),
//! else `--profile`/`OPENMATES_PROFILE` -> `~/.openmates/profiles/<name>`,
//! else `~/.openmates` -- not the native `~/.openmates-rust` state. The native
//! `--state-dir` option has no npm equivalent and is refused explicitly.
//!
//! Credential grants only ever carry environment variable NAMES; values are
//! never read, stored or printed.
use super::*;
use openmates_sdk::remote_command::{
    RemoteAccessSource, RemoteCommandError, RemoteCommandPermissions, ResourceKind,
    disable_preset_grant, disable_resource_grant, enable_preset_grant, enable_credential_grant, enable_network_grant,
    enable_writable_grant, list_preset_grants, list_remote_access_sources, list_resource_grants,
    load_remote_command_permissions, remote_command_preset_digest, select_remote_command_source,
};
use openmates_sdk::work::REMOTE_COMMAND_FOCUS_INACTIVE;
use std::path::{Path, PathBuf};

const PROFILE_PATTERN_MESSAGE: &str =
    "OPENMATES_PROFILE must contain only lowercase letters, numbers, and hyphens.";

pub(super) async fn execute(
    i: &Invocation,
    service: &mut Projects<'_>,
) -> Result<CliOutput, CliError> {
    match i.path.get(2).map(String::as_str) {
        Some("command") if i.path.get(3).map(String::as_str) == Some("stop") => {
            stop(i, service).await
        }
        Some("command-presets") => presets(i, service).await,
        Some("command-resources") => resources(i, service).await,
        _ => Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "This Project command setting is not ported.".into(),
        }),
    }
}

fn remote(error: RemoteCommandError) -> CliError {
    CliError::Contract {
        code: error.code,
        message: error.message,
    }
}
fn contract(code: &'static str, message: &str) -> CliError {
    CliError::Contract {
        code,
        message: message.into(),
    }
}
/// npm `requiredStringFlag`: trimmed, non-empty, else `Missing <label>.`.
fn required<'a>(value: Option<&'a str>, label: &str) -> Result<&'a str, CliError> {
    value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| CliError::Invalid(format!("Missing {label}.")))
}
async fn project_id(i: &Invocation, service: &mut Projects<'_>) -> Result<String, CliError> {
    let selector = required(
        i.positionals.first().map(String::as_str),
        "Project for 'settings'",
    )?;
    Ok(service.show(selector).await?["project_id"]
        .as_str()
        .ok_or(CliError::Client(Error::Protocol))?
        .to_owned())
}

async fn stop(i: &Invocation, service: &mut Projects<'_>) -> Result<CliOutput, CliError> {
    check(i, &["chat"])?;
    let project_id = project_id(i, service).await?;
    let execution_id = required(i.positionals.get(1).map(String::as_str), "execution ID")?;
    let chat_target = required(input::text(i, "chat")?, "--chat <chat-id>")?;
    let chat = uuid::Uuid::parse_str(chat_target)
        .ok()
        .filter(|id| id.to_string() == chat_target.to_ascii_lowercase())
        .map(|id| id.to_string())
        .ok_or_else(|| CliError::Unsupported {
            command: i.command_path(),
            reason: "Use the full hyphenated chat UUID. Short IDs, slugs and titles are not ported for this command.".into(),
        })?;
    let result = service
        .stop_remote_command(&project_id, &chat, execution_id)
        .await
        .map_err(|error| match error {
            Error::Invalid(message) if message == REMOTE_COMMAND_FOCUS_INACTIVE => {
                contract("command_failed", message)
            }
            error => error.into(),
        })?;
    let state = ["state", "status"]
        .iter()
        .map(|key| &result[*key])
        .find(|value| !value.is_null())
        .map(super::super::global_history::js_string)
        .unwrap_or_else(|| "acknowledged".into());
    let text = format!("Command stop requested: {execution_id} ({state})");
    output(i, result, text)
}

/// npm `resolveStateDir` from explicit inputs (see the module comment).
fn resolve_npm_state_dir(
    state_dir: Option<&str>,
    profile: Option<&str>,
    home: Option<&Path>,
) -> Result<PathBuf, CliError> {
    if let Some(state_dir) = state_dir.map(str::trim).filter(|dir| !dir.is_empty()) {
        if !Path::new(state_dir).is_absolute() {
            return Err(CliError::Invalid(
                "OPENMATES_STATE_DIR must be an absolute path.".into(),
            ));
        }
        return Ok(PathBuf::from(state_dir));
    }
    let home = home.ok_or_else(|| {
        CliError::Invalid("The home directory is unavailable; set OPENMATES_STATE_DIR.".into())
    })?;
    let Some(profile) = profile.map(str::trim).filter(|name| !name.is_empty()) else {
        return Ok(home.join(".openmates"));
    };
    let bytes = profile.as_bytes();
    let valid = bytes.len() <= 64
        && (bytes[0].is_ascii_lowercase() || bytes[0].is_ascii_digit())
        && bytes[1..]
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-');
    if !valid {
        return Err(CliError::Invalid(PROFILE_PATTERN_MESSAGE.into()));
    }
    Ok(home.join(".openmates").join("profiles").join(profile))
}
fn npm_state_dir(i: &Invocation) -> Result<PathBuf, CliError> {
    if i.has("state-dir") {
        return Err(CliError::Unsupported {
            command: i.command_path(),
            reason: "--state-dir selects native CLI state; Project command grants live in the npm remote-access state. Use OPENMATES_STATE_DIR or --profile.".into(),
        });
    }
    let env = |key: &str| std::env::var(key).ok();
    let state_dir = env("OPENMATES_STATE_DIR");
    let profile = match input::text(i, "profile")? {
        Some(profile) => Some(profile.to_owned()),
        None => env("OPENMATES_PROFILE"),
    };
    let home = std::env::var_os("HOME")
        .filter(|home| !home.is_empty())
        .map(PathBuf::from);
    resolve_npm_state_dir(state_dir.as_deref(), profile.as_deref(), home.as_deref())
}

/// The selected attached source and its permissions definition.
struct SelectedSource {
    state_dir: PathBuf,
    project_id: String,
    source: RemoteAccessSource,
    permissions: RemoteCommandPermissions,
}
async fn select_source(
    i: &Invocation,
    service: &mut Projects<'_>,
    missing_code: &'static str,
) -> Result<SelectedSource, CliError> {
    let state_dir = npm_state_dir(i)?;
    let project_id = project_id(i, service).await?;
    let sources = list_remote_access_sources(&state_dir).map_err(remote)?;
    let source = select_remote_command_source(
        sources,
        &project_id,
        input::text(i, "source")?,
        input::text(i, "path")?,
    )
    .map_err(remote)?;
    let permissions = load_remote_command_permissions(Path::new(&source.root_path))
        .map_err(remote)?
        .ok_or_else(|| {
            contract(
                missing_code,
                "This source has no .openmates/permissions.yml file.",
            )
        })?;
    Ok(SelectedSource {
        state_dir,
        project_id,
        source,
        permissions,
    })
}
/// `console.log` per line; no lines prints nothing.
fn lines_output(i: &Invocation, value: Value, lines: Vec<String>) -> Result<CliOutput, CliError> {
    if lines.is_empty() && !i.boolean("json") {
        return Ok(CliOutput {
            stdout: String::new(),
            stderr: String::new(),
            exit_code: 0,
        });
    }
    output(i, value, lines.join("\n"))
}
fn state(enabled: bool) -> &'static str {
    if enabled { "enabled" } else { "disabled" }
}

async fn presets(i: &Invocation, service: &mut Projects<'_>) -> Result<CliOutput, CliError> {
    check(i, &["source", "path"])?;
    let action = i.path.get(3).map(String::as_str).unwrap_or("list");
    let selected = select_source(i, service, "command_presets_missing").await?;
    let SelectedSource {
        state_dir,
        project_id,
        source,
        permissions,
    } = &selected;
    if action == "list" {
        let active = list_preset_grants(state_dir)
            .map_err(remote)?
            .into_iter()
            .filter(|grant| &grant.project_id == project_id)
            .collect::<Vec<_>>();
        let mut presets = vec![];
        let mut lines = vec![];
        for preset in &permissions.presets {
            let digest = remote_command_preset_digest(permissions, &preset.id).map_err(remote)?;
            let enabled = active
                .iter()
                .any(|grant| grant.preset_id == preset.id && grant.definition_digest == digest);
            lines.push(format!(
                "{}  {}  {}",
                state(enabled),
                preset.id,
                preset.label
            ));
            presets.push(json!({"id":preset.id,"label":preset.label,"enabled":enabled,"definition_digest":digest}));
        }
        return lines_output(
            i,
            json!({"project_id":project_id,"source_id":source.source_id,"presets":presets}),
            lines,
        );
    }
    let preset_id = required(i.positionals.get(1).map(String::as_str), "preset ID")?;
    match action {
        // npm verifies host command protection (bubblewrap/AppArmor) before
        // writing the grant; a grant without it must not be written.
        "enable" => {
            super::command_protection::ensure(super::command_protection::inspect())?;
            let grant = enable_preset_grant(state_dir, project_id, Path::new(&source.root_path), preset_id)
                .map_err(remote)?;
            output(
                i,
                json!({"project_id":project_id,"source_id":source.source_id,"grant":grant}),
                format!("Command preset enabled: {preset_id}"),
            )
        }
        "disable" => {
            disable_preset_grant(state_dir, project_id, preset_id).map_err(remote)?;
            output(
                i,
                json!({"project_id":project_id,"source_id":source.source_id,"preset_id":preset_id,"enabled":false}),
                format!("Command preset disabled: {preset_id}"),
            )
        }
        _ => Err(contract(
            "invalid_command_preset_action",
            "Use command-presets list|enable|disable.",
        )),
    }
}

/// JavaScript names `result[target]` finds on `Object.prototype`, which npm
/// therefore rejects as duplicate targets.
const OBJECT_PROTOTYPE_NAMES: &[&str] = &[
    "constructor",
    "__proto__",
    "hasOwnProperty",
    "isPrototypeOf",
    "propertyIsEnumerable",
    "toLocaleString",
    "toString",
    "valueOf",
    "__defineGetter__",
    "__defineSetter__",
    "__lookupGetter__",
    "__lookupSetter__",
];
/// npm `parseCredentialEnvironmentMappings`: `TARGET=LOCAL_ENV,...` names only.
fn parse_environment_mappings(value: &str) -> Result<Vec<(String, String)>, CliError> {
    let invalid = || {
        contract(
            "invalid_environment_mapping",
            "--environment must be a comma-separated TARGET=LOCAL_ENV mapping.",
        )
    };
    let mut result: Vec<(String, String)> = vec![];
    for entry in value.split(',') {
        let parts = entry.split('=').map(str::trim).collect::<Vec<_>>();
        let (target, local) = match parts.as_slice() {
            [target, local] => (*target, *local),
            _ => return Err(invalid()),
        };
        if target.is_empty()
            || local.is_empty()
            || OBJECT_PROTOTYPE_NAMES.contains(&target)
            || result.iter().any(|(existing, _)| existing == target)
        {
            return Err(invalid());
        }
        result.push((target.to_owned(), local.to_owned()));
    }
    Ok(result)
}

fn resource_list(selected: &SelectedSource) -> Result<(Value, Vec<String>), CliError> {
    let grants = list_resource_grants(
        &selected.state_dir,
        Some(&selected.project_id),
        Some(&selected.source.source_id),
    )
    .map_err(remote)?;
    let enabled = |kind: &str, id: &str| {
        grants
            .iter()
            .any(|grant| grant["kind"] == kind && grant["profile_id"] == id)
    };
    let profiles = &selected.permissions.resource_profiles;
    let mut lines = vec![];
    let mut line = |kind: &str, id: &str, on: bool| {
        lines.push(format!("{}  {kind}  {id}", state(on)));
    };
    let mut writable = vec![];
    for item in &profiles.writable {
        let on = enabled("writable", &item.id);
        line("writable", &item.id, on);
        writable.push(json!({"id":item.id,"purpose":item.purpose,"enabled":on}));
    }
    let mut network = vec![];
    for item in &profiles.network {
        let on = enabled("network", &item.id);
        line("network", &item.id, on);
        network.push(json!({"id":item.id,"destinations":item.destinations,"enabled":on}));
    }
    let mut credentials = vec![];
    for item in &profiles.credentials {
        let on = enabled("credential", &item.id);
        line("credentials", &item.id, on);
        credentials.push(json!({"id":item.id,"environment":item.environment,"enabled":on}));
    }
    Ok((
        json!({
            "project_id": selected.project_id,
            "source_id": selected.source.source_id,
            "resources": {"writable": writable, "network": network, "credentials": credentials},
        }),
        lines,
    ))
}

async fn resources(i: &Invocation, service: &mut Projects<'_>) -> Result<CliOutput, CliError> {
    check(i, &["source", "path", "host-path", "environment"])?;
    let action = i.path.get(3).map(String::as_str).unwrap_or("list");
    let selected = select_source(i, service, "command_resources_missing").await?;
    if action == "list" {
        let (value, lines) = resource_list(&selected)?;
        return lines_output(i, value, lines);
    }
    let kind_name = required(i.path.get(4).map(String::as_str), "resource kind")?;
    let kind = ResourceKind::parse(kind_name).ok_or_else(|| {
        contract(
            "invalid_command_resource_kind",
            "Resource kind must be writable, network, or credential.",
        )
    })?;
    let profile_id = required(i.positionals.get(1).map(String::as_str), "profile ID")?;
    let SelectedSource {
        state_dir,
        project_id,
        source,
        permissions,
    } = &selected;
    let source_id = source.source_id.as_str();
    let result = match (action, kind) {
        ("disable", _) => {
            disable_resource_grant(state_dir, project_id, source_id, kind, profile_id)
        }
        ("enable", ResourceKind::Writable) => {
            let host_path = required(
                input::text(i, "host-path")?,
                "--host-path <absolute-folder>",
            )?;
            enable_writable_grant(
                state_dir,
                project_id,
                source_id,
                Path::new(&source.root_path),
                permissions,
                profile_id,
                host_path,
            )
        }
        ("enable", ResourceKind::Network) => {
            enable_network_grant(state_dir, project_id, source_id, permissions, profile_id)
        }
        ("enable", ResourceKind::Credential) => {
            let mappings = parse_environment_mappings(required(
                input::text(i, "environment")?,
                "--environment TARGET=LOCAL_ENV,...",
            )?)?;
            enable_credential_grant(
                state_dir,
                project_id,
                source_id,
                permissions,
                profile_id,
                &mappings,
            )
        }
        _ => {
            return Err(contract(
                "invalid_command_resource_action",
                "Use command-resources list|enable|disable.",
            ));
        }
    };
    result.map_err(remote)?;
    let enabled = action == "enable";
    output(
        i,
        json!({"project_id":project_id,"source_id":source_id,"kind":kind.as_str(),"profile_id":profile_id,"enabled":enabled}),
        format!(
            "Command {} profile {}: {profile_id}",
            kind.as_str(),
            state(enabled)
        ),
    )
}

#[cfg(test)]
#[path = "command_settings_tests.rs"]
mod tests;
