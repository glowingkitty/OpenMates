//! Fresh self-host database initialization, never an existing-server cutover.
//! PostgreSQL executes this SQL only while initializing an empty PGDATA volume.
//! A second, transactional empty-user-database guard precedes the sole INSERT.
//! Existing databases, restores and restarts never acquire deferred authority.
//! The generated owner-controlled Compose file mounts only this public SQL file.
//! No application account, provider credential or chat content enters the hook.
use super::*;

const OVERLAY: &str = ".openmates/chat-bootstrap.compose.json";
const SQL_PATH: &str = ".openmates/chat-bootstrap/90-openmates-chat.sql";
const TARGET: &str = "/docker-entrypoint-initdb.d/90-openmates-chat.sql";
pub(super) const SQL: &str = r#"-- Native self-host fresh-PGDATA initialization only; never run as a migration.
-- The official PostgreSQL entrypoint skips initdb.d for existing database storage.
-- Refuse nonempty user databases even if this file is invoked outside initdb.
-- No existing row is ever updated and no deferred activation marker is stored.
BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended('openmates-selfhost-first-database-v1', 0));
DO $bootstrap$
BEGIN
  IF current_database() IN ('postgres', 'template0', 'template1') OR EXISTS (
    SELECT 1 FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
  ) THEN
    RAISE EXCEPTION 'selfhost_fresh_database_required';
  END IF;
  CREATE TABLE public.chat_recovery_protocol_state (
    id varchar(64) PRIMARY KEY,
    protocol_epoch integer NOT NULL DEFAULT 0,
    sends_paused boolean NOT NULL DEFAULT false,
    legacy_in_flight integer NOT NULL DEFAULT 0,
    active_legacy_tasks json NOT NULL,
    legacy_task_lifecycle json
  );
  INSERT INTO public.chat_recovery_protocol_state
    (id, protocol_epoch, sends_paused, legacy_in_flight, active_legacy_tasks, legacy_task_lifecycle)
    VALUES ('chat-recovery', 1, false, 0, '[]'::json, '[]'::json);
END;
$bootstrap$;
COMMIT;
"#;

fn selected(c: &Configuration) -> bool {
    c.server_role == "core" && c.deployment_mode == "self_host"
}
fn present(c: &Configuration) -> bool {
    match std::fs::symlink_metadata(c.install_path.join(OVERLAY)) {
        Ok(_) => true,
        Err(error) => error.kind() != std::io::ErrorKind::NotFound,
    }
}
fn document(c: &Configuration) -> Result<Vec<u8>> {
    // Compose interpolates JSON string values too. Each literal dollar must
    // survive its one interpolation pass without selecting another host path.
    let source = c.install_path.join(SQL_PATH);
    let source = source
        .to_str()
        .ok_or(Error::Invalid("Bootstrap mount path must be valid UTF-8."))?
        .replace('$', "$$");
    Ok(serde_json::to_vec(
        &json!({"services":{"cms-database":{"volumes":[{
            "type":"bind", "source":source, "target":TARGET,
            "read_only":true, "bind":{"create_host_path":false}
        }]}}}),
    )?)
}
/// Called only by install. Register/start/update never create this mount.
pub(super) fn prepare(c: &Configuration) -> Result<()> {
    if selected(c) {
        fs::public_directory(&c.install_path.join(".openmates/chat-bootstrap"))?;
        fs::write(&c.install_path.join(SQL_PATH), SQL.as_bytes(), 0o644)?;
        fs::write(&c.install_path.join(OVERLAY), &document(c)?, 0o600)?;
    }
    Ok(())
}
/// Preserve missing legacy mounts, and refuse changed/symlinked owned inputs.
pub(super) fn validate(c: &Configuration) -> Result<()> {
    if selected(c)
        && present(c)
        && (fs::private_read(&c.install_path.join(OVERLAY), 8192)? != document(c)?
            || fs::read(&c.install_path.join(SQL_PATH), 8192)? != SQL.as_bytes())
    {
        return Err(Error::Invalid(
            "Fresh database bootstrap inputs changed; existing data was preserved.",
        ));
    }
    Ok(())
}
pub(super) fn append(c: &Configuration, args: &mut Vec<String>) {
    if selected(c) && present(c) {
        args.extend(["-f".into(), OVERLAY.into()]);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    fn fixture() -> (tempfile::TempDir, Configuration) {
        let directory = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::super::tests::c();
        c.install_path = directory.path().into();
        (directory, c)
    }
    #[test]
    fn compose_source_escapes_literal_dollars_and_preserves_json_metacharacters() {
        for (literal, encoded) in [
            ("plain", "plain"),
            ("$BOOTSTRAP_ROOT", "$$BOOTSTRAP_ROOT"),
            ("${BOOTSTRAP_ROOT}", "$${BOOTSTRAP_ROOT}"),
            ("$$already", "$$$$already"),
            ("${MISSING:?required}", "$${MISSING:?required}"),
            ("$(printf injected)", "$$(printf injected)"),
            (
                "space ; & \"quote\" 'single' \\ `tick`",
                "space ; & \"quote\" 'single' \\ `tick`",
            ),
        ] {
            let (_directory, mut c) = fixture();
            let parent = c.install_path.clone();
            c.install_path = parent.join(literal);
            let value: Value = serde_json::from_slice(&document(&c).unwrap()).unwrap();
            let source = value["services"]["cms-database"]["volumes"][0]["source"]
                .as_str()
                .unwrap();
            assert_eq!(
                source,
                parent.join(encoded).join(SQL_PATH).to_str().unwrap()
            );
            // Compose's escaped-dollar pass must recover precisely the owned
            // filename; it must not leave a variable expression to evaluate.
            assert_eq!(
                source.replace("$$", "$"),
                c.install_path.join(SQL_PATH).to_str().unwrap()
            );
            let mut bytes = source.bytes();
            while let Some(byte) = bytes.next() {
                if byte == b'$' {
                    assert_eq!(bytes.next(), Some(b'$'));
                }
            }
        }
    }
    #[test]
    fn literal_dollar_install_validates_the_same_owned_sql_file() {
        let (_directory, mut c) = fixture();
        c.install_path = c.install_path.join("${BOOTSTRAP_ROOT}");
        prepare(&c).unwrap();
        validate(&c).unwrap();
        assert_eq!(
            fs::read(&c.install_path.join(SQL_PATH), 8192).unwrap(),
            SQL.as_bytes()
        );
        let value: Value = serde_json::from_slice(&document(&c).unwrap()).unwrap();
        assert!(
            value["services"]["cms-database"]["volumes"][0]["source"]
                .as_str()
                .unwrap()
                .contains("$${BOOTSTRAP_ROOT}")
        );
    }
    #[test]
    fn new_source_and_image_share_the_packaged_first_pgdata_hook() {
        for mode in ["source", "image"] {
            let (_directory, mut c) = fixture();
            c.install_mode = mode.into();
            prepare(&c).unwrap();
            validate(&c).unwrap();
            let document: Value = serde_json::from_slice(
                &fs::private_read(&c.install_path.join(OVERLAY), 8192).unwrap(),
            )
            .unwrap();
            let mount = &document["services"]["cms-database"]["volumes"][0];
            assert_eq!(mount["target"], TARGET);
            assert_eq!(mount["read_only"], true);
            assert_eq!(mount["bind"]["create_host_path"], false);
            let first = compose(&c);
            assert!(first.windows(2).any(|v| v == ["-f", OVERLAY]));
            assert_eq!(first, compose(&c)); // Restart/update use the same persisted mount.
            assert_eq!(
                fs::read(&c.install_path.join(SQL_PATH), 8192).unwrap(),
                SQL.as_bytes()
            );
        }
    }
    #[test]
    fn old_install_start_or_update_does_not_create_a_hook() {
        let (_directory, c) = fixture();
        validate(&c).unwrap();
        assert!(!compose(&c).iter().any(|v| v == OVERLAY));
        assert!(!c.install_path.join(OVERLAY).exists());
    }
    #[test]
    fn other_roles_and_official_cloud_never_receive_the_hook() {
        for (role, deployment) in [
            ("upload", "self_host"),
            ("preview", "self_host"),
            ("core", "official_cloud"),
        ] {
            let (_directory, mut c) = fixture();
            c.server_role = role.into();
            c.deployment_mode = deployment.into();
            prepare(&c).unwrap();
            assert!(!c.install_path.join(OVERLAY).exists());
        }
    }
    #[test]
    fn changed_or_symlinked_bootstrap_is_refused_without_rewriting() {
        let (_directory, c) = fixture();
        prepare(&c).unwrap();
        fs::write(&c.install_path.join(SQL_PATH), b"changed", 0o644).unwrap();
        assert!(validate(&c).is_err());
        assert_eq!(
            fs::read(&c.install_path.join(SQL_PATH), 8192).unwrap(),
            b"changed"
        );
        std::fs::remove_file(c.install_path.join(SQL_PATH)).unwrap();
        std::os::unix::fs::symlink("/dev/null", c.install_path.join(SQL_PATH)).unwrap();
        assert!(validate(&c).is_err());
    }
}
