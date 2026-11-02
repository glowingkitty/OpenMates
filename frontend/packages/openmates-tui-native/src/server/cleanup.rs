//! Unlink-only installation cleanup. Inventory every directory and effective
//! unlink permission before removing any entry; never read file contents,
//! follow symlinks, cross a mount, or chmod/chown a foreign-owned entry.
use super::*;
use rustix::fs::{Access, AtFlags, FileType, Mode, OFlags, Stat};
use std::{ffi::OsString, fs::File, os::unix::ffi::OsStrExt};
const MAX_ENTRIES: usize = 500_000;
const MAX_DEPTH: usize = 128;
pub(super) struct Failure {
    relative: PathBuf,
    reason: &'static str,
    metadata: Option<Box<Stat>>,
}
impl Failure {
    fn new(path: &Path, reason: &'static str, metadata: Option<Stat>) -> Self {
        Self {
            relative: path.into(),
            reason,
            metadata: metadata.map(Box::new),
        }
    }
    pub(super) fn output(self, c: &Configuration, runtime_stopped: bool) -> Value {
        let details=self.metadata.map(|s|json!({"uid":s.st_uid,"gid":s.st_gid,"mode":format!("{:04o}",s.st_mode & 0o7777),"type":if FileType::from_raw_mode(s.st_mode)==FileType::Directory {"directory"}else if FileType::from_raw_mode(s.st_mode)==FileType::Symlink {"symlink"}else{"file"}}));
        json!({"command":"uninstall","status":"degraded","path":c.install_path,"phase":"installation_cleanup","reason":self.reason,"obstruction":{"relativePath":self.relative.to_string_lossy(),"metadata":details},"runtimeStopped":runtime_stopped,"installationRegistrationPreserved":true,"cleanupComplete":false})
    }
}
type CleanupResult<T> = std::result::Result<T, Failure>;
struct Node {
    name: OsString,
    metadata: Stat,
    children: Vec<Node>,
}
pub(super) struct Plan {
    parent: File,
    root: File,
    tree: Node,
}
fn same(a: &Stat, b: &Stat) -> bool {
    a.st_dev == b.st_dev
        && a.st_ino == b.st_ino
        && FileType::from_raw_mode(a.st_mode) == FileType::from_raw_mode(b.st_mode)
}
fn sticky_allows(uid: u32, parent: &Stat, child: &Stat) -> bool {
    uid == 0 || parent.st_mode & 0o1000 == 0 || parent.st_uid == uid || child.st_uid == uid
}
fn can_prepare_write(uid: u32, owner: u32, already_writable: bool) -> bool {
    uid == owner || already_writable
}
fn mounted(root: &Stat, entry: &Stat) -> bool {
    root.st_dev != entry.st_dev
}
fn entry_metadata(parent: &File, name: &std::ffi::OsStr) -> rustix::io::Result<Stat> {
    #[cfg(target_os = "linux")]
    {
        // O_PATH observes metadata without opening the payload (including
        // devices/FIFOs). NO_XDEV also rejects same-device file bind mounts;
        // comparing st_dev alone cannot identify those. O_PATH|NOFOLLOW may
        // pin a final symlink under NO_SYMLINKS without resolving its target.
        let fd = rustix::fs::openat2(
            parent,
            name,
            OFlags::PATH | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::empty(),
            rustix::fs::ResolveFlags::BENEATH
                | rustix::fs::ResolveFlags::NO_SYMLINKS
                | rustix::fs::ResolveFlags::NO_XDEV,
        )?;
        rustix::fs::fstat(fd)
    }
    #[cfg(not(target_os = "linux"))]
    rustix::fs::statat(parent, name, AtFlags::SYMLINK_NOFOLLOW)
}
fn metadata_failure(path: &Path, error: rustix::io::Errno) -> Failure {
    Failure::new(
        path,
        if error == rustix::io::Errno::XDEV {
            "mounted_child_refused"
        } else {
            "entry_metadata_unavailable"
        },
        None,
    )
}
fn directory(parent: &File, name: &std::ffi::OsStr) -> rustix::io::Result<File> {
    let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
    #[cfg(target_os = "linux")]
    let fd = rustix::fs::openat2(
        parent,
        name,
        flags,
        Mode::empty(),
        rustix::fs::ResolveFlags::BENEATH
            | rustix::fs::ResolveFlags::NO_SYMLINKS
            | rustix::fs::ResolveFlags::NO_XDEV,
    )?;
    #[cfg(not(target_os = "linux"))]
    let fd = rustix::fs::openat(parent, name, flags, Mode::empty())?;
    Ok(File::from(fd))
}
fn writable(dir: &File) -> bool {
    rustix::fs::accessat(
        dir,
        ".",
        Access::WRITE_OK | Access::EXEC_OK,
        AtFlags::EACCESS,
    )
    .is_ok()
}
fn names(dir: &File, path: &Path) -> CleanupResult<Vec<OsString>> {
    let entries = rustix::fs::Dir::read_from(dir).map_err(|_| {
        Failure::new(
            path,
            "directory_inventory_unavailable",
            rustix::fs::fstat(dir).ok(),
        )
    })?;
    let mut names = Vec::new();
    for entry in entries {
        let entry =
            entry.map_err(|_| Failure::new(path, "directory_inventory_unavailable", None))?;
        let raw = entry.file_name().to_bytes();
        if raw != b"." && raw != b".." {
            names.push(std::ffi::OsStr::from_bytes(raw).to_os_string());
        }
        if names.len() > MAX_ENTRIES {
            return Err(Failure::new(path, "cleanup_inventory_limit", None));
        }
    }
    names.sort();
    Ok(names)
}
fn inspect(
    parent: &File,
    name: OsString,
    path: &Path,
    root: &Stat,
    remaining: &mut usize,
    depth: usize,
) -> CleanupResult<Node> {
    if *remaining == 0 || depth > MAX_DEPTH {
        return Err(Failure::new(path, "cleanup_inventory_limit", None));
    }
    *remaining -= 1;
    let metadata = entry_metadata(parent, &name).map_err(|error| metadata_failure(path, error))?;
    if mounted(root, &metadata) {
        return Err(Failure::new(path, "mounted_child_refused", Some(metadata)));
    }
    let parent_meta = rustix::fs::fstat(parent)
        .map_err(|_| Failure::new(path, "entry_metadata_unavailable", Some(metadata)))?;
    if !sticky_allows(rustix::process::geteuid().as_raw(), &parent_meta, &metadata) {
        return Err(Failure::new(
            path,
            "parent_unlink_permission_required",
            Some(metadata),
        ));
    }
    let mut children = Vec::new();
    if FileType::from_raw_mode(metadata.st_mode) == FileType::Directory {
        let dir = directory(parent, &name).map_err(|error| {
            Failure::new(
                path,
                if error == rustix::io::Errno::XDEV {
                    "mounted_child_refused"
                } else {
                    "directory_inventory_permission_required"
                },
                Some(metadata),
            )
        })?;
        let pinned = rustix::fs::fstat(&dir)
            .map_err(|_| Failure::new(path, "entry_metadata_unavailable", Some(metadata)))?;
        if !same(&metadata, &pinned) {
            return Err(Failure::new(
                path,
                "installation_tree_changed",
                Some(metadata),
            ));
        }
        let names = names(&dir, path)?;
        let readonly = rustix::fs::fstatvfs(&dir)
            .map_err(|_| Failure::new(path, "filesystem_metadata_unavailable", Some(metadata)))?
            .f_flag
            .contains(rustix::fs::StatVfsMountFlags::RDONLY);
        if readonly
            || !names.is_empty()
                && !can_prepare_write(
                    rustix::process::geteuid().as_raw(),
                    metadata.st_uid,
                    writable(&dir),
                )
        {
            return Err(Failure::new(
                path,
                "directory_unlink_permission_required",
                Some(metadata),
            ));
        }
        for name in names {
            children.push(inspect(
                &dir,
                name.clone(),
                &path.join(&name),
                root,
                remaining,
                depth + 1,
            )?);
        }
    }
    Ok(Node {
        name,
        metadata,
        children,
    })
}
fn verify(parent: &File, node: &Node, path: &Path) -> CleanupResult<()> {
    let metadata =
        entry_metadata(parent, &node.name).map_err(|error| metadata_failure(path, error))?;
    if !same(&metadata, &node.metadata) {
        return Err(Failure::new(
            path,
            "installation_tree_changed",
            Some(metadata),
        ));
    }
    let parent_meta = rustix::fs::fstat(parent)
        .map_err(|_| Failure::new(path, "entry_metadata_unavailable", Some(metadata)))?;
    if !sticky_allows(rustix::process::geteuid().as_raw(), &parent_meta, &metadata) {
        return Err(Failure::new(
            path,
            "parent_unlink_permission_required",
            Some(metadata),
        ));
    }
    if FileType::from_raw_mode(metadata.st_mode) == FileType::Directory {
        let dir = directory(parent, &node.name).map_err(|_| {
            Failure::new(
                path,
                "directory_inventory_permission_required",
                Some(metadata),
            )
        })?;
        let pinned = rustix::fs::fstat(&dir)
            .map_err(|_| Failure::new(path, "entry_metadata_unavailable", Some(metadata)))?;
        if !same(&metadata, &pinned) {
            return Err(Failure::new(
                path,
                "installation_tree_changed",
                Some(metadata),
            ));
        }
        let actual = names(&dir, path)?;
        if actual
            != node
                .children
                .iter()
                .map(|n| n.name.clone())
                .collect::<Vec<_>>()
        {
            return Err(Failure::new(
                path,
                "installation_tree_changed",
                Some(metadata),
            ));
        }
        if !actual.is_empty()
            && !can_prepare_write(
                rustix::process::geteuid().as_raw(),
                metadata.st_uid,
                writable(&dir),
            )
        {
            return Err(Failure::new(
                path,
                "directory_unlink_permission_required",
                Some(metadata),
            ));
        }
        for child in &node.children {
            verify(&dir, child, &path.join(&child.name))?;
        }
    }
    Ok(())
}
fn remove(parent: &File, node: &Node, path: &Path) -> CleanupResult<()> {
    let metadata =
        entry_metadata(parent, &node.name).map_err(|error| metadata_failure(path, error))?;
    if !same(&metadata, &node.metadata) {
        return Err(Failure::new(
            path,
            "installation_tree_changed",
            Some(metadata),
        ));
    }
    let directory_type = FileType::from_raw_mode(metadata.st_mode) == FileType::Directory;
    if directory_type {
        let dir = directory(parent, &node.name).map_err(|_| {
            Failure::new(
                path,
                "directory_inventory_permission_required",
                Some(metadata),
            )
        })?;
        let pinned = rustix::fs::fstat(&dir)
            .map_err(|_| Failure::new(path, "entry_metadata_unavailable", Some(metadata)))?;
        if !same(&metadata, &pinned) {
            return Err(Failure::new(
                path,
                "installation_tree_changed",
                Some(metadata),
            ));
        }
        if metadata.st_uid == rustix::process::geteuid().as_raw() && !writable(&dir) {
            // Only owner permissions inside the explicitly selected tree may
            // change. Never touch mode/ownership of regular files or foreigners.
            rustix::fs::fchmod(&dir, Mode::from_raw_mode(metadata.st_mode | 0o700)).map_err(
                |_| Failure::new(path, "directory_unlink_permission_required", Some(metadata)),
            )?;
        }
        // Retain management inputs until all ordinary entries are removed. A
        // whole-tree permission failure is caught by preflight; this ordering
        // also preserves recovery inputs during an unexpected early I/O error.
        let mut children = node.children.iter().collect::<Vec<_>>();
        children.sort_by_key(|child| match child.name.to_str() {
            Some(".env") => 2,
            Some(".openmates") => 1,
            _ => 0,
        });
        for child in children {
            remove(&dir, child, &path.join(&child.name))?;
        }
    }
    let current =
        entry_metadata(parent, &node.name).map_err(|error| metadata_failure(path, error))?;
    if !same(&current, &node.metadata) {
        return Err(Failure::new(
            path,
            "installation_tree_changed",
            Some(current),
        ));
    }
    rustix::fs::unlinkat(
        parent,
        &node.name,
        if directory_type {
            AtFlags::REMOVEDIR
        } else {
            AtFlags::empty()
        },
    )
    .map_err(|_| Failure::new(path, "entry_unlink_failed", Some(current)))?;
    Ok(())
}
impl Plan {
    pub(super) fn prepare(path: &Path) -> CleanupResult<Self> {
        let root = fs::directory(path, false)
            .map_err(|_| Failure::new(Path::new("."), "installation_root_untrusted", None))?;
        let metadata = rustix::fs::fstat(&root)
            .map_err(|_| Failure::new(Path::new("."), "entry_metadata_unavailable", None))?;
        let parent = File::from(
            rustix::fs::open(
                path.parent().ok_or_else(|| {
                    Failure::new(
                        Path::new("."),
                        "installation_root_untrusted",
                        Some(metadata),
                    )
                })?,
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::empty(),
            )
            .map_err(|_| {
                Failure::new(
                    Path::new("."),
                    "parent_unlink_permission_required",
                    Some(metadata),
                )
            })?,
        );
        if !writable(&parent) {
            return Err(Failure::new(
                Path::new("."),
                "parent_unlink_permission_required",
                Some(metadata),
            ));
        }
        let name = path
            .file_name()
            .ok_or_else(|| {
                Failure::new(
                    Path::new("."),
                    "installation_root_untrusted",
                    Some(metadata),
                )
            })?
            .to_os_string();
        let mut remaining = MAX_ENTRIES;
        let tree = inspect(&parent, name, Path::new("."), &metadata, &mut remaining, 0)?;
        if !same(&tree.metadata, &metadata) {
            return Err(Failure::new(
                Path::new("."),
                "installation_tree_changed",
                Some(metadata),
            ));
        }
        Ok(Self { parent, root, tree })
    }
    pub(super) fn remove(self) -> CleanupResult<()> {
        let current = rustix::fs::fstat(&self.root)
            .map_err(|_| Failure::new(Path::new("."), "installation_tree_changed", None))?;
        if !same(&current, &self.tree.metadata) {
            return Err(Failure::new(
                Path::new("."),
                "installation_tree_changed",
                Some(current),
            ));
        }
        // Whole-tree recheck follows Docker shutdown and precedes all unlinks.
        verify(&self.parent, &self.tree, Path::new("."))?;
        remove(&self.parent, &self.tree, Path::new("."))?;
        self.parent
            .sync_all()
            .map_err(|_| Failure::new(Path::new("."), "cleanup_sync_failed", None))?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::{MetadataExt, PermissionsExt, symlink};
    fn fixture() -> tempfile::TempDir {
        tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap()
    }
    fn prepare(path: &Path) -> Plan {
        match Plan::prepare(path) {
            Ok(plan) => plan,
            Err(failure) => panic!("cleanup preflight failed: {}", failure.reason),
        }
    }
    #[test]
    fn unlink_only_keeps_outside_symlink_and_hardlink_targets_unchanged() {
        let root = fixture();
        let target = root.path().join("outside");
        std::fs::write(&target, b"sentinel").unwrap();
        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o400)).unwrap();
        let install = root.path().join("install");
        fs::directory(&install, true).unwrap();
        symlink(&target, install.join("link")).unwrap();
        symlink(root.path(), install.join("directory-link")).unwrap();
        std::fs::hard_link(&target, install.join("object")).unwrap();
        let original = std::fs::metadata(&target).unwrap();
        assert_eq!(original.nlink(), 2);
        prepare(&install)
            .remove()
            .unwrap_or_else(|f| panic!("{}", f.reason));
        assert!(!install.exists());
        assert_eq!(std::fs::read(&target).unwrap(), b"sentinel");
        let after = std::fs::metadata(&target).unwrap();
        assert_eq!(after.ino(), original.ino());
        assert_eq!(after.mode(), original.mode());
        assert_eq!(after.nlink(), 1);
    }
    #[test]
    fn changed_tree_fails_before_any_unlink_preserving_env_and_registration() {
        let root = fixture();
        let install = root.path().join("install");
        fs::directory(&install, true).unwrap();
        fs::write(&install.join(".env"), b"fixture-private", 0o600).unwrap();
        fs::write(&install.join("ordinary"), b"keep", 0o600).unwrap();
        fs::write(
            &root.path().join("server.json"),
            b"fixture-registration",
            0o600,
        )
        .unwrap();
        let plan = prepare(&install);
        std::fs::rename(install.join("ordinary"), install.join("replaced")).unwrap();
        let failure = plan.remove().err().unwrap();
        assert_eq!(failure.reason, "installation_tree_changed");
        assert_eq!(
            std::fs::read(install.join(".env")).unwrap(),
            b"fixture-private"
        );
        assert_eq!(
            std::fs::read(root.path().join("server.json")).unwrap(),
            b"fixture-registration"
        );
        assert!(install.join("replaced").is_file());
    }
    #[test]
    fn unreadable_nested_directory_is_reported_before_environment_or_registration_removal() {
        if rustix::process::geteuid().is_root() {
            return;
        }
        let root = fixture();
        let install = root.path().join("install");
        fs::directory(&install, true).unwrap();
        fs::write(&install.join(".env"), b"fixture-private", 0o600).unwrap();
        let blocked = install.join("vault_setup").join("__pycache__");
        std::fs::create_dir_all(&blocked).unwrap();
        std::fs::write(blocked.join("setup.pyc"), b"fixture").unwrap();
        std::fs::set_permissions(&blocked, std::fs::Permissions::from_mode(0o000)).unwrap();
        let state = root.path().join("state");
        fs::write(&state.join(CONFIG), b"fixture-registration", 0o600).unwrap();
        let mut c = super::super::tests::c();
        c.install_path = install.clone();
        let output = fake::with(vec![], || {
            destructive(
                "uninstall",
                &c,
                &Flags::from([("yes".into(), json!(true))]),
                &state,
            )
            .unwrap()
        });
        std::fs::set_permissions(&blocked, std::fs::Permissions::from_mode(0o700)).unwrap();
        assert_eq!(output["reason"], "directory_inventory_permission_required");
        assert_eq!(
            output["obstruction"]["relativePath"],
            "./vault_setup/__pycache__"
        );
        assert_eq!(output["runtimeStopped"], false);
        assert_eq!(
            std::fs::read(install.join(".env")).unwrap(),
            b"fixture-private"
        );
        assert_eq!(
            std::fs::read(state.join(CONFIG)).unwrap(),
            b"fixture-registration"
        );
        assert!(blocked.join("setup.pyc").is_file());
    }
    #[test]
    fn inventory_obstruction_retains_environment_and_registration_without_stopping_runtime() {
        let root = fixture();
        let install = root.path().join("install");
        fs::directory(&install, true).unwrap();
        fs::write(&install.join(".env"), b"fixture-private", 0o600).unwrap();
        let state = root.path().join("state");
        fs::write(&state.join(CONFIG), b"fixture-registration", 0o600).unwrap();
        let mut deep = install.clone();
        for _ in 0..MAX_DEPTH + 1 {
            deep.push("d");
            std::fs::create_dir(&deep).unwrap();
        }
        let mut c = super::super::tests::c();
        c.install_path = install.clone();
        let output = fake::with(vec![], || {
            destructive(
                "uninstall",
                &c,
                &Flags::from([("yes".into(), json!(true))]),
                &state,
            )
            .unwrap()
        });
        assert_eq!(output["status"], "degraded");
        assert_eq!(output["reason"], "cleanup_inventory_limit");
        assert_eq!(output["runtimeStopped"], false);
        assert_eq!(output["installationRegistrationPreserved"], true);
        assert!(!output.to_string().contains("fixture-private"));
        assert_eq!(
            std::fs::read(install.join(".env")).unwrap(),
            b"fixture-private"
        );
        assert_eq!(
            std::fs::read(state.join(CONFIG)).unwrap(),
            b"fixture-registration"
        );
    }
    #[test]
    fn successful_uninstall_removes_registration_only_after_verified_tree_cleanup() {
        let root = fixture();
        let install = root.path().join("install");
        fs::directory(&install, true).unwrap();
        fs::write(&install.join(".env"), b"fixture-private", 0o600).unwrap();
        let state = root.path().join("state");
        let mut c = super::super::tests::c();
        c.install_path = install.clone();
        save_config(&state, &c).unwrap();
        let mut args = compose(&c);
        args.extend([
            "down".into(),
            "--rmi".into(),
            "local".into(),
            "--volumes".into(),
        ]);
        let output = fake::with(
            vec![fake::Call {
                program: "docker",
                args,
                output: Ok(vec![]),
            }],
            || {
                destructive(
                    "uninstall",
                    &c,
                    &Flags::from([("yes".into(), json!(true))]),
                    &state,
                )
                .unwrap()
            },
        );
        assert_eq!(output["status"], "success");
        assert!(!install.exists());
        assert!(!state.join(CONFIG).exists());
    }
    #[test]
    fn owner_only_directory_write_preparation_preserves_regular_file_modes() {
        let root = fixture();
        let install = root.path().join("install");
        fs::directory(&install, true).unwrap();
        let child = install.join("objects");
        std::fs::create_dir(&child).unwrap();
        std::fs::write(child.join("object"), b"fixture").unwrap();
        std::fs::set_permissions(&child, std::fs::Permissions::from_mode(0o500)).unwrap();
        prepare(&install)
            .remove()
            .unwrap_or_else(|f| panic!("{}", f.reason));
        assert!(!install.exists());
        // Foreign-owned nonempty directories require effective parent write;
        // root ownership alone never triggers a chmod by the invoking user.
        assert!(!can_prepare_write(1001, 0, false));
        assert!(!can_prepare_write(1001, 1002, false));
        assert!(can_prepare_write(1001, 0, true));
        assert!(can_prepare_write(1001, 1001, false));
        let mut parent = rustix::fs::fstat(File::open(root.path()).unwrap()).unwrap();
        let mut child = parent;
        parent.st_mode |= 0o1000;
        parent.st_uid = 0;
        child.st_uid = 1002;
        assert!(!sticky_allows(1001, &parent, &child));
        assert!(sticky_allows(1002, &parent, &child));
    }
    #[cfg(target_os = "linux")]
    #[test]
    fn mounted_child_is_refused_by_descriptor_resolution() {
        // Read an existing kernel mount; the fixture creates no host mounts.
        let root = File::open("/").unwrap();
        assert!(matches!(
            directory(&root, std::ffi::OsStr::new("proc")),
            Err(rustix::io::Errno::XDEV)
        ));
        assert!(matches!(
            entry_metadata(&root, std::ffi::OsStr::new("proc/version")),
            Err(rustix::io::Errno::XDEV)
        ));
        let root_meta = rustix::fs::fstat(&root).unwrap();
        let proc_meta = rustix::fs::statat(&root, "proc", AtFlags::SYMLINK_NOFOLLOW).unwrap();
        assert!(mounted(&root_meta, &proc_meta));
    }
}
