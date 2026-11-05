use super::*;
use flate2::{Compression, read::GzDecoder, write::GzEncoder};
use sha2::{Digest, Sha256};
use std::fs::File;

struct CheckedReader<R>(R);
impl<R: Read> Read for CheckedReader<R> {
    fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
        operation::check().map_err(|_| std::io::Error::other("Operation cancelled."))?;
        self.0.read(buffer)
    }
}
struct Scratch(PathBuf);
impl Scratch {
    fn new(root: &Path) -> Result<Self> {
        let path = root.join(format!(".backup-{}", uuid::Uuid::new_v4()));
        fs::directory(&path, true)?;
        Ok(Self(path))
    }
}
impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
fn files(root: &Path, relative: &Path, result: &mut Vec<PathBuf>) -> Result<()> {
    for entry in std::fs::read_dir(root.join(relative))? {
        operation::check()?;
        let entry = entry?;
        let kind = entry.file_type()?;
        let path = relative.join(entry.file_name());
        if kind.is_symlink() {
            return Err(Error::Invalid("Backup refuses symbolic links."));
        }
        if kind.is_dir() {
            files(root, &path, result)?;
        } else if kind.is_file() {
            result.push(path);
        } else {
            return Err(Error::Invalid("Backup refuses special files."));
        }
    }
    result.sort();
    Ok(())
}
fn copy_tree(from: &Path, to: &Path) -> Result<()> {
    let mut names = vec![];
    files(from, Path::new(""), &mut names)?;
    for name in names {
        let bytes = Zeroizing::new(fs::read(&from.join(&name), 64 * 1024 * 1024)?);
        fs::write(&to.join(name), &bytes, 0o600)?;
    }
    Ok(())
}
fn digest_file(path: &Path) -> Result<String> {
    let mut input = File::open(path)?;
    let mut digest = Sha256::new();
    let mut block = [0u8; 65536];
    loop {
        operation::check()?;
        let n = input.read(&mut block)?;
        if n == 0 {
            break;
        }
        digest.update(&block[..n]);
    }
    Ok(format!("{:x}", digest.finalize()))
}
fn backup_dir(c: &Configuration) -> PathBuf {
    c.install_path.join("backups").join(&c.server_role)
}
pub(super) fn list(c: &Configuration) -> Result<Value> {
    let root = backup_dir(c);
    let mut files = vec![];
    if root.try_exists()? {
        fs::directory(&root, false)?;
        for entry in std::fs::read_dir(&root)? {
            let entry = entry?;
            if entry.file_type()?.is_file()
                && entry.file_name().to_string_lossy().ends_with(".tar.gz")
            {
                files.push(entry.file_name().to_string_lossy().into_owned());
            }
        }
    }
    files.sort();
    Ok(json!({"role":c.server_role,"backupDir":root,"files":files}))
}
pub(super) fn create(c: &Configuration, flags: &Flags) -> Result<Value> {
    let root = backup_dir(c);
    fs::directory(&root, true)?;
    let scratch = Scratch::new(&root)?;
    let archive = if let Some(path) = text(flags, "output") {
        normalized_path(path)?
    } else {
        root.join(format!("openmates-{}-{}.tar.gz", c.server_role, now()))
    };
    if archive.starts_with(&scratch.0) || archive == c.install_path.join(".env") {
        return Err(Error::Invalid("Backup output overlaps server state."));
    }
    if archive.starts_with(&c.install_path) && !archive.starts_with(&root) {
        return Err(Error::Invalid(
            "Backup output must not overwrite installation files. Use the backup directory or an external archive path.",
        ));
    }
    if !archive.to_string_lossy().ends_with(".tar.gz") {
        return Err(Error::Invalid(
            "Backup output must use a .tar.gz archive filename.",
        ));
    }
    let content = env(&c.install_path)?;
    fs::write(&scratch.0.join("runtime/.env"), content.as_bytes(), 0o600)?;
    if c.install_path.join("config").try_exists()? {
        copy_tree(
            &c.install_path.join("config"),
            &scratch.0.join("runtime/config"),
        )?;
    }
    if c.server_role == "core" {
        let user = env_get(&content, "DATABASE_USERNAME").unwrap_or("directus");
        let database = env_get(&content, "DATABASE_NAME").unwrap_or("directus");
        fs::publish(&scratch.0.join("postgres.sql"), 0o600, |output| {
            let mut args = compose(c);
            args.extend([
                "exec".into(),
                "-T".into(),
                "cms-database".into(),
                "pg_dump".into(),
                "--clean".into(),
                "--if-exists".into(),
                "--no-owner".into(),
                "--no-privileges".into(),
                "-U".into(),
                user.into(),
                "--dbname".into(),
                database.into(),
            ]);
            operation::to_file(
                "docker",
                &args,
                &c.install_path,
                output,
                std::time::Duration::from_secs(30 * 60),
            )?;
            Ok(())
        })?;
    }
    let manifest = json!({"role":c.server_role,"backup_format_version":2,"created_at":now(),"cli_version":env!("CARGO_PKG_VERSION"),"image_tag":c.image_tag,"recovery_scope":if c.server_role=="core"{"database-and-runtime-only"}else{"runtime-only"},"include_observability":false,"contents":if c.server_role=="core"{vec!["runtime-env","runtime-config","postgres"]}else{vec!["runtime-env","runtime-config"]}});
    fs::write(
        &scratch.0.join("manifest.json"),
        &serde_json::to_vec_pretty(&manifest)?,
        0o600,
    )?;
    let mut names = vec![];
    files(&scratch.0, Path::new(""), &mut names)?;
    let mut sums = String::new();
    for name in &names {
        let name_text = name.to_str().ok_or(Error::Io)?;
        if name_text.contains(['\n', '\r']) {
            return Err(Error::Invalid(
                "Backup filename contains unsupported characters.",
            ));
        }
        sums.push_str(&format!(
            "{}  {}\n",
            digest_file(&scratch.0.join(name))?,
            name_text
        ));
    }
    fs::write(&scratch.0.join("checksums.sha256"), sums.as_bytes(), 0o600)?;
    names.push("checksums.sha256".into());
    fs::publish(&archive, 0o600, |output| {
        let encoder = GzEncoder::new(output, Compression::default());
        let mut tar = tar::Builder::new(encoder);
        for name in &names {
            let mut source = CheckedReader(File::open(scratch.0.join(name))?);
            let mut header = tar::Header::new_gnu();
            header.set_entry_type(tar::EntryType::Regular);
            header.set_size(source.0.metadata()?.len());
            header.set_mode(0o600);
            header.set_uid(0);
            header.set_gid(0);
            header.set_mtime(0);
            header.set_cksum();
            tar.append_data(&mut header, name, &mut source)?;
        }
        tar.into_inner()?.finish()?;
        Ok(())
    })?;
    Ok(
        json!({"command":"backup","status":"success","role":c.server_role,"file":archive,"recoveryScope":manifest["recovery_scope"]}),
    )
}
fn extract(archive: &Path, root: &Path) -> Result<()> {
    use std::os::unix::fs::MetadataExt;
    let directory = fs::directory(archive.parent().ok_or(Error::Io)?, false)?;
    let file = File::from(
        rustix::fs::openat(
            &directory,
            archive.file_name().ok_or(Error::Io)?,
            rustix::fs::OFlags::RDONLY | rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::CLOEXEC,
            rustix::fs::Mode::empty(),
        )
        .map_err(|_| Error::Io)?,
    );
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.nlink() != 1 || metadata.mode() & 0o077 != 0 {
        return Err(Error::Invalid(
            "Restore archive must be a private regular file without hard links.",
        ));
    }
    let capacity = fs2::available_space(root)?
        .saturating_sub(256 * 1024 * 1024)
        .min(128 * 1024 * 1024 * 1024);
    let mut input = tar::Archive::new(GzDecoder::new(CheckedReader(file)));
    let mut seen = std::collections::BTreeSet::new();
    let mut total = 0u64;
    for entry in input.entries()? {
        let mut entry = entry?;
        let path = entry.path()?.into_owned();
        if path.is_absolute()
            || path
                .components()
                .any(|c| !matches!(c, std::path::Component::Normal(_)))
            || !seen.insert(path.clone())
            || !entry.header().entry_type().is_file()
        {
            return Err(Error::Invalid(
                "Backup contains an unsafe path, duplicate or non-regular entry.",
            ));
        }
        // Archive entries are streamed with both per-entry and aggregate limits.
        let length = entry.header().size()?;
        total = total.checked_add(length).ok_or(Error::Io)?;
        if total > capacity || seen.len() > 100_000 {
            return Err(Error::Invalid("Backup exceeds recovery limits."));
        }
        fs::publish(&root.join(path), 0o600, |out| {
            let written = std::io::copy(&mut entry, out)?;
            if written != length {
                return Err(Error::Protocol);
            }
            Ok(())
        })?;
    }
    Ok(())
}
fn validate(root: &Path, role: &str) -> Result<Value> {
    let checksums = String::from_utf8(fs::read(&root.join("checksums.sha256"), 16 * 1024 * 1024)?)
        .map_err(|_| Error::Protocol)?;
    let mut expected = std::collections::BTreeSet::new();
    for line in checksums.lines() {
        let (hash, name) = line.split_once("  ").ok_or(Error::Protocol)?;
        let path = Path::new(name);
        if hash.len() != 64
            || !hash.bytes().all(|b| b.is_ascii_hexdigit())
            || path.is_absolute()
            || path
                .components()
                .any(|c| !matches!(c, std::path::Component::Normal(_)))
            || !expected.insert(path.to_path_buf())
            || digest_file(&root.join(path))? != hash
        {
            return Err(Error::Invalid("Backup checksum verification failed."));
        }
    }
    let mut actual = vec![];
    files(root, Path::new(""), &mut actual)?;
    actual.retain(|p| p != Path::new("checksums.sha256"));
    if actual
        .into_iter()
        .collect::<std::collections::BTreeSet<_>>()
        != expected
    {
        return Err(Error::Invalid(
            "Backup checksum inventory does not match archive files.",
        ));
    }
    let manifest: Value =
        serde_json::from_slice(&fs::read(&root.join("manifest.json"), 128 * 1024)?)?;
    if manifest["role"].as_str() != Some(role) {
        return Err(Error::Invalid(
            "Backup role does not match the requested server role.",
        ));
    }
    if manifest["backup_format_version"] != 2 {
        return Err(Error::Invalid("Unsupported backup format."));
    }
    if role == "core" && manifest["recovery_scope"].as_str() != Some("full-core") {
        return Err(Error::Invalid(
            "This backup records database and runtime state only; refusing unsafe full core restore.",
        ));
    }
    // Full-core requires coordinated Vault/storage recovery, which this native
    // format does not produce. Reject forged scope upgrades too.
    if role == "core" {
        return Err(Error::Invalid(
            "Full core recovery requires a coordinated storage and Vault recovery plan.",
        ));
    }
    if manifest["recovery_scope"] != "runtime-only"
        || !manifest["contents"]
            .as_array()
            .is_some_and(|items| items.iter().any(|v| v == "runtime-env"))
        || !expected.contains(Path::new("runtime/.env"))
        || expected.iter().any(|p| {
            p != Path::new("manifest.json")
                && p != Path::new("runtime/.env")
                && !p.starts_with("runtime/config")
        })
    {
        return Err(Error::Invalid(
            "Runtime backup is incomplete or contains unsupported recovery data.",
        ));
    }
    Ok(manifest)
}
struct StagedFile {
    target: PathBuf,
    bytes: Zeroizing<Vec<u8>>,
    before: Option<fs::Snapshot>,
}
fn stage(c: &Configuration, root: &Path) -> Result<Vec<StagedFile>> {
    let mut names = vec![];
    files(&root.join("runtime"), Path::new(""), &mut names)?;
    let mut staged = vec![];
    let mut size = 0usize;
    for name in names {
        if name != Path::new(".env") && !name.starts_with("config") {
            return Err(Error::Invalid("Unsupported runtime recovery path."));
        }
        let bytes = Zeroizing::new(fs::private_read(
            &root.join("runtime").join(&name),
            64 * 1024 * 1024,
        )?);
        size = size.checked_add(bytes.len()).ok_or(Error::Io)?;
        if size > 64 * 1024 * 1024 {
            return Err(Error::Invalid(
                "Runtime recovery configuration exceeds staging limits.",
            ));
        }
        if name == Path::new(".env") {
            std::str::from_utf8(&bytes).map_err(|_| Error::Protocol)?;
        }
        let target = c.install_path.join(name);
        // Validate all destination ancestors and existing files before downtime.
        fs::directory(target.parent().ok_or(Error::Io)?, true)?;
        let before = if target.try_exists()? {
            Some(fs::snapshot(&target, 64 * 1024 * 1024)?)
        } else {
            None
        };
        staged.push(StagedFile {
            target,
            bytes,
            before,
        });
    }
    Ok(staged)
}
fn apply_staged(c: &Configuration, staged: &[StagedFile]) -> Result<()> {
    let _critical = operation::critical()?;
    // Resolve the complete launch command while the prior runtime is still up.
    let start = ["up".to_owned(), "-d".to_owned()]
        .into_iter()
        .chain(services(c, &Flags::new())?)
        .collect::<Vec<_>>();
    if docker(c, ["down".into()]).is_err() {
        let restarted = docker(c, start.clone()).is_ok();
        return Err(Error::Invalid(if restarted {
            "Restore could not stop the runtime; prior runtime was restarted."
        } else {
            "Restore could not stop the runtime and its restart failed; operator recovery is required."
        }));
    }
    let mut written = 0;
    let result: Result<()> = (|| {
        for item in staged {
            if item.before.is_some() {
                fs::write_identity(&item.target, &item.bytes, item.before.as_ref())?;
            } else {
                fs::write(&item.target, &item.bytes, 0o600)?;
            }
            written += 1;
        }
        docker(c, start.clone())?;
        Ok(())
    })();
    if result.is_err() {
        // Stop any partially started restored runtime before restoring its inputs.
        let _ = docker(c, ["down".into()]);
        let mut recovered = true;
        for item in staged[..written].iter().rev() {
            let rollback = if let Some(before) = &item.before {
                fs::write_identity(&item.target, &before.bytes, Some(before))
            } else {
                std::fs::remove_file(&item.target).map_err(|_| Error::Io)
            };
            recovered &= rollback.is_ok();
        }
        let restarted = docker(c, start).is_ok();
        return Err(Error::Invalid(if recovered && restarted {
            "Restore failed; previous configuration was restored and its runtime restarted."
        } else {
            "Restore failed and automatic recovery was incomplete; operator recovery is required."
        }));
    }
    Ok(())
}
pub(super) fn restore(c: &Configuration, flags: &Flags) -> Result<Value> {
    if !boolean(flags, "yes") {
        return Err(Error::Invalid("Restore requires --yes."));
    }
    let file = normalized_path(
        text(flags, "file").ok_or(Error::Invalid("Restore requires --file ARCHIVE."))?,
    )?;
    let root = backup_dir(c);
    fs::directory(&root, true)?;
    let scratch = Scratch::new(&root)?;
    extract(&file, &scratch.0)?;
    validate(&scratch.0, &c.server_role)?;
    let staged = stage(c, &scratch.0)?;
    apply_staged(c, &staged)?;
    Ok(json!({"command":"restore","status":"success","role":c.server_role}))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn temp() -> tempfile::TempDir {
        use std::os::unix::fs::PermissionsExt;
        tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap()
    }
    #[test]
    fn manifest_only_runtime_backup_is_rejected_before_any_system_command() {
        let dir = temp();
        let manifest = json!({"role":"upload","backup_format_version":2,"recovery_scope":"runtime-only","contents":["runtime-env","runtime-config"]});
        fs::write(
            &dir.path().join("manifest.json"),
            &serde_json::to_vec(&manifest).unwrap(),
            0o600,
        )
        .unwrap();
        let sums = format!(
            "{}  manifest.json\n",
            digest_file(&dir.path().join("manifest.json")).unwrap()
        );
        fs::write(&dir.path().join("checksums.sha256"), sums.as_bytes(), 0o600).unwrap();
        fake::with(vec![], || assert!(validate(dir.path(), "upload").is_err()));
    }
    #[test]
    fn failed_restored_start_restores_old_inputs_and_restarts_prior_runtime() {
        let dir = temp();
        let staged = temp();
        let mut c = super::super::tests::c();
        c.install_path = dir.path().to_path_buf();
        c.server_role = "upload".into();
        fs::write(&dir.path().join(".env"), b"OLD=1\n", 0o600).unwrap();
        fs::write(&staged.path().join("runtime/.env"), b"NEW=1\n", 0o600).unwrap();
        let staged = stage(&c, staged.path()).unwrap();
        let call = |tail: Vec<String>, output| {
            let mut args = compose(&c);
            args.extend(tail);
            fake::Call {
                program: "docker",
                args,
                output,
            }
        };
        let up = ["up".to_owned(), "-d".to_owned()]
            .into_iter()
            .chain(services(&c, &Flags::new()).unwrap())
            .collect::<Vec<_>>();
        fake::with(
            vec![
                call(vec!["down".into()], Ok(vec![])),
                call(up.clone(), Err(Error::Io)),
                call(vec!["down".into()], Ok(vec![])),
                call(up, Ok(vec![])),
            ],
            || {
                assert!(
                    matches!(apply_staged(&c,&staged),Err(Error::Invalid(message)) if message.contains("runtime restarted"))
                );
            },
        );
        assert_eq!(
            fs::private_read(&dir.path().join(".env"), 64).unwrap(),
            b"OLD=1\n"
        );
    }
    #[test]
    fn corrupted_inventory_and_incomplete_core_restore_are_rejected_before_docker() {
        let dir = temp();
        let manifest = json!({"role":"core","backup_format_version":2,"recovery_scope":"database-and-runtime-only"});
        fs::write(
            &dir.path().join("manifest.json"),
            &serde_json::to_vec(&manifest).unwrap(),
            0o600,
        )
        .unwrap();
        let sum = format!(
            "{}  manifest.json\n",
            digest_file(&dir.path().join("manifest.json")).unwrap()
        );
        fs::write(&dir.path().join("checksums.sha256"), sum.as_bytes(), 0o600).unwrap();
        assert!(
            matches!(validate(dir.path(),"core"),Err(Error::Invalid(message)) if message.contains("refusing unsafe full core restore"))
        );
        fs::write(&dir.path().join("manifest.json"), b"{}", 0o600).unwrap();
        assert!(
            matches!(validate(dir.path(),"core"),Err(Error::Invalid(message)) if message.contains("checksum"))
        );
    }
    #[test]
    fn archive_symlinks_are_rejected() {
        let dir = temp();
        let archive = dir.path().join("bad.tar.gz");
        fs::publish(&archive, 0o600, |file| {
            let mut tar = tar::Builder::new(GzEncoder::new(file, Compression::default()));
            let mut header = tar::Header::new_gnu();
            header.set_entry_type(tar::EntryType::Symlink);
            header.set_size(0);
            header.set_mode(0o600);
            header.set_link_name("/etc/passwd")?;
            header.set_cksum();
            tar.append_data(&mut header, "runtime/.env", std::io::empty())?;
            tar.into_inner()?.finish()?;
            Ok(())
        })
        .unwrap();
        let output = dir.path().join("extract");
        fs::directory(&output, true).unwrap();
        assert!(extract(&archive, &output).is_err());
        assert!(!output.join("runtime/.env").exists());
    }
}
