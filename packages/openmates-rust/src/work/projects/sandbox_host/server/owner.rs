//! Process isolation helpers of the sandbox host: the daemon runs as root and
//! hands the Project files to the unprivileged sandbox user, so commands run
//! as that user cannot read the daemon's memory, environment or key.
use rustix::fs::{AtFlags, CWD, Gid, Uid, chownat};
use std::path::Path;

/// uid/gid of the user that runs model commands.
#[derive(Clone, Copy, Debug)]
pub struct RunUser {
    uid: u32,
    gid: u32,
}

impl RunUser {
    /// Looks `name` up in `/etc/passwd`. `None` when the daemon is not root
    /// (chown would fail) or the user does not exist, so unprivileged test
    /// runs simply skip ownership changes.
    pub fn lookup(name: &str) -> Option<Self> {
        if !rustix::process::geteuid().is_root() {
            return None;
        }
        let passwd = std::fs::read_to_string("/etc/passwd").ok()?;
        passwd.lines().find_map(|line| {
            let mut parts = line.split(':');
            if parts.next()? != name {
                return None;
            }
            let uid = parts.nth(1)?.parse().ok()?;
            let gid = parts.next()?.parse().ok()?;
            Some(Self { uid, gid })
        })
    }

    /// Makes `path` owned by the user (symlinks are not followed). Errors are
    /// ignored for vanished paths; the file stays root-owned, which only makes
    /// it read-only for commands.
    pub fn chown(&self, path: &Path) {
        let _ = chownat(
            CWD,
            path,
            Some(Uid::from_raw(self.uid)),
            Some(Gid::from_raw(self.gid)),
            AtFlags::SYMLINK_NOFOLLOW,
        );
    }

    /// Chowns `path` and every ancestor directory below `root`.
    pub fn chown_with_parents(&self, root: &Path, path: &Path) {
        let mut current = Some(path);
        while let Some(p) = current {
            if p == root || !p.starts_with(root) {
                break;
            }
            self.chown(p);
            current = p.parent();
        }
    }

    /// Chowns `root` and everything below it (including `.git`).
    pub fn chown_tree(&self, root: &Path) {
        self.chown(root);
        let Ok(entries) = std::fs::read_dir(root) else {
            return;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            match entry.file_type() {
                Ok(kind) if kind.is_dir() => self.chown_tree(&path),
                _ => self.chown(&path),
            }
        }
    }
}

/// Marks the process non-dumpable so no other process of the same uid can
/// ptrace it or read `/proc/<pid>/mem`. Best effort: failure is reported to
/// the caller, who decides whether to continue.
///
/// # Errors
/// The OS error when the kernel refuses `prctl(PR_SET_DUMPABLE)`.
pub fn make_non_dumpable() -> std::io::Result<()> {
    rustix::process::set_dumpable_behavior(rustix::process::DumpableBehavior::NotDumpable)
        .map_err(std::io::Error::from)
}
