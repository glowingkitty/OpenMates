//! `openmates privacy status|disable|remove` (npm runPrivacyCommand). The
//! native CLI has no offline model runtime, so install/enable/update stay
//! unsupported; status reports that honestly, and disable/remove let a user
//! turn off an npm-enabled mode that otherwise blocks native sends.
use super::super::{CliError, CliOutput, Invocation, handlers};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};

pub const LABEL: &str = "Enhanced personal data anonymization (offline AI model)";
const MODEL_REVISION: &str = "935d86882f4b5dc6e0eef05aae48ae5ba0a82a7a";
const MODEL_BYTES: u64 = 1_637_572_192;
const UNSUPPORTED: &str = "The native Rust CLI does not include the offline privacy runtime yet.";

pub(super) fn supported(i: &Invocation) -> bool {
    matches!(
        i.command_path().as_str(),
        "privacy status" | "privacy disable" | "privacy remove"
    )
}
fn fail(message: impl Into<String>) -> CliError {
    CliError::Invalid(message.into())
}
struct Paths {
    native: PathBuf,
    legacy: PathBuf,
    model_dir: PathBuf,
}
fn paths(i: &Invocation) -> Result<Paths, CliError> {
    let home = directories::BaseDirs::new()
        .ok_or(crate::error::Error::Io)?
        .home_dir()
        .to_path_buf();
    let resolved = crate::profile::resolve(
        crate::profile::ProfileOptions {
            profile: i.text("profile").map(str::to_owned),
            state_dir: i.text("state-dir").map(PathBuf::from),
            api_url: None,
        },
        crate::profile::ProfileEnvironment::capture(),
        &home,
    )?;
    let legacy = match &resolved.profile {
        Some(name) => home.join(".openmates/profiles").join(name),
        None => home.join(".openmates"),
    };
    let root = std::env::var_os("OPENMATES_PRIVACY_DIR")
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join(".openmates").join("privacy-model"));
    Ok(Paths {
        native: resolved.state_dir.join("privacy-preferences.json"),
        legacy: legacy.join("privacy-preferences.json"),
        model_dir: root.join(MODEL_REVISION),
    })
}
fn defaults() -> Value {
    json!({"version":1,"enabled":false,"documents":false,"projects":[],"offerSeen":false,"idleSeconds":120})
}
/// Private preference file (0600, owner-only, no symlink) or None when absent.
fn read(path: &Path) -> Result<Option<Value>, CliError> {
    let metadata = match std::fs::symlink_metadata(path) {
        Ok(m) => m,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(fail("Privacy preferences could not be read safely.")),
    };
    if !metadata.is_file() || metadata.len() > 65_536 {
        return Err(fail("Privacy preferences could not be read safely."));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.mode() & 0o077 != 0 || metadata.uid() != rustix::process::getuid().as_raw() {
            return Err(fail("Privacy preferences must be private to this account."));
        }
    }
    let raw = std::fs::read_to_string(path).map_err(|_| fail("Invalid privacy preferences."))?;
    let value: Value =
        serde_json::from_str(&raw).map_err(|_| fail("Invalid privacy preferences."))?;
    if value["version"] != 1
        || !value["enabled"].is_boolean()
        || !value["documents"].is_boolean()
        || !value["projects"].is_array()
    {
        return Err(fail("Invalid privacy preferences."));
    }
    let mut merged = defaults();
    for (key, field) in value.as_object().into_iter().flatten() {
        merged[key] = field.clone();
    }
    Ok(Some(merged))
}
fn write(path: &Path, value: &Value) -> Result<(), CliError> {
    let directory = path.parent().ok_or(crate::error::Error::Io)?;
    std::fs::create_dir_all(directory).map_err(|_| crate::error::Error::Io)?;
    let temporary = directory.join(format!("privacy-preferences.json.{}", uuid::Uuid::new_v4()));
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
        options.mode(0o600);
        let _ = std::fs::set_permissions(directory, std::fs::Permissions::from_mode(0o700));
    }
    {
        use std::io::Write;
        let mut file = options
            .open(&temporary)
            .map_err(|_| crate::error::Error::Io)?;
        file.write_all(format!("{value}\n").as_bytes())
            .and_then(|()| file.sync_all())
            .map_err(|_| crate::error::Error::Io)?;
    }
    std::fs::rename(&temporary, path).map_err(|_| {
        let _ = std::fs::remove_file(&temporary);
        CliError::Client(crate::error::Error::Io)
    })
}
/// Apply a change to the native file and to an existing npm-profile file.
fn update(paths: &Paths, change: impl Fn(&mut Value)) -> Result<(), CliError> {
    let mut native = read(&paths.native)?.unwrap_or_else(defaults);
    change(&mut native);
    write(&paths.native, &native)?;
    if paths.legacy != paths.native
        && let Some(mut legacy) = read(&paths.legacy)?
    {
        change(&mut legacy);
        write(&paths.legacy, &legacy)?;
    }
    Ok(())
}
fn status(paths: &Paths) -> Result<Value, CliError> {
    let preferences = match read(&paths.native)? {
        Some(value) => value,
        None => read(&paths.legacy)?.unwrap_or_else(defaults),
    };
    let model = paths.model_dir.join("model.gguf");
    let installed =
        std::fs::symlink_metadata(&model).is_ok_and(|m| m.is_file() && m.len() == MODEL_BYTES);
    let enabled = preferences["enabled"] == true;
    Ok(
        json!({"feature":LABEL,"state":"unsupported","reason":UNSUPPORTED,"model_bytes":MODEL_BYTES,
        "memory_gib":2,"local_only":true,"messages":enabled,"documents":enabled && preferences["documents"] == true,
        "projects":preferences["projects"],"installed":installed,"idle_seconds":preferences["idleSeconds"],"worker":"stopped"}),
    )
}

pub(super) fn execute(i: &Invocation) -> Result<CliOutput, CliError> {
    let command = i.command_path();
    let allowed: &[&str] = match command.as_str() {
        "privacy disable" => &["documents", "project"],
        "privacy remove" => &["yes"],
        _ => &[],
    };
    handlers::flags(i, allowed)?;
    if let Some(project) = i.text("project")
        && (project.len() != 36 || uuid::Uuid::parse_str(project).is_err())
    {
        return Err(fail(
            "Use the full Project ID for its local privacy setting.",
        ));
    }
    execute_with(i, &paths(i)?)
}
/// The command against explicit preference/model locations.
fn execute_with(i: &Invocation, paths: &Paths) -> Result<CliOutput, CliError> {
    let command = i.command_path();
    let text = match command.as_str() {
        "privacy status" => {
            let value = status(paths)?;
            if i.boolean("json") {
                return CliOutput::json(&value);
            }
            format!(
                "{LABEL}\nState: {} · worker: {}\nMessages: {} · documents: {}\nEnhanced Projects: {}\n{}",
                value["state"].as_str().unwrap_or(""),
                value["worker"].as_str().unwrap_or(""),
                if value["messages"] == true {
                    "on"
                } else {
                    "off"
                },
                if value["documents"] == true {
                    "on"
                } else {
                    "off"
                },
                value["projects"].as_array().map_or(0, Vec::len),
                UNSUPPORTED
            )
        }
        "privacy disable" => {
            let documents = i.boolean("documents");
            let project = i.text("project").map(str::to_owned);
            update(paths, |p| {
                if documents {
                    p["documents"] = json!(false);
                } else if let Some(project) = &project {
                    let kept = p["projects"]
                        .as_array()
                        .cloned()
                        .unwrap_or_default()
                        .into_iter()
                        .filter(|id| id != project)
                        .collect::<Vec<_>>();
                    p["projects"] = json!(kept);
                } else {
                    p["enabled"] = json!(false);
                }
            })?;
            format!(
                "{} enhanced scanning disabled. Existing deterministic detection remains available.",
                if documents {
                    "Document"
                } else if project.is_some() {
                    "Project"
                } else {
                    "Message"
                }
            )
        }
        "privacy remove" => {
            if !i.boolean("yes") {
                use std::io::IsTerminal;
                if !std::io::stdin().is_terminal() || !std::io::stdout().is_terminal() {
                    return Err(fail("This explicit operation requires --yes in scripts."));
                }
                print!(
                    "Remove the offline model from this device? This affects all CLI profiles using it. [y/N] "
                );
                use std::io::Write;
                let _ = std::io::stdout().flush();
                let mut answer = String::new();
                std::io::stdin()
                    .read_line(&mut answer)
                    .map_err(|_| crate::error::Error::Io)?;
                let answer = answer.trim().to_lowercase();
                if answer != "y" && answer != "yes" {
                    return Err(fail("Cancelled. Existing privacy settings are unchanged."));
                }
            }
            update(paths, |p| p["enabled"] = json!(false))?;
            match std::fs::remove_dir_all(&paths.model_dir) {
                Ok(()) => {}
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                Err(_) => return Err(crate::error::Error::Io.into()),
            }
            "Offline model removed. Existing deterministic detection remains available.".into()
        }
        _ => {
            return Err(CliError::Unsupported {
                command,
                reason: UNSUPPORTED.into(),
            });
        }
    };
    Ok(CliOutput::text(text))
}

#[cfg(test)]
#[path = "privacy_cmd_tests.rs"]
mod tests;
