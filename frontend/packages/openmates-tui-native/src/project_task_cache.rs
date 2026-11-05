//! Explicit, owner-private plaintext Project Task cache for local Codex readers.
//! Credential storage remains separate. The SDK reducer owns protocol/crypto;
//! this application module owns descriptors, one-writer locking and publication.
//! snapshot.json is the atomic authority; tasks.txt is a recoverable derived view.
use crate::error::{Error, Result};
use fs2::FileExt;
use openmates_sdk::project_task_sync::{
    MAX_BATCH_BYTES, MAX_TASKS, ProjectTaskSync, TaskSyncConnection, TaskSyncEvent, TaskSyncFrame,
    TaskSyncScope, TaskSyncWorkspace,
};
use rustix::fs::{AtFlags, Mode, OFlags};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs::File,
    io::{Read, Write},
    os::unix::fs::MetadataExt,
    path::{Component, Path, PathBuf},
};
use time::{OffsetDateTime, format_description::well_known::Rfc3339};

const MAX_CACHE_BYTES: usize = MAX_BATCH_BYTES + 65536;

#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CacheConnection {
    Connected,
    Reconnecting,
    Stopped,
    Revoked,
}

/// Legacy reader schema. Full titles are retained; only description/activity
/// summaries are shortened. `encrypted` preserves the authenticated wire record.
#[derive(Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CachedTask {
    pub task_id: String,
    pub short_id: String,
    pub title: String,
    pub description: String,
    pub status: Value,
    pub version: Value,
    pub primary_chat_id: Value,
    pub external_chat: Value,
    pub blocked_reason: Value,
    pub blocked_reason_code: Value,
    pub dependencies: Value,
    pub latest_activity: String,
    pub assignee_type: Value,
    pub assignee_identity: Value,
    pub ai_execution_state: Value,
    pub queue_state: Value,
    pub encrypted: Value,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CacheSnapshot {
    pub schema_version: u8,
    pub account_scope: [String; 3],
    pub project_id: String,
    pub cursor: String,
    pub synced_at: String,
    pub connection: CacheConnection,
    pub tasks: Vec<CachedTask>,
    // Existing Python/TS readers ignore this additional field. Native recovery
    // requires it: a copied cache cannot silently select another account/source.
    native_binding: String,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Revocation {
    schema_version: u8,
    native_binding: String,
}

pub struct ProjectTaskCache {
    directory: File,
    _lock: File,
    path: PathBuf,
    scope: TaskSyncScope,
    reducer: Option<ProjectTaskSync>,
    state: CacheSnapshot,
    poisoned: bool,
    #[cfg(test)]
    fail_after_snapshot: bool,
    #[cfg(test)]
    fail_after_revocation_marker: bool,
}
impl ProjectTaskCache {
    /// All identity and key inputs come from the authenticated application.
    /// The caller selects an explicit private cache root; no profile is found.
    /// `hashed_email` preserves the legacy reader's account-scope contract.
    pub fn open(
        root: &Path,
        scope: TaskSyncScope,
        hashed_email: &str,
        project_key: openmates_sdk::crypto::Key,
        now_seconds: u64,
    ) -> Result<Self> {
        let sync = ProjectTaskSync::new(scope.clone(), project_key);
        Self::open_with_sync(root, scope, hashed_email, sync, now_seconds)
    }
    /// The authorized binding supplies a blank reducer. Cache restore decrypts
    /// once; take_sync transfers that same state owner into the socket watch.
    pub fn open_with_sync(
        root: &Path,
        scope: TaskSyncScope,
        hashed_email: &str,
        sync: ProjectTaskSync,
        now_seconds: u64,
    ) -> Result<Self> {
        if sync.snapshot().scope != &scope
            || sync.snapshot().cursor.is_some()
            || !sync.snapshot().tasks.is_empty()
            || sync.snapshot().connection == TaskSyncConnection::Revoked
        {
            return Err(Error::Forbidden);
        }
        timestamp(now_seconds)?;
        if hashed_email.is_empty()
            || hashed_email.len() > 256
            || hashed_email.chars().any(char::is_control)
        {
            return Err(Error::Protocol);
        }
        let context = match scope.workspace() {
            TaskSyncWorkspace::Personal => "personal",
            TaskSyncWorkspace::Team(id) => id,
        };
        let account_scope = [
            scope.api_url().to_owned(),
            hashed_email.to_owned(),
            context.to_owned(),
        ];
        let account_name = hash(&serde_json::to_string(&account_scope)?);
        let project_name = hash(scope.project_id());
        let root_fd = private_root(root)?;
        let account = private_child(&root_fd, &account_name)?;
        let directory = private_child(&account, &project_name)?;
        let lock = open_regular(&directory, "writer.lock", OFlags::RDWR | OFlags::CREATE)?;
        lock.try_lock_exclusive().map_err(|error| {
            if error.kind() == std::io::ErrorKind::WouldBlock {
                Error::Invalid("Another native process owns this Project Task cache.")
            } else {
                Error::Io
            }
        })?;
        clean_temporaries(&directory)?;
        let binding = hash(&serde_json::to_string(&json!([
            account_scope,
            scope.account_id(),
            scope.project_id(),
            scope.source_id()
        ]))?);
        let stored = read_optional(&directory, "snapshot.json")?;
        let state = if let Some(bytes) = stored {
            let state: CacheSnapshot = serde_json::from_slice(&bytes)?;
            if state.schema_version != 1
                || state.account_scope != account_scope
                || state.project_id != scope.project_id()
                || state.native_binding != binding
                || state.tasks.len() > MAX_TASKS
            {
                return Err(Error::Forbidden);
            }
            if !state.synced_at.is_empty() {
                OffsetDateTime::parse(&state.synced_at, &Rfc3339).map_err(|_| Error::Protocol)?;
            }
            state
        } else {
            CacheSnapshot {
                schema_version: 1,
                account_scope,
                project_id: scope.project_id().into(),
                cursor: String::new(),
                synced_at: String::new(),
                connection: CacheConnection::Reconnecting,
                tasks: vec![],
                native_binding: binding,
            }
        };
        let mut cache = Self {
            directory,
            _lock: lock,
            path: root.join(account_name).join(project_name),
            reducer: Some(sync),
            scope,
            state,
            poisoned: false,
            #[cfg(test)]
            fail_after_snapshot: false,
            #[cfg(test)]
            fail_after_revocation_marker: false,
        };
        let revoked = if let Some(bytes) = read_optional(&cache.directory, "revoked.json")? {
            let revoked: Revocation = serde_json::from_slice(&bytes)?;
            if revoked.schema_version != 1 || revoked.native_binding != cache.state.native_binding {
                return Err(Error::Forbidden);
            }
            true
        } else {
            cache.state.connection == CacheConnection::Revoked
        };
        if revoked {
            cache.revoke(now_seconds)?;
        } else {
            // Fence legacy hook readers before potentially expensive recovery.
            cache.state.connection = CacheConnection::Reconnecting;
            cache.publish()?;
            cache.restore_reducer(now_seconds)?;
            // A previous process's connected marker never authorizes new work.
            // Only a real server final batch/empty ACK will refresh readiness.
            cache.reconnecting()?;
        }
        Ok(cache)
    }
    pub fn directory(&self) -> &Path {
        &self.path
    }
    pub fn snapshot(&self) -> Result<&CacheSnapshot> {
        self.ensure_usable()?;
        Ok(&self.state)
    }
    pub fn cursor(&self) -> Result<Option<&str>> {
        self.ensure_usable()?;
        Ok((!self.state.cursor.is_empty()).then_some(self.state.cursor.as_str()))
    }
    pub fn reconnecting(&mut self) -> Result<()> {
        self.ensure_usable()?;
        if let Some(sync) = &mut self.reducer {
            sync.reconnecting();
        }
        if self.state.connection != CacheConnection::Revoked {
            self.state.connection = CacheConnection::Reconnecting;
        }
        self.publish()
    }
    pub fn stopped(&mut self) -> Result<()> {
        self.ensure_usable()?;
        if let Some(sync) = &mut self.reducer {
            sync.reconnecting();
        }
        if self.state.connection != CacheConnection::Revoked {
            self.state.connection = CacheConnection::Stopped;
        }
        self.publish()
    }
    /// Partial frames never reach disk. A failed publication poisons this writer;
    /// reopening reconstructs from the last atomic disk snapshot before retry.
    pub fn accept(
        &mut self,
        source_scope: &TaskSyncScope,
        event: TaskSyncEvent,
        now_seconds: u64,
    ) -> Result<bool> {
        self.ensure_usable()?;
        let synced_at = timestamp(now_seconds)?;
        let committed = match self.reducer.as_mut().ok_or(Error::Forbidden)?.accept(
            source_scope,
            event,
            now_seconds,
        ) {
            Ok(committed) => committed,
            Err(error) => {
                self.reconnecting()?;
                return Err(error);
            }
        };
        match self
            .reducer
            .as_ref()
            .ok_or(Error::Forbidden)?
            .snapshot()
            .connection
        {
            TaskSyncConnection::Revoked => self.revoke(now_seconds)?,
            TaskSyncConnection::Reconnecting => self.reconnecting()?,
            TaskSyncConnection::Connected if committed => {
                let tasks = match self.project_tasks() {
                    Ok(tasks) => tasks,
                    Err(error) => {
                        if let Some(sync) = &mut self.reducer {
                            sync.reconnecting();
                        }
                        self.state.connection = CacheConnection::Reconnecting;
                        self.publish()?;
                        self.poisoned = true;
                        return Err(error);
                    }
                };
                self.state.tasks = tasks;
                self.state.cursor = self
                    .reducer
                    .as_ref()
                    .ok_or(Error::Forbidden)?
                    .snapshot()
                    .cursor
                    .unwrap_or("")
                    .into();
                self.state.synced_at = synced_at;
                self.state.connection = CacheConnection::Connected;
                self.publish()?;
            }
            TaskSyncConnection::Connected => {}
        }
        Ok(committed)
    }
    /// Transfer the one reducer to a typed watch. Legacy accept is unavailable
    /// afterwards; this writer only publishes sealed validated snapshots.
    pub fn take_sync(&mut self) -> Result<ProjectTaskSync> {
        self.ensure_usable()?;
        self.reducer.take().ok_or(Error::Forbidden)
    }
    /// No ciphertext is decrypted here. The exact receipt is returned only
    /// after the existing atomic authority and derived view are durable.
    pub fn publish_validated(
        &mut self,
        publication: &openmates_sdk::client::ProjectTaskPublication,
        now_seconds: u64,
    ) -> Result<openmates_sdk::project_task_sync::TaskSyncCommit> {
        self.ensure_usable()?;
        if self.reducer.is_some() {
            return Err(Error::Forbidden);
        }
        let snapshot = publication.snapshot()?;
        if snapshot.scope != &self.scope || snapshot.connection != TaskSyncConnection::Connected {
            return Err(Error::Forbidden);
        }
        let tasks = Self::project_task_rows(snapshot.tasks)?;
        let receipt = publication.receipt()?.clone();
        let synced_at = timestamp(now_seconds)?;
        // A revoked marker always wins over a queued candidate, including an
        // independently observed revocation by the watch control reader.
        if self.state.connection == CacheConnection::Revoked {
            return Err(Error::Forbidden);
        }
        publication.snapshot()?;
        let previous = self.state.clone();
        self.state.tasks = tasks;
        self.state.cursor = receipt.cursor.clone();
        self.state.synced_at = synced_at;
        self.state.connection = CacheConnection::Connected;
        self.publish()?;
        if publication.snapshot().is_err() {
            // Do not acknowledge a publication invalidated during durable I/O.
            // Owner loop must apply a revoke event via revoke_watch; other
            // failures retain ciphertext but fence ordinary cached readiness.
            self.state = previous;
            self.state.connection = CacheConnection::Reconnecting;
            self.publish()?;
            return Err(Error::Cancelled);
        }
        Ok(receipt)
    }
    /// Durable revocation uses the existing marker-before-erasure policy.
    /// The authenticated owner loop calls this after a typed revoked control.
    pub fn revoke_watch(&mut self, scope: &TaskSyncScope, now_seconds: u64) -> Result<()> {
        if scope != &self.scope || self.reducer.is_some() {
            return Err(Error::Forbidden);
        }
        self.revoke(now_seconds)
    }
    fn ensure_usable(&self) -> Result<()> {
        if self.poisoned {
            Err(Error::Io)
        } else {
            let named = open_regular(&self.directory, "writer.lock", OFlags::RDONLY)?.metadata()?;
            let held = self._lock.metadata()?;
            if named.dev() != held.dev() || named.ino() != held.ino() {
                return Err(Error::Forbidden);
            }
            Ok(())
        }
    }
    fn restore_reducer(&mut self, now: u64) -> Result<()> {
        if self.state.cursor.is_empty() {
            if !self.state.tasks.is_empty() {
                return Err(Error::Protocol);
            }
            return Ok(());
        }
        let count = self.state.tasks.len().div_ceil(20).max(1);
        let records = self
            .state
            .tasks
            .iter()
            .map(|task| {
                if task.encrypted["task_id"] != task.task_id {
                    return Err(Error::Forbidden);
                }
                Ok(task.encrypted.clone())
            })
            .collect::<Result<Vec<_>>>()?;
        for part in 0..count {
            let frame = TaskSyncFrame {
                project_id: self.scope.project_id().into(),
                batch_id: "native-cache-recovery".into(),
                part: part as u32,
                final_part: part == count - 1,
                reset: true,
                cursor: self.state.cursor.clone(),
                tasks: records.iter().skip(part * 20).take(20).cloned().collect(),
                removed_task_ids: vec![],
            };
            self.reducer.as_mut().ok_or(Error::Forbidden)?.accept(
                &self.scope,
                TaskSyncEvent::Batch(frame),
                now,
            )?;
        }
        // Rebuild every plaintext field from authenticated encrypted records,
        // never trust disk plaintext as the source of Task identity/content.
        self.state.tasks = self.project_tasks()?;
        Ok(())
    }
    fn project_tasks(&self) -> Result<Vec<CachedTask>> {
        Self::project_task_rows(
            self.reducer
                .as_ref()
                .ok_or(Error::Forbidden)?
                .snapshot()
                .tasks,
        )
    }
    fn project_task_rows(
        tasks: &std::collections::BTreeMap<String, openmates_sdk::project_task_sync::SyncedTask>,
    ) -> Result<Vec<CachedTask>> {
        tasks
            .values()
            .map(|task| {
                let value = task.decrypted();
                if value["version"].as_u64().is_none_or(|version| version == 0)
                    || !matches!(
                        value["status"].as_str(),
                        Some("backlog" | "todo" | "in_progress" | "blocked" | "done")
                    )
                {
                    return Err(Error::Protocol);
                }
                let activity = &value["latest_activity"];
                let latest = activity["message"]
                    .as_str()
                    .filter(|message| !message.is_empty())
                    .map(str::to_owned)
                    .unwrap_or_else(|| {
                        let event = activity["event_type"]
                            .as_str()
                            .or(activity["kind"].as_str())
                            .unwrap_or("");
                        match activity["next_status"].as_str() {
                            Some(status) => format!("{event}: {status}"),
                            None => event.into(),
                        }
                    });
                Ok(CachedTask {
                    task_id: text(value, "task_id").into(),
                    short_id: text(value, "short_id").into(),
                    title: text(value, "title").into(),
                    description: shorten(text(value, "description"), 180),
                    status: value["status"].clone(),
                    version: value["version"].clone(),
                    primary_chat_id: value["primary_chat_id"].clone(),
                    external_chat: value["external_chat"].clone(),
                    blocked_reason: value["blocked_reason"].clone(),
                    blocked_reason_code: value["blocked_reason_code"].clone(),
                    dependencies: value["dependencies"].clone(),
                    latest_activity: shorten(&latest, 140),
                    assignee_type: value["assignee_type"].clone(),
                    assignee_identity: value["assignee_identity"].clone(),
                    ai_execution_state: value["ai_execution_state"].clone(),
                    queue_state: value["queue_state"].clone(),
                    encrypted: task.encrypted().clone(),
                })
            })
            .collect()
    }
    fn revoke(&mut self, now: u64) -> Result<()> {
        self.ensure_usable()?;
        // Durable intent precedes erasure, so a crash cannot resurrect content.
        let marker = serde_json::to_vec(&Revocation {
            schema_version: 1,
            native_binding: self.state.native_binding.clone(),
        })?;
        if let Err(error) = atomic_write(&self.directory, "revoked.json", &marker) {
            self.poisoned = true;
            return Err(error);
        }
        #[cfg(test)]
        if self.fail_after_revocation_marker {
            self.poisoned = true;
            return Err(Error::Io);
        }
        if let Some(sync) = &mut self.reducer
            && sync.snapshot().connection != TaskSyncConnection::Revoked
        {
            sync.accept(
                &self.scope,
                TaskSyncEvent::AccessRevoked {
                    project_id: Some(self.scope.project_id().into()),
                },
                now,
            )?;
        }
        self.state.tasks.clear();
        self.state.cursor.clear();
        self.state.synced_at.clear();
        self.state.connection = CacheConnection::Revoked;
        self.publish()?;
        if let Err(error) = clean_temporaries(&self.directory) {
            self.poisoned = true;
            return Err(error);
        }
        Ok(())
    }
    fn publish(&mut self) -> Result<()> {
        let result = self.ensure_usable().and_then(|()| self.publish_inner());
        if result.is_err() {
            self.poisoned = true;
        }
        result
    }
    fn publish_inner(&mut self) -> Result<()> {
        let bytes = serde_json::to_vec(&self.state)?;
        let view = render(&self.state)?;
        if bytes.len() > MAX_CACHE_BYTES || view.len() > MAX_CACHE_BYTES {
            return Err(Error::Protocol);
        }
        // Publish the authority first, including a revoked/empty snapshot. A
        // derived view must never delay the hook's revocation/readiness fence.
        atomic_write(&self.directory, "snapshot.json", &bytes)?;
        #[cfg(test)]
        if self.fail_after_snapshot {
            return Err(Error::Io);
        }
        atomic_write(&self.directory, "tasks.txt", view.as_bytes())?;
        Ok(())
    }
}

fn text<'a>(value: &'a Value, field: &str) -> &'a str {
    value[field].as_str().unwrap_or("")
}
fn timestamp(seconds: u64) -> Result<String> {
    OffsetDateTime::from_unix_timestamp(seconds.try_into().map_err(|_| Error::Protocol)?)
        .map_err(|_| Error::Protocol)?
        .format(&Rfc3339)
        .map_err(|_| Error::Protocol)
}
fn hash(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
fn shorten(value: &str, limit: usize) -> String {
    let normalized = value.split_whitespace().collect::<Vec<_>>().join(" ");
    if normalized.chars().count() <= limit {
        normalized
    } else {
        format!(
            "{}…",
            normalized.chars().take(limit - 1).collect::<String>()
        )
    }
}
fn render(state: &CacheSnapshot) -> Result<String> {
    let connection = match state.connection {
        CacheConnection::Connected => "connected",
        CacheConnection::Reconnecting => "reconnecting",
        CacheConnection::Stopped => "stopped",
        CacheConnection::Revoked => "revoked",
    };
    let mut output = format!("Project {}; sync {connection}\n", state.project_id);
    for task in &state.tasks {
        output.push_str(&format!(
            "- {} [{}] {}\n",
            task.short_id,
            task.status.as_str().unwrap_or(""),
            serde_json::to_string(&task.title)?
        ));
        for (label, value) in [
            ("Description", Some(task.description.as_str())),
            (
                "Blocker",
                task.blocked_reason
                    .as_str()
                    .filter(|text| !text.is_empty())
                    .or(task.blocked_reason_code.as_str()),
            ),
            ("Latest activity", Some(task.latest_activity.as_str())),
        ] {
            if let Some(value) = value.filter(|value| !value.is_empty()) {
                output.push_str(&format!("  {label}: {}\n", serde_json::to_string(value)?));
            }
        }
        if task
            .dependencies
            .as_array()
            .is_some_and(|values| !values.is_empty())
        {
            output.push_str(&format!(
                "  Dependencies: {}\n",
                serde_json::to_string(&task.dependencies)?
            ));
        }
    }
    Ok(output)
}
fn private_root(path: &Path) -> Result<File> {
    if !path.is_absolute() {
        return Err(Error::Invalid(
            "Project Task cache requires an absolute private path.",
        ));
    }
    let mut directory = File::open("/")?;
    let mut visited = false;
    for component in path.components() {
        match component {
            Component::RootDir => {}
            Component::Normal(name) => {
                directory = child_directory(&directory, name)?;
                visited = true;
            }
            _ => return Err(Error::Forbidden),
        }
    }
    if !visited {
        return Err(Error::Forbidden);
    }
    check_directory(&directory)?;
    Ok(directory)
}
fn child_directory(parent: &File, name: impl rustix::path::Arg) -> Result<File> {
    let name = name
        .into_with_c_str(|name| {
            match rustix::fs::mkdirat(parent, name, Mode::RWXU) {
                Ok(()) => parent.sync_all().map_err(|_| rustix::io::Errno::IO)?,
                Err(rustix::io::Errno::EXIST) => {}
                Err(error) => return Err(error),
            }
            rustix::fs::openat(
                parent,
                name,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::empty(),
            )
        })
        .map_err(|_| Error::Io)?;
    Ok(File::from(name))
}
fn private_child(parent: &File, name: &str) -> Result<File> {
    let file = child_directory(parent, name)?;
    check_directory(&file)?;
    Ok(file)
}
fn check_directory(directory: &File) -> Result<()> {
    let meta = directory.metadata()?;
    if !meta.is_dir()
        || meta.uid() != rustix::process::geteuid().as_raw()
        || meta.mode() & 0o7777 != 0o700
    {
        return Err(Error::Forbidden);
    }
    Ok(())
}
fn open_regular(parent: &File, name: &str, flags: OFlags) -> Result<File> {
    let file = File::from(
        rustix::fs::openat(
            parent,
            name,
            flags | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(|_| Error::Io)?,
    );
    let meta = file.metadata()?;
    if !meta.is_file()
        || meta.uid() != rustix::process::geteuid().as_raw()
        || meta.mode() & 0o7777 != 0o600
        || meta.nlink() != 1
    {
        return Err(Error::Forbidden);
    }
    Ok(file)
}
fn read_optional(parent: &File, name: &str) -> Result<Option<Vec<u8>>> {
    match rustix::fs::statat(parent, name, AtFlags::SYMLINK_NOFOLLOW) {
        Err(rustix::io::Errno::NOENT) => return Ok(None),
        Err(_) => return Err(Error::Io),
        Ok(_) => {}
    }
    let mut file = open_regular(parent, name, OFlags::RDONLY)?;
    if file.metadata()?.len() > MAX_CACHE_BYTES as u64 {
        return Err(Error::Protocol);
    }
    let mut bytes = vec![];
    (&mut file)
        .take(MAX_CACHE_BYTES as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_CACHE_BYTES {
        return Err(Error::Protocol);
    }
    Ok(Some(bytes))
}
fn atomic_write(parent: &File, name: &str, bytes: &[u8]) -> Result<()> {
    if bytes.len() > MAX_CACHE_BYTES {
        return Err(Error::Protocol);
    }
    // Validate an existing destination, including hard links. Rename never
    // follows a substituted destination symlink, even after this check.
    if rustix::fs::statat(parent, name, AtFlags::SYMLINK_NOFOLLOW).is_ok() {
        drop(open_regular(parent, name, OFlags::RDONLY)?);
    }
    let temporary = format!(".native-cache-{}.tmp", uuid::Uuid::new_v4());
    let result = (|| {
        let mut file = open_regular(
            parent,
            &temporary,
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL,
        )?;
        file.write_all(bytes)?;
        file.sync_all()?;
        rustix::fs::renameat(parent, &temporary, parent, name).map_err(|_| Error::Io)?;
        parent.sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        let _ = rustix::fs::unlinkat(parent, &temporary, AtFlags::empty());
    }
    result
}

fn clean_temporaries(parent: &File) -> Result<()> {
    let mut directory = rustix::fs::Dir::read_from(parent).map_err(|_| Error::Io)?;
    let mut visited = 0;
    while let Some(entry) = directory.read() {
        visited += 1;
        if visited > MAX_TASKS + 32 {
            return Err(Error::Protocol);
        }
        let entry = entry.map_err(|_| Error::Io)?;
        let Some(name) = entry.file_name().to_str().ok() else {
            continue;
        };
        let Some(id) = name
            .strip_prefix(".native-cache-")
            .and_then(|name| name.strip_suffix(".tmp"))
        else {
            continue;
        };
        if uuid::Uuid::parse_str(id).is_err() {
            continue;
        }
        drop(open_regular(parent, name, OFlags::RDONLY)?);
        rustix::fs::unlinkat(parent, name, AtFlags::empty()).map_err(|_| Error::Io)?;
    }
    parent.sync_all()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        fs,
        os::unix::fs::{PermissionsExt, symlink},
    };
    const NOW: u64 = 1_792_540_800;
    fn private_tempdir() -> tempfile::TempDir {
        tempfile::Builder::new()
            .permissions(fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap()
    }
    fn scope() -> TaskSyncScope {
        TaskSyncScope::new(
            "https://example.invalid",
            "user",
            TaskSyncWorkspace::Personal,
            "project",
            "source",
        )
        .unwrap()
    }
    fn open(root: &Path) -> ProjectTaskCache {
        ProjectTaskCache::open(
            root,
            scope(),
            "hashed-email",
            zeroize::Zeroizing::new([3; 32]),
            NOW,
        )
        .unwrap()
    }
    fn raw(id: &str) -> Value {
        let key = [7; 32];
        json!({"task_id":id,"short_id":format!("TASK-{id}"),"status":"blocked","version":1,"hashed_user_id":hash("user"),
            "encrypted_title":openmates_sdk::crypto::encrypt_combined(&format!("Work {id} {}", "long title ".repeat(40)),&key).unwrap(),
            "encrypted_description":openmates_sdk::crypto::encrypt_combined(&"detail ".repeat(300),&key).unwrap(),
            "encrypted_blocked_reason":openmates_sdk::crypto::encrypt_combined("Waiting for approval",&key).unwrap(),
            "blocked_reason_code":"waiting_for_approval","external_chat_provider":"codex",
            "encrypted_external_chat_id":openmates_sdk::crypto::encrypt_combined("11111111-1111-4111-8111-111111111111",&key).unwrap(),
            "encrypted_external_chat_title":openmates_sdk::crypto::encrypt_combined("Synthetic worker",&key).unwrap(),
            "assignee_type":"ai","assignee_identity":"codex","queue_state":"ready",
            "key_wrappers":[{"key_type":"project","hashed_project_id":hash("project"),"hashed_task_id":hash(id),"hashed_user_id":hash("user"),"encrypted_task_key":openmates_sdk::crypto::encrypt_bytes(&key,&[3;32]).unwrap()}],
            "dependencies":[{"target_kind":"task","target_id":"dependency","target_status":"done"}],
            "latest_activity":{"task_id":id,"kind":"event","event_type":"status_changed","next_status":"blocked"}})
    }
    fn event(sequence: u64, tasks: Vec<Value>) -> TaskSyncFrame {
        TaskSyncFrame {
            project_id: "project".into(),
            batch_id: format!("batch-{sequence}"),
            part: 0,
            final_part: true,
            reset: true,
            cursor: format!("epoch:{sequence}"),
            tasks,
            removed_task_ids: vec![],
        }
    }
    fn accept(cache: &mut ProjectTaskCache, frame: TaskSyncFrame) -> Result<bool> {
        cache.accept(&scope(), TaskSyncEvent::Batch(frame), NOW)
    }
    fn disk(path: &Path) -> Value {
        serde_json::from_slice(&fs::read(path.join("snapshot.json")).unwrap()).unwrap()
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn legacy_private_schema_keeps_titles_and_account_project_hash_paths() {
        let root = private_tempdir();
        let mut cache = open(root.path());
        let records = (0..12).map(|id| raw(&id.to_string())).collect();
        accept(&mut cache, event(1, records)).unwrap();
        let directory = cache.directory();
        let expected = root
            .path()
            .join(hash(
                r#"["https://example.invalid","hashed-email","personal"]"#,
            ))
            .join(hash("project"));
        assert_eq!(directory, expected);
        let state = disk(directory);
        assert_eq!(state["schema_version"], 1);
        assert_eq!(
            state["account_scope"],
            json!(["https://example.invalid", "hashed-email", "personal"])
        );
        assert_eq!(state["connection"], "connected");
        assert_eq!(state["cursor"], "epoch:1");
        assert!(OffsetDateTime::parse(state["synced_at"].as_str().unwrap(), &Rfc3339).is_ok());
        assert_eq!(state["tasks"].as_array().unwrap().len(), 12);
        let view = fs::read_to_string(directory.join("tasks.txt")).unwrap();
        for task in state["tasks"].as_array().unwrap() {
            assert!(view.contains(&serde_json::to_string(&task["title"]).unwrap()));
            assert!(task["title"].as_str().unwrap().len() > 300);
            assert!(task["description"].as_str().unwrap().chars().count() <= 180);
            assert_eq!(task["external_chat"]["provider"], "codex");
            assert_eq!(task["dependencies"][0]["target_status"], "done");
            assert!(task["encrypted"]["key_wrappers"].is_array());
        }
        assert!(view.contains("Waiting for approval"));
        assert!(!view.contains(&"detail ".repeat(300)));
        for path in [root.path(), directory.parent().unwrap(), directory] {
            assert_eq!(fs::metadata(path).unwrap().mode() & 0o7777, 0o700);
        }
        for name in ["snapshot.json", "tasks.txt", "writer.lock"] {
            assert_eq!(
                fs::metadata(directory.join(name)).unwrap().mode() & 0o7777,
                0o600
            );
        }
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn partial_batch_never_changes_disk_and_restart_recovers_committed_only() {
        let root = private_tempdir();
        let mut cache = open(root.path());
        accept(&mut cache, event(1, vec![raw("original")])).unwrap();
        let path = cache.directory().to_path_buf();
        let committed = fs::read(path.join("snapshot.json")).unwrap();
        let mut frame = event(2, vec![raw("partial")]);
        frame.final_part = false;
        assert!(!accept(&mut cache, frame).unwrap());
        assert_eq!(fs::read(path.join("snapshot.json")).unwrap(), committed);
        drop(cache);
        let cache = open(root.path());
        assert_eq!(cache.cursor().unwrap(), Some("epoch:1"));
        assert_eq!(cache.snapshot().unwrap().tasks[0].task_id, "original");
        assert_eq!(disk(&path)["connection"], "reconnecting");
        assert!(matches!(
            cache.snapshot().unwrap().connection,
            CacheConnection::Reconnecting
        ));
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn empty_reconnect_ack_refreshes_readiness_and_delta_removes_membership() {
        let root = private_tempdir();
        let mut cache = open(root.path());
        accept(&mut cache, event(1, vec![raw("original")])).unwrap();
        drop(cache);
        let mut cache = open(root.path());
        let mut ack = event(1, vec![]);
        ack.reset = false;
        accept(&mut cache, ack).unwrap();
        assert_eq!(disk(cache.directory())["connection"], "connected");
        let mut change = event(2, vec![raw("replacement")]);
        change.reset = false;
        change.removed_task_ids = vec!["original".into()];
        accept(&mut cache, change).unwrap();
        let state = disk(cache.directory());
        assert_eq!(state["cursor"], "epoch:2");
        assert_eq!(state["tasks"][0]["task_id"], "replacement");
        cache.stopped().unwrap();
        assert_eq!(disk(cache.directory())["connection"], "stopped");
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn failed_derived_view_publication_recovers_atomic_cursor_and_tasks() {
        let root = private_tempdir();
        let mut cache = open(root.path());
        accept(&mut cache, event(1, vec![raw("old")])).unwrap();
        let path = cache.directory().to_path_buf();
        cache.fail_after_snapshot = true;
        assert!(accept(&mut cache, event(2, vec![raw("new")])).is_err());
        assert!(cache.cursor().is_err());
        assert!(cache.snapshot().is_err());
        assert_eq!(disk(&path)["cursor"], "epoch:2");
        assert_eq!(disk(&path)["tasks"][0]["task_id"], "new");
        assert!(
            fs::read_to_string(path.join("tasks.txt"))
                .unwrap()
                .contains("Work old")
        );
        drop(cache);
        let cache = open(root.path());
        assert_eq!(cache.cursor().unwrap(), Some("epoch:2"));
        let view = fs::read_to_string(path.join("tasks.txt")).unwrap();
        assert!(view.contains("Work new"));
        assert!(!view.contains("Work old"));
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn durable_revocation_recovers_erasure_after_interrupted_cleanup() {
        let root = private_tempdir();
        let mut cache = open(root.path());
        accept(&mut cache, event(1, vec![raw("private")])).unwrap();
        let path = cache.directory().to_path_buf();
        let temporary = path.join(format!(".native-cache-{}.tmp", uuid::Uuid::new_v4()));
        fs::write(&temporary, b"private abandoned atomic write").unwrap();
        fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600)).unwrap();
        cache.fail_after_revocation_marker = true;
        assert!(
            cache
                .accept(
                    &scope(),
                    TaskSyncEvent::AccessRevoked { project_id: None },
                    NOW
                )
                .is_err()
        );
        assert!(path.join("revoked.json").exists());
        drop(cache);
        let mut cache = open(root.path());
        let state = disk(&path);
        assert_eq!(state["connection"], "revoked");
        assert_eq!(state["cursor"], "");
        assert_eq!(state["tasks"], json!([]));
        assert!(
            !fs::read_to_string(path.join("tasks.txt"))
                .unwrap()
                .contains("Work private")
        );
        assert!(!temporary.exists());
        assert!(accept(&mut cache, event(2, vec![raw("not-authorized")])).is_err());
        assert_eq!(disk(&path)["connection"], "revoked");
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn lock_excludes_second_writer_and_detects_replaced_lock_inode() {
        let root = private_tempdir();
        let mut cache = open(root.path());
        assert!(
            ProjectTaskCache::open(
                root.path(),
                scope(),
                "hashed-email",
                zeroize::Zeroizing::new([3; 32]),
                NOW
            )
            .is_err()
        );
        fs::rename(
            cache.directory().join("writer.lock"),
            cache.directory().join("old-writer.lock"),
        )
        .unwrap();
        fs::write(cache.directory().join("writer.lock"), b"").unwrap();
        fs::set_permissions(
            cache.directory().join("writer.lock"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        assert!(cache.reconnecting().is_err());
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn owner_api_team_project_and_source_bindings_never_cross() {
        let root = private_tempdir();
        let cache = open(root.path());
        let original = cache.directory().to_path_buf();
        drop(cache);
        for selected in [
            TaskSyncScope::new(
                "https://example.invalid",
                "other",
                TaskSyncWorkspace::Personal,
                "project",
                "source",
            )
            .unwrap(),
            TaskSyncScope::new(
                "https://example.invalid",
                "user",
                TaskSyncWorkspace::Personal,
                "project",
                "other-source",
            )
            .unwrap(),
        ] {
            assert!(
                ProjectTaskCache::open(
                    root.path(),
                    selected,
                    "hashed-email",
                    zeroize::Zeroizing::new([3; 32]),
                    NOW
                )
                .is_err()
            );
        }
        for selected in [
            TaskSyncScope::new(
                "https://other.invalid",
                "user",
                TaskSyncWorkspace::Personal,
                "project",
                "source",
            )
            .unwrap(),
            TaskSyncScope::new(
                "https://example.invalid",
                "user",
                TaskSyncWorkspace::Team("team".into()),
                "project",
                "source",
            )
            .unwrap(),
            TaskSyncScope::new(
                "https://example.invalid",
                "user",
                TaskSyncWorkspace::Personal,
                "other-project",
                "source",
            )
            .unwrap(),
        ] {
            let separate = ProjectTaskCache::open(
                root.path(),
                selected,
                "hashed-email",
                zeroize::Zeroizing::new([3; 32]),
                NOW,
            )
            .unwrap();
            assert_ne!(separate.directory(), original);
            assert!(separate.snapshot().unwrap().tasks.is_empty());
        }
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn descriptor_anchor_rejects_symlinks_hardlinks_and_insecure_roots() {
        let parent = private_tempdir();
        let outside = private_tempdir();
        symlink(outside.path(), parent.path().join("linked")).unwrap();
        assert!(
            ProjectTaskCache::open(
                &parent.path().join("linked"),
                scope(),
                "hashed-email",
                zeroize::Zeroizing::new([3; 32]),
                NOW
            )
            .is_err()
        );
        let cache = open(parent.path());
        let path = cache.directory().to_path_buf();
        drop(cache);
        fs::remove_file(path.join("snapshot.json")).unwrap();
        symlink(outside.path().join("secret"), path.join("snapshot.json")).unwrap();
        assert!(
            ProjectTaskCache::open(
                parent.path(),
                scope(),
                "hashed-email",
                zeroize::Zeroizing::new([3; 32]),
                NOW
            )
            .is_err()
        );
        fs::remove_file(path.join("snapshot.json")).unwrap();
        fs::write(outside.path().join("secret"), b"preserve outside bytes").unwrap();
        fs::set_permissions(
            outside.path().join("secret"),
            fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        fs::hard_link(outside.path().join("secret"), path.join("snapshot.json")).unwrap();
        assert!(
            ProjectTaskCache::open(
                parent.path(),
                scope(),
                "hashed-email",
                zeroize::Zeroizing::new([3; 32]),
                NOW
            )
            .is_err()
        );
        assert_eq!(
            fs::read(outside.path().join("secret")).unwrap(),
            b"preserve outside bytes"
        );
        fs::set_permissions(parent.path(), fs::Permissions::from_mode(0o755)).unwrap();
        assert!(
            ProjectTaskCache::open(
                parent.path(),
                scope(),
                "hashed-email",
                zeroize::Zeroizing::new([3; 32]),
                NOW
            )
            .is_err()
        );
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn plaintext_is_rebuilt_from_authenticated_records_and_bad_crypto_fences_hooks() {
        let root = private_tempdir();
        let mut cache = open(root.path());
        accept(&mut cache, event(1, vec![raw("original")])).unwrap();
        let path = cache.directory().to_path_buf();
        drop(cache);
        let mut state = disk(&path);
        state["tasks"][0]["title"] = json!("untrusted cache edit");
        fs::write(
            path.join("snapshot.json"),
            serde_json::to_vec(&state).unwrap(),
        )
        .unwrap();
        let cache = open(root.path());
        assert!(
            cache.snapshot().unwrap().tasks[0]
                .title
                .starts_with("Work original")
        );
        drop(cache);
        let mut state = disk(&path);
        state["connection"] = json!("connected");
        state["tasks"][0]["encrypted"]["encrypted_title"] = json!("tampered");
        fs::write(
            path.join("snapshot.json"),
            serde_json::to_vec(&state).unwrap(),
        )
        .unwrap();
        assert!(
            ProjectTaskCache::open(
                root.path(),
                scope(),
                "hashed-email",
                zeroize::Zeroizing::new([3; 32]),
                NOW
            )
            .is_err()
        );
        assert_eq!(disk(&path)["connection"], "reconnecting");
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn renamed_directory_cannot_redirect_descriptor_anchored_publication() {
        let root = private_tempdir();
        let outside = private_tempdir();
        let mut cache = open(root.path());
        let path = cache.directory().to_path_buf();
        let moved = path.with_extension("moved");
        fs::rename(&path, &moved).unwrap();
        symlink(outside.path(), &path).unwrap();
        accept(&mut cache, event(1, vec![raw("anchored")])).unwrap();
        assert_eq!(disk(&moved)["cursor"], "epoch:1");
        assert!(!outside.path().join("snapshot.json").exists());
        assert!(!outside.path().join("tasks.txt").exists());
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn oversized_snapshots_are_rejected_without_reading_or_rewriting_them() {
        let root = private_tempdir();
        let cache = open(root.path());
        let path = cache.directory().join("snapshot.json");
        drop(cache);
        File::options()
            .write(true)
            .open(&path)
            .unwrap()
            .set_len(MAX_CACHE_BYTES as u64 + 1)
            .unwrap();
        assert!(
            ProjectTaskCache::open(
                root.path(),
                scope(),
                "hashed-email",
                zeroize::Zeroizing::new([3; 32]),
                NOW
            )
            .is_err()
        );
        assert_eq!(
            fs::metadata(path).unwrap().len(),
            MAX_CACHE_BYTES as u64 + 1
        );
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn invalid_hook_metadata_never_publishes_new_cursor_or_live_state() {
        for (field, value) in [("version", json!(-1)), ("status", json!("unknown"))] {
            let root = private_tempdir();
            let mut cache = open(root.path());
            accept(&mut cache, event(1, vec![raw("original")])).unwrap();
            let mut bad = raw("invalid");
            bad[field] = value;
            assert!(accept(&mut cache, event(2, vec![bad])).is_err());
            let state = disk(cache.directory());
            assert_eq!(state["cursor"], "epoch:1");
            assert_eq!(state["tasks"][0]["task_id"], "original");
            assert_eq!(state["connection"], "reconnecting");
            assert!(cache.cursor().is_err());
        }
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn reducer_transfers_once_and_detached_cache_rejects_raw_frames() {
        let root = private_tempdir();
        let mut cache = open(root.path());
        accept(&mut cache, event(1, vec![raw("existing")])).unwrap();
        let sync = cache.take_sync().unwrap();
        assert_eq!(sync.snapshot().cursor, Some("epoch:1"));
        assert_eq!(sync.snapshot().tasks.len(), 1);
        assert!(cache.take_sync().is_err());
        assert!(matches!(
            accept(&mut cache, event(2, vec![])),
            Err(Error::Forbidden)
        ));
        assert_eq!(cache.cursor().unwrap(), Some("epoch:1"));
        cache.revoke_watch(&scope(), NOW).unwrap();
        assert!(cache.snapshot().unwrap().tasks.is_empty());
        assert!(cache.snapshot().unwrap().connection == CacheConnection::Revoked);
    }
}
