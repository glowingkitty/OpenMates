//! CLI adapter that drains the npm CLI's legacy on-disk Task outboxes
//! (`taskMutationDelivery.ts`, `taskActivityDelivery.ts`) into the native
//! encrypted delivery journal. File IO and npm-compatible record locks live
//! here; record validation and intent preparation stay in the shared core
//! (`openmates_sdk::work::Tasks::adopt_npm_*`).
//!
//! Invariant: an npm record is first committed to the native journal and only
//! then marked `rejected` (migrated) in the npm outbox, under npm's own
//! per-record lock, so neither CLI resends it and a crash between the two steps
//! leaves an idempotent duplicate (same delivery id) rather than a loss.
use super::CliError;
use crate::{error::Error, task_delivery::Journal};
use openmates_sdk::work::{LegacyRefusal, Tasks};
use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
    time::{Duration, SystemTime},
};

/// Text npm shows for a migrated record; npm treats `rejected` as terminal.
const MIGRATED: &str = "Migrated to the native OpenMates CLI encrypted task-delivery journal; it is delivered from there.";
/// proper-lockfile `stale` used by every npm Task outbox lock.
const STALE: Duration = Duration::from_secs(240);

/// The account/Team the native session is bound to (npm scope fields).
pub(crate) struct LegacyScope<'a> {
    /// Session API URL; compared by origin like npm's stored `apiUrl`.
    pub(crate) api_url: &'a str,
    /// Account hashed email (npm scope field 2).
    pub(crate) hashed_email: &'a str,
    /// Active Team, or `None` for npm's `"personal"`.
    pub(crate) team: Option<&'a str>,
}

/// Result of one adoption pass.
#[derive(Default, Debug, PartialEq, Eq)]
pub(crate) struct Adoption {
    /// `(delivery id, journal intent)` newly or previously adopted.
    pub(crate) adopted: Vec<(String, String)>,
    /// Records left untouched in the npm outbox, with the refusal code.
    pub(crate) refused: Vec<(String, &'static str)>,
}

/// npm's state directory (`storage.ts resolveStateDir`). An explicit
/// `OPENMATES_STATE_DIR` is ambiguous between the two CLIs and is not adopted.
pub(crate) fn npm_root() -> Option<PathBuf> {
    if std::env::var_os("OPENMATES_STATE_DIR").is_some() {
        return None;
    }
    let base = PathBuf::from(std::env::var_os("HOME")?).join(".openmates");
    match std::env::var("OPENMATES_PROFILE") {
        Ok(profile) if !profile.trim().is_empty() => {
            let profile = profile.trim();
            profile
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
                .then(|| base.join("profiles").join(profile))
        }
        _ => Some(base),
    }
}

fn origin(url: &str) -> Option<String> {
    url::Url::parse(url)
        .ok()
        .map(|url| url.origin().ascii_serialization())
}
fn hex64(id: &str) -> bool {
    id.len() == 64
        && id
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn read_json(path: &Path) -> Result<Value, CliError> {
    let text = fs::read_to_string(path).map_err(|_| CliError::Client(Error::Io))?;
    serde_json::from_str(&text).map_err(|_| CliError::Client(Error::Protocol))
}
/// Same-directory temp file + rename, private mode, like npm `atomicPrivateFile`.
fn write_json(path: &Path, value: &Value) -> Result<(), CliError> {
    let temp = path.with_extension("json.native-tmp");
    let io = |_| CliError::Client(Error::Io);
    {
        use std::io::Write;
        let mut options = fs::OpenOptions::new();
        options.write(true).create(true).truncate(true);
        #[cfg(unix)]
        std::os::unix::fs::OpenOptionsExt::mode(&mut options, 0o600);
        let mut file = options.open(&temp).map_err(io)?;
        file.write_all(value.to_string().as_bytes()).map_err(io)?;
        file.sync_all().map_err(io)?;
    }
    fs::rename(&temp, path).map_err(io)
}

/// npm `lockTaskDeliveryRecord`: proper-lockfile mkdir lock `locks/<id>.lock`.
struct RecordLock(PathBuf);
impl RecordLock {
    fn acquire(directory: &Path, id: &str) -> Result<Option<Self>, CliError> {
        let locks = directory.join("locks");
        fs::create_dir_all(&locks).map_err(|_| CliError::Client(Error::Io))?;
        let lock = locks.join(format!("{id}.lock"));
        for _ in 0..2 {
            match fs::create_dir(&lock) {
                Ok(()) => return Ok(Some(Self(lock))),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                    let stale = fs::metadata(&lock)
                        .and_then(|meta| meta.modified())
                        .ok()
                        .and_then(|time| SystemTime::now().duration_since(time).ok())
                        .is_some_and(|age| age > STALE);
                    if !stale {
                        // An npm process is delivering it now; adopt on a later run.
                        return Ok(None);
                    }
                    let _ = fs::remove_dir(&lock);
                }
                Err(_) => return Err(CliError::Client(Error::Io)),
            }
        }
        Ok(None)
    }
}
impl Drop for RecordLock {
    fn drop(&mut self) {
        let _ = fs::remove_dir(&self.0);
    }
}

fn scopes(root: &Path, kind: &str, scope: &LegacyScope<'_>) -> Vec<(PathBuf, Value)> {
    let Ok(entries) = fs::read_dir(root.join(kind)) else {
        return vec![];
    };
    let want = origin(scope.api_url);
    let team = scope.team.unwrap_or("personal");
    let mut found = entries
        .filter_map(|entry| entry.ok().map(|entry| entry.path()))
        .filter_map(|dir| {
            let parts = read_json(&dir.join("scope.json")).ok()?;
            (want.is_some()
                && origin(parts[0].as_str()?) == want
                && parts[1] == scope.hashed_email
                && parts[2] == team)
                .then_some((dir, parts))
        })
        .collect::<Vec<_>>();
    found.sort_by(|a, b| a.0.cmp(&b.0));
    found
}
fn pending_records(directory: &Path) -> Vec<(String, PathBuf)> {
    let Ok(entries) = fs::read_dir(directory) else {
        return vec![];
    };
    let mut records = entries
        .filter_map(|entry| entry.ok().map(|entry| entry.path()))
        .filter_map(|path| {
            let id = path
                .file_name()?
                .to_str()?
                .strip_suffix(".json")?
                .to_owned();
            hex64(&id).then_some((id, path))
        })
        .collect::<Vec<_>>();
    records.sort();
    records
}
fn migrated(mut record: Value) -> Value {
    if let Some(input) = record["mutation"]["input"].as_object_mut() {
        input.retain(|key, _| !key.starts_with("plaintext_"));
    }
    record["rejected"] = Value::String(MIGRATED.into());
    record
}

/// Adopt every pending npm mutation/Activity record for this account scope.
/// Records already acknowledged or rejected by npm are skipped; refused
/// records stay untouched and are reported.
///
/// # Errors
/// Local journal/key failures; unreadable individual records are refused.
pub(crate) async fn adopt(
    service: &mut Tasks<'_>,
    journal: &Journal,
    root: &Path,
    scope: &LegacyScope<'_>,
) -> Result<Adoption, CliError> {
    let mut adoption = Adoption::default();
    for (directory, _) in scopes(root, "task-mutation-delivery", scope) {
        for (id, path) in pending_records(&directory) {
            let Some(_lock) = RecordLock::acquire(&directory, &id)? else {
                continue;
            };
            let Ok(record) = read_json(&path) else {
                adoption.refused.push((id, LegacyRefusal::Malformed.code()));
                continue;
            };
            if !record["acknowledgement"].is_null() || !record["rejected"].is_null() {
                continue;
            }
            let intent = format!("legacy-npm-task-mutation:{id}");
            match service.adopt_npm_mutation(&record["mutation"], &id).await? {
                Ok(delivery) => {
                    journal
                        .insert_adopted(delivery, intent.clone(), record["uncertain"] == true)
                        .await?;
                    write_json(&path, &migrated(record))?;
                    adoption.adopted.push((id, intent));
                }
                Err(refusal) => adoption.refused.push((id, refusal.code())),
            }
        }
    }
    for (directory, parts) in scopes(root, "task-activity-delivery", scope) {
        let (Some(task_id), Some(actor)) = (parts[3].as_str(), parts[4].as_str()) else {
            continue;
        };
        for (id, path) in pending_records(&directory.join("pending")) {
            let Some(_lock) = RecordLock::acquire(&directory, &id)? else {
                continue;
            };
            let Ok(record) = read_json(&path) else {
                adoption.refused.push((id, LegacyRefusal::Malformed.code()));
                continue;
            };
            if !record["acknowledged"].is_null() || !record["rejected"].is_null() {
                continue;
            }
            let intent = format!("legacy-npm-task-activity:{id}");
            match service
                .adopt_npm_activity(task_id, actor, &record, &id)
                .await?
            {
                Ok(delivery) => {
                    // npm marks a record uncertain only through its retry
                    // state; reconcile first so a lost ack is never doubled.
                    journal
                        .insert_adopted(delivery, intent.clone(), true)
                        .await?;
                    write_json(&path, &migrated(record))?;
                    adoption.adopted.push((id, intent));
                }
                Err(refusal) => adoption.refused.push((id, refusal.code())),
            }
        }
    }
    Ok(adoption)
}

/// Foreground hook for cookie Task commands: adopt the npm outbox of this
/// session's account/Team, then deliver at most three adopted intents before
/// the current command. Outcomes are reported on stderr so stdout/JSON of the
/// current command is unchanged; a failure here never discards npm records.
///
/// # Errors
/// Non-retryable delivery errors of an adopted intent (it stays journaled).
pub(crate) async fn drain(
    client: &mut crate::client::Client,
    journal: &Journal,
    cancel: &tokio_util::sync::CancellationToken,
) -> Result<(), CliError> {
    let Some(root) = npm_root() else {
        return Ok(());
    };
    let Some(session) = client.session() else {
        return Ok(());
    };
    let api_url = session.api_url.clone();
    let hashed_email = session.hashed_email.clone();
    let team = session.active_team_id.clone();
    let filters = openmates_sdk::work::TaskFilters {
        team_id: team.clone(),
        personal: team.is_none(),
        ..Default::default()
    };
    let mut service = client.tasks().with_filters(filters);
    let scope = LegacyScope {
        api_url: &api_url,
        hashed_email: &hashed_email,
        team: team.as_deref(),
    };
    let adoption = adopt(&mut service, journal, &root, &scope).await?;
    let mut notice = String::new();
    for (id, code) in &adoption.refused {
        notice.push_str(&format!(
            "Legacy npm Task delivery {id} was not migrated ({code}); it remains in the npm outbox.\n"
        ));
    }
    let mut delivered = 0usize;
    for (id, intent) in adoption.adopted.iter().take(3) {
        match super::task_queue::dispatch(&mut service, journal, id, intent, cancel).await {
            Ok(_) => delivered += 1,
            Err(error) if super::task_queue::retryable(&error) => break,
            Err(error) => return Err(error),
        }
    }
    if !adoption.adopted.is_empty() {
        notice.push_str(&format!(
            "Migrated {} queued npm Task operation(s) to the native delivery journal; {delivered} delivered.\n",
            adoption.adopted.len()
        ));
    }
    if !notice.is_empty() {
        use std::io::Write;
        let _ = std::io::stderr().write_all(notice.as_bytes());
    }
    Ok(())
}

#[cfg(test)]
#[path = "task_legacy_outbox_tests.rs"]
mod tests;
