//! `FileByteStore`: the native directory implementation of `ByteStore`.
//!
//! Moved unchanged in behaviour from the TUI `storage.rs` file primitives. The
//! invariants it protects: the store directory is reached by walking from `/`
//! with `O_NOFOLLOW` descriptors (no intermediate symlink can redirect a write),
//! or, for sandboxed apps, created as one `O_NOFOLLOW` child of an OS-provided
//! container (`open_in`);
//! the directory is `0700` and every record `0600`, owned by the effective
//! user with a single link; a write is temp file + fsync + rename (+ directory
//! fsync), so readers see the old or the new record, never a torn one.
use super::{ByteStore, ByteStoreError, Durability, LockGuard, MAX_LOCAL_RECORD_BYTES};
use rustix::fs::{FlockOperation, Mode, OFlags};
use std::{
    fs::File,
    io::{Read, Write},
    os::unix::fs::MetadataExt,
    path::{Component, Path},
    time::{Duration, Instant},
};

type Result<T> = std::result::Result<T, ByteStoreError>;

/// Everything that identifies one observed record file. Two equal identities
/// mean the same inode with the same size, timestamps and permissions, so a
/// replacement (even with identical bytes) is detectable.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FileIdentity {
    device: u64,
    inode: u64,
    mode: u32,
    uid: u32,
    gid: u32,
    links: u64,
    bytes: u64,
    modified: (i64, i64),
    changed: (i64, i64),
}

impl FileIdentity {
    /// Size in bytes of the file when it was observed.
    pub fn len(&self) -> u64 {
        self.bytes
    }
    /// True when the observed file was empty.
    pub fn is_empty(&self) -> bool {
        self.bytes == 0
    }
}

/// A private directory of named records, anchored by an open descriptor.
pub struct FileByteStore {
    root: File,
}

/// Holds an exclusive `flock` until dropped.
struct FileLock(File);

impl Drop for FileLock {
    fn drop(&mut self) {
        // Closing the descriptor releases the lock regardless; the explicit
        // unlock only shortens the window when a duplicate descriptor lives on.
        let _ = rustix::fs::flock(&self.0, FlockOperation::Unlock);
    }
}

impl FileByteStore {
    /// Open (creating as needed) the private store directory `path`.
    ///
    /// # Errors
    /// `RelativePath`/`NonNormalizedPath` for unusable paths, `NotPrivate` when
    /// the final directory is not `0700` and owned by this user, `Io`.
    pub fn open(path: &Path) -> Result<Self> {
        if !path.is_absolute() {
            return Err(ByteStoreError::RelativePath);
        }
        // Walk from an open root descriptor so intermediate symlinks cannot
        // redirect credential writes. Existing parent directories need not be private.
        let mut directory = File::from(
            rustix::fs::open(
                "/",
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC,
                Mode::empty(),
            )
            .map_err(|_| ByteStoreError::Io)?,
        );
        let components: Vec<_> = path.components().collect();
        for (index, component) in components.iter().enumerate() {
            let Component::Normal(name) = component else {
                if matches!(component, Component::RootDir) {
                    continue;
                }
                return Err(ByteStoreError::NonNormalizedPath);
            };
            let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
            let fd = match rustix::fs::openat(&directory, *name, flags, Mode::empty()) {
                Ok(fd) => fd,
                Err(rustix::io::Errno::NOENT) => {
                    rustix::fs::mkdirat(&directory, *name, Mode::RUSR | Mode::WUSR | Mode::XUSR)
                        .map_err(|_| ByteStoreError::Io)?;
                    rustix::fs::openat(&directory, *name, flags, Mode::empty())
                        .map_err(|_| ByteStoreError::Io)?
                }
                Err(_) => return Err(ByteStoreError::Io),
            };
            directory = File::from(fd);
            if index + 1 == components.len() {
                check_private(&directory, true)?;
            }
        }
        check_private(&directory, true)?;
        Ok(Self { root: directory })
    }

    /// Open (creating as needed) the private store directory `name` inside the
    /// existing, OS-provided `container` (an app sandbox container such as
    /// Apple's Application Support or temporary directory).
    ///
    /// Unlike [`Self::open`] it does not walk from `/`: inside an app sandbox
    /// the container's ancestors are not readable. The container path is
    /// opened directly, so symlinks in it are followed (the OS hands out paths
    /// like `/var/...` that resolve to `/private/var/...`); it must be a
    /// directory owned by this user and is never created. `name` is created
    /// `0700` and opened with `O_NOFOLLOW`, so a symlink planted at `name`
    /// cannot redirect writes, and it must be private.
    ///
    /// # Errors
    /// `RelativePath`/`NonNormalizedPath` for an unusable container path,
    /// `InvalidName` when `name` is not one plain component, `NotPrivate`
    /// when the container is not owned by this user or `name` is not a
    /// private directory, `Io` (also for a missing container).
    pub fn open_in(container: &Path, name: &str) -> Result<Self> {
        if !container.is_absolute() {
            return Err(ByteStoreError::RelativePath);
        }
        if container
            .components()
            .any(|component| matches!(component, Component::CurDir | Component::ParentDir))
        {
            return Err(ByteStoreError::NonNormalizedPath);
        }
        validate_name(name)?;
        let parent = File::from(
            rustix::fs::open(
                container,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC,
                Mode::empty(),
            )
            .map_err(|_| ByteStoreError::Io)?,
        );
        let metadata = parent.metadata()?;
        if !metadata.is_dir() || metadata.uid() != rustix::process::geteuid().as_raw() {
            return Err(ByteStoreError::NotPrivate);
        }
        let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
        let fd = match rustix::fs::openat(&parent, name, flags, Mode::empty()) {
            Ok(fd) => fd,
            Err(rustix::io::Errno::NOENT) => {
                match rustix::fs::mkdirat(&parent, name, Mode::RUSR | Mode::WUSR | Mode::XUSR) {
                    // A concurrent opener may have created it first; the
                    // private check below still decides.
                    Ok(()) | Err(rustix::io::Errno::EXIST) => {}
                    Err(_) => return Err(ByteStoreError::Io),
                }
                rustix::fs::openat(&parent, name, flags, Mode::empty())
                    .map_err(|_| ByteStoreError::Io)?
            }
            Err(_) => return Err(ByteStoreError::Io),
        };
        let directory = File::from(fd);
        check_private(&directory, true)?;
        Ok(Self { root: directory })
    }

    /// Open `name` privately with `flags`, refusing symlinks and foreign files.
    fn open_named(&self, name: &str, flags: OFlags) -> Result<File> {
        check_private(&self.root, true)?;
        validate_name(name)?;
        let fd = rustix::fs::openat(
            &self.root,
            name,
            flags | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::RUSR | Mode::WUSR,
        )
        .map_err(|_| ByteStoreError::Io)?;
        let file = File::from(fd);
        check_private(&file, false)?;
        Ok(file)
    }

    /// Bytes of `name` plus the identity of the exact descriptor they came from.
    /// Identity capture is optional evidence: a failure yields `None`, never an error.
    ///
    /// # Errors
    /// As `get`.
    pub fn get_with_identity(&self, name: &str) -> Result<Option<(Vec<u8>, Option<FileIdentity>)>> {
        validate_name(name)?;
        check_private(&self.root, true)?;
        let fd = match rustix::fs::openat(
            &self.root,
            name,
            OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW | OFlags::NONBLOCK,
            Mode::empty(),
        ) {
            Ok(fd) => fd,
            Err(rustix::io::Errno::NOENT) => return Ok(None),
            Err(_) => return Err(ByteStoreError::Io),
        };
        let mut file = File::from(fd);
        check_private(&file, false)?;
        if file.metadata()?.len() > MAX_LOCAL_RECORD_BYTES as u64 {
            return Err(ByteStoreError::TooLarge);
        }
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        let identity = Self::identity(&file).ok();
        Ok(Some((bytes, identity)))
    }

    /// Identity of an open record file; fails unless it is private.
    ///
    /// # Errors
    /// `NotPrivate` for a foreign, non-private, linked or non-regular file.
    pub fn identity(file: &File) -> Result<FileIdentity> {
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.uid() != rustix::process::geteuid().as_raw()
            || metadata.mode() & 0o777 != 0o600
            || metadata.nlink() != 1
        {
            return Err(ByteStoreError::NotPrivate);
        }
        Ok(FileIdentity {
            device: metadata.dev(),
            inode: metadata.ino(),
            mode: metadata.mode(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            links: metadata.nlink(),
            bytes: metadata.len(),
            modified: (metadata.mtime(), metadata.mtime_nsec()),
            changed: (metadata.ctime(), metadata.ctime_nsec()),
        })
    }

    /// Open the existing record `name` without following symlinks; `None` when
    /// it does not exist. `writable` opens read-write.
    ///
    /// # Errors
    /// `NotPrivate` or `Io` when the entry is not a private regular file.
    pub fn open_existing(&self, name: &str, writable: bool) -> Result<Option<File>> {
        validate_name(name)?;
        let access = if writable {
            OFlags::RDWR
        } else {
            OFlags::RDONLY
        };
        let fd = match rustix::fs::openat(
            &self.root,
            name,
            access | OFlags::CLOEXEC | OFlags::NOFOLLOW | OFlags::NONBLOCK,
            Mode::empty(),
        ) {
            Ok(fd) => fd,
            Err(rustix::io::Errno::NOENT) => return Ok(None),
            Err(_) => return Err(ByteStoreError::Io),
        };
        check_private(&self.root, true)?;
        let file = File::from(fd);
        check_private(&file, false)?;
        Ok(Some(file))
    }

    /// Open the record `name` read-only to compare it against a held descriptor;
    /// a missing record is an error here, unlike `open_existing`.
    ///
    /// # Errors
    /// `Io` when missing, `NotPrivate` when not private.
    pub fn open_current(&self, name: &str) -> Result<File> {
        self.open_named(name, OFlags::RDONLY | OFlags::NONBLOCK)
    }

    /// Check that the store directory itself is still private and owned by us.
    ///
    /// # Errors
    /// `NotPrivate` when it changed.
    pub fn check_directory(&self) -> Result<()> {
        check_private(&self.root, true)
    }

    /// Replace `name` atomically and return the fsynced, renamed descriptor (not
    /// a reopened file). `sync_directory: false` is only for records a later,
    /// synced commit names.
    ///
    /// # Errors
    /// As `put`; a failed attempt removes its temporary file.
    pub fn put_file(&self, name: &str, bytes: &[u8], sync_directory: bool) -> Result<File> {
        self.put_file_hooked(name, bytes, sync_directory, || Ok(()))
    }

    /// `put_file` with a callback between the rename and the directory fsync.
    /// It exists so crash-window faults can be injected; an `Err` there is
    /// treated like any failure after the rename (temporary cleanup only).
    ///
    /// # Errors
    /// As `put_file`, plus whatever `after_rename` returns.
    pub fn put_file_hooked(
        &self,
        name: &str,
        bytes: &[u8],
        sync_directory: bool,
        after_rename: impl FnOnce() -> Result<()>,
    ) -> Result<File> {
        // Validate existing targets as well as replacement files; reject symlinks
        // and names that would leave the directory (get checks the name first).
        self.get(name)?;
        let temporary = format!(".tmp-{}", uuid::Uuid::new_v4());
        let result = (|| {
            let mut file =
                self.open_named(&temporary, OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL)?;
            file.write_all(bytes)?;
            file.sync_all()?;
            rustix::fs::renameat(&self.root, &temporary, &self.root, name)
                .map_err(|_| ByteStoreError::Io)?;
            after_rename()?;
            if sync_directory {
                self.root.sync_all()?;
            }
            Ok(file)
        })();
        if result.is_err() {
            let _ = rustix::fs::unlinkat(&self.root, &temporary, rustix::fs::AtFlags::empty());
        }
        result
    }

    /// Take `scope`'s lock without waiting.
    ///
    /// # Errors
    /// `WouldBlock` when another holder has it, `Io` otherwise.
    pub fn try_lock(&self, scope: &str) -> Result<LockGuard> {
        let file = self.open_named(scope, OFlags::RDWR | OFlags::CREATE)?;
        match rustix::fs::flock(&file, FlockOperation::NonBlockingLockExclusive) {
            Ok(()) => Ok(LockGuard::new(FileLock(file))),
            Err(rustix::io::Errno::WOULDBLOCK) => Err(ByteStoreError::WouldBlock),
            Err(_) => Err(ByteStoreError::Io),
        }
    }

    /// Take `scope`'s lock, polling every 50 ms for at most `timeout`.
    ///
    /// # Errors
    /// `WouldBlock` once the timeout passes, `Io` otherwise.
    pub fn lock_timeout(&self, scope: &str, timeout: Duration) -> Result<LockGuard> {
        let file = self.open_named(scope, OFlags::RDWR | OFlags::CREATE)?;
        let deadline = Instant::now() + timeout;
        loop {
            match rustix::fs::flock(&file, FlockOperation::NonBlockingLockExclusive) {
                Ok(()) => return Ok(LockGuard::new(FileLock(file))),
                Err(rustix::io::Errno::WOULDBLOCK) => {
                    if Instant::now() >= deadline {
                        return Err(ByteStoreError::WouldBlock);
                    }
                    std::thread::sleep(Duration::from_millis(50));
                }
                Err(_) => return Err(ByteStoreError::Io),
            }
        }
    }
}

impl ByteStore for FileByteStore {
    type Version = FileIdentity;

    fn get(&self, name: &str) -> Result<Option<Vec<u8>>> {
        Ok(self.get_with_identity(name)?.map(|(bytes, _)| bytes))
    }

    fn version(&self, name: &str) -> Result<Option<FileIdentity>> {
        match self.open_existing(name, false)? {
            Some(file) => Self::identity(&file).map(Some),
            None => Ok(None),
        }
    }

    fn put(&self, name: &str, bytes: &[u8], durability: Durability) -> Result<()> {
        self.put_file(name, bytes, durability == Durability::Now)
            .map(|_| ())
    }

    fn delete(&self, name: &str) -> Result<()> {
        validate_name(name)?;
        check_private(&self.root, true)?;
        let fd = match rustix::fs::openat(
            &self.root,
            name,
            OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        ) {
            Ok(fd) => fd,
            Err(rustix::io::Errno::NOENT) => return Ok(()),
            Err(_) => return Err(ByteStoreError::Io),
        };
        // Cleanup must work even for damaged or oversized ciphertext records.
        check_private(&File::from(fd), false)?;
        rustix::fs::unlinkat(&self.root, name, rustix::fs::AtFlags::empty())
            .map_err(|_| ByteStoreError::Io)?;
        Ok(())
    }

    fn list(&self, prefix: &str) -> Result<Vec<String>> {
        // Enumerate through the same anchored descriptor used for reads/writes.
        let entries = rustix::fs::Dir::read_from(&self.root).map_err(|_| ByteStoreError::Io)?;
        let mut names = Vec::new();
        for entry in entries {
            let entry = entry.map_err(|_| ByteStoreError::Io)?;
            let name = entry.file_name().to_str().map_err(|_| ByteStoreError::Io)?;
            if name.starts_with(prefix) {
                names.push(name.to_owned());
            }
        }
        Ok(names)
    }

    fn barrier(&self) -> Result<()> {
        self.root.sync_all()?;
        Ok(())
    }

    fn sync(&self, name: &str) -> Result<()> {
        self.open_named(name, OFlags::RDONLY | OFlags::NONBLOCK)?
            .sync_all()?;
        Ok(())
    }

    fn lock(&self, scope: &str) -> Result<LockGuard> {
        let file = self.open_named(scope, OFlags::RDWR | OFlags::CREATE)?;
        rustix::fs::flock(&file, FlockOperation::LockExclusive).map_err(|_| ByteStoreError::Io)?;
        Ok(LockGuard::new(FileLock(file)))
    }
}

/// A record name is one plain path component: it can never leave the directory.
fn validate_name(name: &str) -> Result<()> {
    if name.is_empty() || name.contains('/') || name == "." || name == ".." {
        return Err(ByteStoreError::InvalidName);
    }
    Ok(())
}

fn check_private(file: &File, directory: bool) -> Result<()> {
    let metadata = file.metadata()?;
    if directory != metadata.is_dir() || (!directory && !metadata.is_file()) {
        return Err(ByteStoreError::NotPrivate);
    }
    if metadata.uid() != rustix::process::geteuid().as_raw()
        || metadata.mode() & 0o777 != if directory { 0o700 } else { 0o600 }
        || (!directory && metadata.nlink() != 1)
    {
        return Err(ByteStoreError::NotPrivate);
    }
    Ok(())
}
