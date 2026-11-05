//! Prepare only canonical source bind mountpoints before Docker can create them
//! as root. Existing container-owned data directories are never chmod/chowned.
use super::*;
use rustix::fs::{Mode, OFlags};
use std::fs::File;

const DIRECTORIES: &[(&str, u32)] = &[
    ("backend/core/vault/setup/data", 0o700),
    ("backend/core/api/logs", 0o755),
    ("backend/core/directus/uploads", 0o755),
    (".cursor", 0o755),
    ("test-results", 0o755),
];
pub(super) fn prepare(c: &Configuration) -> Result<()> {
    if c.install_mode != "source" || c.server_role != "core" {
        return Ok(());
    }
    for (relative, mode) in DIRECTORIES {
        let path = c.install_path.join(relative);
        // All ancestors are executable source already selected by the caller;
        // retain their ownership/no-follow checks and their existing modes.
        let parent = fs::directory(path.parent().ok_or(Error::Io)?, false)?;
        let name = path.file_name().ok_or(Error::Io)?;
        let created = match rustix::fs::mkdirat(&parent, name, fs::raw_mode(*mode)?) {
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
        if created {
            // Only a newly created, pinned inode may receive the requested
            // mode. Never widen an existing private/shared directory.
            let meta = rustix::fs::fstat(&dir).map_err(|_| Error::Io)?;
            if meta.st_uid != rustix::process::geteuid().as_raw() {
                return Err(Error::Io);
            }
            rustix::fs::fchmod(&dir, fs::raw_mode(*mode)?).map_err(|_| Error::Io)?;
            parent.sync_all()?;
        }
    }
    // The read-only Vault code mount must already contain this regular file
    // target. Docker must not create a directory or follow a symlink for it.
    let _placeholder = Zeroizing::new(fs::read(
        &c.install_path.join("backend/core/vault/setup/dotenv"),
        4 * 1024 * 1024,
    )?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::{MetadataExt, PermissionsExt, symlink};
    fn fixture() -> (tempfile::TempDir, Configuration) {
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = root.path().join("install");
        c.install_mode = "source".into();
        for parent in [
            "backend/core/vault/setup",
            "backend/core/api",
            "backend/core/directus",
        ] {
            fs::directory(&c.install_path.join(parent), true).unwrap();
        }
        fs::write(
            &c.install_path.join("backend/core/vault/setup/dotenv"),
            b"",
            0o600,
        )
        .unwrap();
        (root, c)
    }
    #[test]
    fn canonical_missing_mountpoints_are_owned_and_existing_modes_stay_unchanged() {
        let (_root, c) = fixture();
        prepare(&c).unwrap();
        for (relative, mode) in DIRECTORIES {
            let metadata = std::fs::metadata(c.install_path.join(relative)).unwrap();
            assert_eq!(metadata.uid(), rustix::process::geteuid().as_raw());
            assert_eq!(metadata.mode() & 0o777, *mode);
        }
        let logs = c.install_path.join("backend/core/api/logs");
        std::fs::set_permissions(&logs, std::fs::Permissions::from_mode(0o700)).unwrap();
        fs::write(&logs.join("fixture"), b"keep", 0o600).unwrap();
        prepare(&c).unwrap();
        assert_eq!(std::fs::metadata(&logs).unwrap().mode() & 0o777, 0o700);
        assert_eq!(std::fs::read(logs.join("fixture")).unwrap(), b"keep");
    }
    #[test]
    fn symlink_mountpoints_and_vault_placeholder_are_refused_without_touching_target() {
        let (root, c) = fixture();
        let outside = root.path().join("outside");
        fs::directory(&outside, true).unwrap();
        fs::write(&outside.join("sentinel"), b"keep", 0o600).unwrap();
        symlink(
            &outside,
            c.install_path.join("backend/core/vault/setup/data"),
        )
        .unwrap();
        assert!(prepare(&c).is_err());
        std::fs::remove_file(c.install_path.join("backend/core/vault/setup/data")).unwrap();
        let placeholder = c.install_path.join("backend/core/vault/setup/dotenv");
        std::fs::remove_file(&placeholder).unwrap();
        symlink(outside.join("sentinel"), &placeholder).unwrap();
        assert!(prepare(&c).is_err());
        assert_eq!(std::fs::read(outside.join("sentinel")).unwrap(), b"keep");
    }
}
