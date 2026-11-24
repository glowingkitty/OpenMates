//! Version grouping. Edits are grouped into `session` versions (closed after 3 idle minutes
//! or 30 minutes of continuous editing); assistant change sets, restores and commits are
//! always their own entry; naming a version turns the open session into a `named` one.
//! Never one version per keystroke. Pure state machine; time is injected (milliseconds).

use std::collections::BTreeMap;

/// A session closes after this much idle time.
pub const SESSION_IDLE_MS: u64 = 3 * 60_000;
/// A session closes after this much continuous editing.
pub const SESSION_MAX_MS: u64 = 30 * 60_000;
/// Unnamed sessions older than this are compacted.
pub const COMPACTION_AGE_MS: u64 = 30 * 24 * 3_600_000;
const DAY_MS: u64 = 24 * 3_600_000;

/// Kind of a version.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum VersionKind {
    /// Grouped edits.
    Session,
    /// One assistant change set.
    Assistant,
    /// A restore of an old version.
    Restore,
    /// A user-named version.
    Named,
    /// A Project commit.
    Commit,
}

/// One timeline entry.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VersionCheckpoint {
    /// Kind.
    pub kind: VersionKind,
    /// User ids and mate names that contributed.
    pub contributors: Vec<String>,
    /// First change, ms.
    pub started_at: u64,
    /// Last change, ms.
    pub ended_at: u64,
    /// Name of a `named` version.
    pub name: Option<String>,
}

/// An event fed to the timeline.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TimelineEvent {
    /// A local or remote change by `contributor`.
    Change {
        /// User id.
        contributor: String,
        /// Time, ms.
        at_ms: u64,
    },
    /// An assistant change set.
    Assistant {
        /// The mate's name.
        mate_name: String,
        /// Time, ms.
        at_ms: u64,
    },
    /// A restore by `contributor`.
    Restore {
        /// User id.
        contributor: String,
        /// Time, ms.
        at_ms: u64,
    },
    /// The user names the current state.
    NameVersion {
        /// The name.
        name: String,
        /// Time, ms.
        at_ms: u64,
    },
    /// A Project commit.
    Commit {
        /// User id.
        contributor: String,
        /// Time, ms.
        at_ms: u64,
    },
}

/// The grouping state machine.
#[derive(Debug, Default)]
pub struct Timeline {
    open: Option<VersionCheckpoint>,
}

fn add(list: &mut Vec<String>, who: &str) {
    if !list.iter().any(|c| c == who) {
        list.push(who.to_string());
    }
}

fn single(kind: VersionKind, who: &str, at_ms: u64) -> VersionCheckpoint {
    VersionCheckpoint {
        kind,
        contributors: vec![who.to_string()],
        started_at: at_ms,
        ended_at: at_ms,
        name: None,
    }
}

impl Timeline {
    /// Empty timeline (no open session).
    pub fn new() -> Self {
        Self::default()
    }

    /// Feeds one event; returns the versions it closed or created, oldest first.
    pub fn push(&mut self, event: TimelineEvent) -> Vec<VersionCheckpoint> {
        let mut out = Vec::new();
        match event {
            TimelineEvent::Change { contributor, at_ms } => {
                if let Some(open) = &self.open
                    && (at_ms.saturating_sub(open.ended_at) >= SESSION_IDLE_MS
                        || at_ms.saturating_sub(open.started_at) >= SESSION_MAX_MS)
                {
                    out.extend(self.open.take());
                }
                match &mut self.open {
                    Some(open) => {
                        open.ended_at = at_ms;
                        add(&mut open.contributors, &contributor);
                    }
                    None => self.open = Some(single(VersionKind::Session, &contributor, at_ms)),
                }
            }
            TimelineEvent::Assistant { mate_name, at_ms } => {
                out.extend(self.open.take());
                out.push(single(VersionKind::Assistant, &mate_name, at_ms));
            }
            TimelineEvent::Restore { contributor, at_ms } => {
                out.extend(self.open.take());
                out.push(single(VersionKind::Restore, &contributor, at_ms));
            }
            TimelineEvent::Commit { contributor, at_ms } => {
                out.extend(self.open.take());
                out.push(single(VersionKind::Commit, &contributor, at_ms));
            }
            TimelineEvent::NameVersion { name, at_ms } => {
                let mut named = self.open.take().unwrap_or(VersionCheckpoint {
                    kind: VersionKind::Named,
                    contributors: Vec::new(),
                    started_at: at_ms,
                    ended_at: at_ms,
                    name: None,
                });
                named.kind = VersionKind::Named;
                named.name = Some(name);
                out.push(named);
            }
        }
        out
    }

    /// Closes the open session when it has been idle for 3 minutes (call on a timer).
    pub fn tick(&mut self, now_ms: u64) -> Vec<VersionCheckpoint> {
        match &self.open {
            Some(open) if now_ms.saturating_sub(open.ended_at) >= SESSION_IDLE_MS => {
                self.open.take().into_iter().collect()
            }
            _ => Vec::new(),
        }
    }

    /// Closes the open session now (the item is closed).
    pub fn flush(&mut self) -> Vec<VersionCheckpoint> {
        self.open.take().into_iter().collect()
    }
}

/// One merge of several old unnamed session versions into a single day entry.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Merge {
    /// UTC day number (ms / 86 400 000).
    pub day: u64,
    /// Indexes into the input of the versions merged, ascending.
    pub indexes: Vec<usize>,
    /// The merged version.
    pub merged: VersionCheckpoint,
}

/// Merges unnamed `session` versions older than 30 days into one per day. Other kinds and
/// days with a single session are left alone.
pub fn compaction_plan(versions: &[VersionCheckpoint], now_ms: u64) -> Vec<Merge> {
    let mut days: BTreeMap<u64, Vec<usize>> = BTreeMap::new();
    for (index, v) in versions.iter().enumerate() {
        let old = now_ms.saturating_sub(v.ended_at) > COMPACTION_AGE_MS;
        if v.kind == VersionKind::Session && v.name.is_none() && old {
            days.entry(v.ended_at / DAY_MS).or_default().push(index);
        }
    }
    days.into_iter()
        .filter(|(_, idx)| idx.len() > 1)
        .map(|(day, indexes)| {
            let mut contributors = Vec::new();
            for &i in &indexes {
                for who in &versions[i].contributors {
                    add(&mut contributors, who);
                }
            }
            let merged = VersionCheckpoint {
                kind: VersionKind::Session,
                contributors,
                started_at: indexes
                    .iter()
                    .map(|&i| versions[i].started_at)
                    .min()
                    .unwrap_or(0),
                ended_at: indexes
                    .iter()
                    .map(|&i| versions[i].ended_at)
                    .max()
                    .unwrap_or(0),
                name: None,
            };
            Merge {
                day,
                indexes,
                merged,
            }
        })
        .collect()
}
