//! Descriptor-relative local writes for server configuration and secrets.
use crate::error::{Error, Result};
use rustix::fs::{Mode, OFlags};
use std::os::unix::fs::MetadataExt;
use std::{
    cell::RefCell,
    fs::File,
    io::{Read, Write},
    path::{Component, Path, PathBuf},
};
use zeroize::Zeroizing;
// RawMode is u32 on Linux and u16 on Darwin.
#[allow(clippy::useless_conversion)]
pub(super) fn raw_mode(mode: u32) -> Result<Mode> {
    let raw: rustix::fs::RawMode = mode.try_into().map_err(|_| Error::Io)?;
    Ok(Mode::from_raw_mode(raw))
}
fn owner_allowed(effective_uid: u32, owner_uid: u32, root_read: bool) -> bool {
    owner_uid == effective_uid || (root_read && owner_uid == 0)
}
fn mode_allowed(effective_uid: u32, mode: u32, host: bool, private: bool) -> bool {
    (!(host || effective_uid == 0) || mode & 0o022 == 0) && (!private || mode & 0o077 == 0)
}
thread_local! {static SHARED_SOURCE:RefCell<Option<PathBuf>>=const{RefCell::new(None)};}
pub(super) struct SourceScope(Option<PathBuf>);
impl Drop for SourceScope {
    fn drop(&mut self) {
        SHARED_SOURCE.with(|p| *p.borrow_mut() = self.0.take());
    }
}
/// Only an explicit registered, nonprivileged working tree opts into trusting
/// shared source files already executed by Docker/Git. Credential/host storage
/// does not use this scope.
pub(super) fn source_scope(path: &Path) -> Result<SourceScope> {
    if rustix::process::geteuid().is_root() {
        let guard = strict_scope();
        directory(path, false)?;
        return Ok(guard);
    }
    let previous = SHARED_SOURCE.with(|p| p.borrow_mut().replace(path.to_path_buf()));
    let guard = SourceScope(previous);
    directory(path, false)?;
    Ok(guard)
}
pub(super) fn strict_scope() -> SourceScope {
    SourceScope(SHARED_SOURCE.with(|p| p.borrow_mut().take()))
}
fn shared(path: &Path, host: bool) -> bool {
    !host
        && !rustix::process::geteuid().is_root()
        && SHARED_SOURCE.with(|scope| {
            scope.borrow().as_ref().is_some_and(|root| {
                if let Ok(relative) = path.strip_prefix(root)
                    && (relative.starts_with(".openmates") || relative.starts_with("backups"))
                {
                    return false;
                }
                path.starts_with(root) || root.starts_with(path)
            })
        })
}

pub(super) fn directory(path: &Path, create: bool) -> Result<File> {
    directory_policy(path, create, false)
}
fn public_directory_allowed(uid: u32, mode: u32, effective_uid: u32) -> bool {
    uid == effective_uid && mode & 0o7777 == 0o755
}
/// A container-readable bind directory is separate from private application
/// state. Set permissions only on a newly created inode; existing custom,
/// private or foreign directory permissions are never widened.
pub(super) fn public_directory(path: &Path) -> Result<File> {
    let parent = directory(path.parent().ok_or(Error::Io)?, true)?;
    let name = path.file_name().ok_or(Error::Io)?;
    let created = match rustix::fs::mkdirat(&parent, name, Mode::from_raw_mode(0o755)) {
        Ok(()) => true,
        Err(rustix::io::Errno::EXIST) => false,
        Err(_) => return Err(Error::Io),
    };
    let dir = File::from(
        rustix::fs::openat(
            &parent,
            name,
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::empty(),
        )
        .map_err(|_| Error::Io)?,
    );
    let metadata = dir.metadata()?;
    let effective_uid = rustix::process::geteuid().as_raw();
    if metadata.uid() != effective_uid {
        return Err(Error::Io);
    }
    if created {
        rustix::fs::fchmod(&dir, Mode::from_raw_mode(0o755)).map_err(|_| Error::Io)?;
        parent.sync_all()?;
    } else if !public_directory_allowed(metadata.uid(), metadata.mode(), effective_uid) {
        return Err(Error::Invalid(
            "Container configuration directory requires owner-controlled 0755 permissions; existing permissions were preserved.",
        ));
    }
    Ok(dir)
}
fn directory_policy(path: &Path, create: bool, root_read: bool) -> Result<File> {
    if !path.is_absolute() {
        return Err(Error::Invalid("Server paths must be absolute."));
    }
    let mut dir = File::from(
        rustix::fs::open(
            "/",
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC,
            Mode::empty(),
        )
        .map_err(|_| Error::Io)?,
    );
    let mut traversed = PathBuf::from("/");
    for component in path.components() {
        let Component::Normal(name) = component else {
            if matches!(component, Component::RootDir) {
                continue;
            }
            return Err(Error::Invalid("Server paths must be normalized."));
        };
        let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
        traversed.push(name);
        let fd = match rustix::fs::openat(&dir, name, flags, Mode::empty()) {
            Ok(fd) => fd,
            Err(rustix::io::Errno::NOENT) if create => {
                rustix::fs::mkdirat(&dir, name, Mode::from_raw_mode(0o700))
                    .map_err(|_| Error::Io)?;
                rustix::fs::openat(&dir, name, flags, Mode::empty()).map_err(|_| Error::Io)?
            }
            Err(_) => return Err(Error::Io),
        };
        dir = File::from(fd);
        let ancestor = dir.metadata()?;
        // Path-based system tools subsequently resolve their working directory.
        // Reject replaceable ancestors; root-owned sticky temporary roots are
        // safe because another user cannot rename this user's child entry.
        let trusted_temporary = ancestor.uid() == 0 && ancestor.mode() & 0o1000 != 0;
        if ancestor.mode() & 0o022 != 0 && !trusted_temporary && !shared(&traversed, root_read)
            || ancestor.uid() != 0 && ancestor.uid() != rustix::process::geteuid().as_raw()
        {
            return Err(Error::Invalid(
                "Server paths must not traverse directories writable or owned by another user.",
            ));
        }
        if name == ".openmates" && ancestor.mode() & 0o777 != 0o700 {
            return Err(Error::Invalid(
                "Server metadata must remain in a private 0700 directory.",
            ));
        }
    }
    let meta = dir.metadata()?;
    if !owner_allowed(rustix::process::geteuid().as_raw(), meta.uid(), root_read)
        || meta.mode() & 0o022 != 0 && !shared(path, root_read)
    {
        return Err(Error::Invalid(
            "Server directory must be owned by this user and not writable by other users.",
        ));
    }
    Ok(dir)
}
pub(super) fn read(path: &Path, limit: u64) -> Result<Vec<u8>> {
    read_policy(path, limit, false, false).map(|mut snapshot| std::mem::take(&mut *snapshot.bytes))
}
pub(super) fn private_read(path: &Path, limit: u64) -> Result<Vec<u8>> {
    read_policy(path, limit, false, true).map(|mut snapshot| std::mem::take(&mut *snapshot.bytes))
}
pub(super) fn read_with_mode(path: &Path, limit: u64) -> Result<(Vec<u8>, u32)> {
    read_policy(path, limit, false, false)
        .map(|mut snapshot| (std::mem::take(&mut *snapshot.bytes), snapshot.mode))
}
#[derive(Clone)]
pub(super) struct Snapshot {
    pub bytes: Zeroizing<Vec<u8>>,
    pub mode: u32,
    pub uid: u32,
    pub gid: u32,
    pub device: u64,
    pub inode: u64,
}
impl Snapshot {
    pub(super) fn matches(&self, other: &Self) -> bool {
        self.bytes == other.bytes
            && self.mode == other.mode
            && self.uid == other.uid
            && self.gid == other.gid
            && self.device == other.device
            && self.inode == other.inode
    }
}
pub(super) fn host_snapshot(path: &Path, limit: u64) -> Result<Snapshot> {
    read_policy(path, limit, true, false)
}
pub(super) fn snapshot(path: &Path, limit: u64) -> Result<Snapshot> {
    read_policy(path, limit, false, false)
}
fn read_policy(path: &Path, limit: u64, root_read: bool, private: bool) -> Result<Snapshot> {
    let dir = directory_policy(path.parent().ok_or(Error::Io)?, false, root_read)?;
    let file = File::from(
        rustix::fs::openat(
            &dir,
            path.file_name().ok_or(Error::Io)?,
            OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::empty(),
        )
        .map_err(|_| Error::Io)?,
    );
    let meta = file.metadata()?;
    if !meta.is_file()
        || meta.nlink() != 1
        || !owner_allowed(rustix::process::geteuid().as_raw(), meta.uid(), root_read)
        || meta.len() > limit
        || !mode_allowed(
            rustix::process::geteuid().as_raw(),
            meta.mode(),
            root_read,
            private,
        )
    {
        return Err(Error::Io);
    }
    let mut bytes = Vec::new();
    file.take(limit + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err(Error::Io);
    }
    Ok(Snapshot {
        bytes: Zeroizing::new(bytes),
        mode: meta.mode() & 0o777,
        uid: meta.uid(),
        gid: meta.gid(),
        device: meta.dev(),
        inode: meta.ino(),
    })
}
pub(super) fn write_identity(path: &Path, bytes: &[u8], identity: Option<&Snapshot>) -> Result<()> {
    let mode = identity.map(|s| s.mode).unwrap_or(0o644);
    publish(path, mode, |file| {
        if let Some(identity) = identity {
            rustix::fs::fchown(
                &*file,
                Some(rustix::fs::Uid::from_raw(identity.uid)),
                Some(rustix::fs::Gid::from_raw(identity.gid)),
            )
            .map_err(|_| Error::Io)?;
            rustix::fs::fchmod(&*file, raw_mode(identity.mode)?).map_err(|_| Error::Io)?;
        }
        file.write_all(bytes)?;
        Ok(())
    })
}
pub(super) struct HostLock(File);
impl HostLock {
    pub(super) fn acquire(path: &Path) -> Result<Self> {
        let _strict = strict_scope();
        let parent = directory(path.parent().ok_or(Error::Io)?, false)?;
        let name = format!(
            ".{}.openmates-transaction.lock",
            path.file_name().ok_or(Error::Io)?.to_string_lossy()
        );
        let file = File::from(
            rustix::fs::openat(
                &parent,
                name.as_str(),
                OFlags::RDWR | OFlags::CREATE | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::from_raw_mode(0o600),
            )
            .map_err(|_| Error::Io)?,
        );
        let meta = file.metadata()?;
        if !meta.is_file()
            || meta.nlink() != 1
            || !owner_allowed(rustix::process::geteuid().as_raw(), meta.uid(), false)
            || meta.mode() & 0o777 != 0o600
        {
            return Err(Error::Io);
        }
        fs2::FileExt::try_lock_exclusive(&file).map_err(|_| Error::Locked)?;
        Ok(Self(file))
    }
}
impl Drop for HostLock {
    fn drop(&mut self) {
        let _ = fs2::FileExt::unlock(&self.0);
    }
}
pub(super) fn write(path: &Path, bytes: &[u8], mode: u32) -> Result<()> {
    publish(path, mode, |file| {
        file.write_all(bytes)?;
        Ok(())
    })
}
/// Bind-mounted public configuration must be readable by the container UID.
/// The enclosing installation root remains private; secrets never use this.
pub(super) fn public_write(path: &Path, bytes: &[u8]) -> Result<()> {
    let dir = directory(path.parent().ok_or(Error::Io)?, true)?;
    rustix::fs::fchmod(&dir, Mode::from_raw_mode(0o755)).map_err(|_| Error::Io)?;
    write(path, bytes, 0o644)
}
pub(super) fn metrics(root: &Path) -> Result<()> {
    let dir = directory(&root.join(".openmates/runtime-health/metrics"), true)?;
    rustix::fs::fchmod(&dir, Mode::from_raw_mode(0o755)).map_err(|_| Error::Io)?;
    Ok(())
}
pub(super) fn publish(
    path: &Path,
    mode: u32,
    writer: impl FnOnce(&mut File) -> Result<()>,
) -> Result<()> {
    let dir = directory(path.parent().ok_or(Error::Io)?, true)?;
    let name = path.file_name().ok_or(Error::Io)?;
    match rustix::fs::statat(&dir, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(stat) => {
            if rustix::fs::FileType::from_raw_mode(stat.st_mode)
                != rustix::fs::FileType::RegularFile
                || !owner_allowed(rustix::process::geteuid().as_raw(), stat.st_uid, false)
                || stat.st_nlink != 1
            {
                return Err(Error::Io);
            }
        }
        Err(rustix::io::Errno::NOENT) => {}
        Err(_) => return Err(Error::Io),
    }
    let temp = format!(".native-{}.tmp", uuid::Uuid::new_v4());
    let result = (|| {
        let mut file = File::from(
            rustix::fs::openat(
                &dir,
                temp.as_str(),
                OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                raw_mode(mode)?,
            )
            .map_err(|_| Error::Io)?,
        );
        rustix::fs::fchmod(&file, raw_mode(mode)?).map_err(|_| Error::Io)?;
        writer(&mut file)?;
        file.sync_all()?;
        rustix::fs::renameat(&dir, temp.as_str(), &dir, name).map_err(|_| Error::Io)?;
        dir.sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        let _ = rustix::fs::unlinkat(&dir, temp.as_str(), rustix::fs::AtFlags::empty());
    }
    result
}
pub(super) struct Lock {
    native: File,
    dir: File,
    token: Vec<u8>,
}
impl Lock {
    pub(super) fn acquire(root: &Path) -> Result<Self> {
        let dir = directory(&root.join(".openmates"), true)?;
        let file = File::from(
            rustix::fs::openat(
                &dir,
                "native-server.lock",
                OFlags::RDWR | OFlags::CREATE | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::from_raw_mode(0o600),
            )
            .map_err(|_| Error::Io)?,
        );
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.nlink() != 1
            || !owner_allowed(rustix::process::geteuid().as_raw(), metadata.uid(), false)
            || metadata.mode() & 0o777 != 0o600
        {
            return Err(Error::Io);
        }
        fs2::FileExt::try_lock_exclusive(&file).map_err(|_| Error::Locked)?;
        // The legacy updater uses this same exclusive-create marker. Holding
        // both mechanisms prevents a native update from racing its refresh.
        // Stale markers require deliberate operator reconciliation.
        let mut marker = File::from(
            rustix::fs::openat(
                &dir,
                "server-update.lock",
                OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::from_raw_mode(0o600),
            )
            .map_err(|e| {
                if e == rustix::io::Errno::EXIST {
                    Error::Locked
                } else {
                    Error::Io
                }
            })?,
        );
        let token = format!("{}:{}", std::process::id(), uuid::Uuid::new_v4()).into_bytes();
        marker.write_all(&token)?;
        marker.sync_all()?;
        dir.sync_all()?;
        Ok(Self {
            native: file,
            dir,
            token,
        })
    }
}
impl Drop for Lock {
    fn drop(&mut self) {
        if let Ok(fd) = rustix::fs::openat(
            &self.dir,
            "server-update.lock",
            OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::empty(),
        ) {
            let file = File::from(fd);
            let mut token = Vec::new();
            if file.take(256).read_to_end(&mut token).is_ok() && token == self.token {
                let _ = rustix::fs::unlinkat(
                    &self.dir,
                    "server-update.lock",
                    rustix::fs::AtFlags::empty(),
                );
                let _ = self.dir.sync_all();
            }
        }
        let _ = fs2::FileExt::unlock(&self.native);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    #[test]
    fn image_compat_public_directory_is_readable_and_preserves_existing_secret_files() {
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let path = root.path().join("config/providers");
        let dir = public_directory(&path).unwrap();
        assert_eq!(dir.metadata().unwrap().mode() & 0o7777, 0o755);
        let secret = path.join("local-ai-models.yml");
        write(&secret, b"synthetic-private", 0o600).unwrap();
        let before = std::fs::metadata(&secret).unwrap();
        let before_dir = dir.metadata().unwrap();
        public_directory(&path).unwrap();
        let after = std::fs::metadata(&secret).unwrap();
        assert_eq!((before.ino(), before.mode()), (after.ino(), after.mode()));
        assert_eq!(std::fs::read(&secret).unwrap(), b"synthetic-private");
        assert_eq!(
            public_directory(&path).unwrap().metadata().unwrap().ino(),
            before_dir.ino()
        );
        assert_eq!(
            std::fs::metadata(root.path()).unwrap().mode() & 0o7777,
            0o700
        );
        assert!(public_directory_allowed(1001, 0o755, 1001));
        assert!(!public_directory_allowed(1000, 0o755, 1001));
        assert!(!public_directory_allowed(1001, 0o755, 0));
    }
    #[test]
    fn image_compat_public_directory_refuses_private_custom_and_symlink_entries_without_changes() {
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let path = root.path().join("providers");
        directory(&path, true).unwrap();
        write(&path.join("private.yml"), b"synthetic-private", 0o600).unwrap();
        for mode in [0o700, 0o750, 0o555, 0o775, 0o1755] {
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode)).unwrap();
            assert!(public_directory(&path).is_err());
            assert_eq!(std::fs::metadata(&path).unwrap().mode() & 0o7777, mode);
            assert_eq!(
                std::fs::read(path.join("private.yml")).unwrap(),
                b"synthetic-private"
            );
        }
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        let link = root.path().join("link");
        std::os::unix::fs::symlink(&path, &link).unwrap();
        assert!(public_directory(&link).is_err());
        assert_eq!(std::fs::metadata(&path).unwrap().mode() & 0o7777, 0o700);
        assert_eq!(
            std::fs::metadata(path.join("private.yml")).unwrap().mode() & 0o7777,
            0o600
        );
        assert!(link.symlink_metadata().unwrap().is_symlink());
    }
    #[test]
    #[allow(clippy::useless_conversion)]
    fn native_mode_conversion_preserves_posix_bits_and_rejects_overflow() {
        for bits in [0, 0o600, 0o700, 0o755, 0o7777] {
            assert_eq!(u32::from(raw_mode(bits).unwrap().as_raw_mode()), bits);
        }
        let highest = u32::from(rustix::fs::RawMode::MAX);
        if let Some(overflow) = highest.checked_add(1) {
            assert!(raw_mode(overflow).is_err());
        }
    }
    #[test]
    fn privileged_owner_policy_is_independent_of_test_process_identity() {
        assert!(owner_allowed(0, 0, false));
        assert!(owner_allowed(0, 0, true));
        assert!(!owner_allowed(0, 1000, false));
        assert!(!owner_allowed(0, 1000, true));
        assert!(owner_allowed(1000, 1000, false));
        assert!(!owner_allowed(1000, 1001, true));
        assert!(owner_allowed(1000, 0, true));
        assert!(!owner_allowed(1000, 0, false));
        assert!(mode_allowed(0, 0o644, false, false));
        assert!(!mode_allowed(0, 0o664, false, false));
        assert!(!mode_allowed(1000, 0o664, true, false));
        assert!(mode_allowed(1000, 0o664, false, false));
        assert!(!mode_allowed(1000, 0o640, false, true));
    }
    #[test]
    fn explicit_nonprivileged_source_scope_preserves_shared_code_but_host_and_private_checks_stay_strict()
     {
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let repo = root.path().join("repo");
        std::fs::create_dir(&repo).unwrap();
        std::fs::set_permissions(&repo, std::fs::Permissions::from_mode(0o775)).unwrap();
        std::fs::write(repo.join(".env"), b"fixture").unwrap();
        std::fs::set_permissions(repo.join(".env"), std::fs::Permissions::from_mode(0o600))
            .unwrap();
        assert!(directory(&repo, false).is_err());
        if rustix::process::geteuid().is_root() {
            assert!(source_scope(&repo).is_err());
            return;
        }
        {
            let _source = source_scope(&repo).unwrap();
            assert_eq!(private_read(&repo.join(".env"), 64).unwrap(), b"fixture");
            assert!(host_snapshot(&repo.join(".env"), 64).is_err());
            {
                let _strict = strict_scope();
                assert!(directory(&repo, false).is_err());
            }
            assert!(directory(&repo, false).is_ok());
            std::fs::set_permissions(repo.join(".env"), std::fs::Permissions::from_mode(0o664))
                .unwrap();
            assert!(private_read(&repo.join(".env"), 64).is_err());
            assert_eq!(
                std::fs::metadata(&repo).unwrap().permissions().mode() & 0o777,
                0o775
            );
        }
        assert!(directory(&repo, false).is_err());
    }
}
