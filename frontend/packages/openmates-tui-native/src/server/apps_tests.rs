//! Instance app package install store: validation, staging and activation.
use super::apps::{self, RESTART_SERVICES, Registry};
use super::apps_archive as archive;
use super::*;
use std::os::unix::fs::PermissionsExt;

const PROVIDER: &[u8] = b"#!/bin/sh\necho '{\"results\":[]}'\n";

fn manifest(version: &str) -> String {
    format!(
        "format: openmates-app-package\nformat_version: 1\nid: my.events\nversion: {version}\nname: My events\ndescription: Events from my own website.\ncontributes:\n  providers:\n    - app: events\n      skill: search\n      contract: events.search@1\n      id: my_events\n      name: My events\n      runtime: executable\n      entrypoint: bin/{{target}}/provider\n      secrets: [api_key]\n"
    )
}
fn zip(entries: &[(&str, &[u8])]) -> Vec<u8> {
    use zip::write::SimpleFileOptions;
    let mut writer = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
    for (name, body) in entries {
        if name.ends_with('/') {
            writer
                .add_directory(*name, SimpleFileOptions::default())
                .unwrap();
        } else {
            writer
                .start_file(*name, SimpleFileOptions::default().unix_permissions(0o644))
                .unwrap();
            writer.write_all(body).unwrap();
        }
    }
    writer.finish().unwrap().into_inner()
}
fn package(version: &str, extra: &[(&str, &[u8])]) -> Vec<u8> {
    let manifest = manifest(version);
    let mut entries: Vec<(&str, &[u8])> = vec![
        ("manifest.yml", manifest.as_bytes()),
        ("bin/aarch64/provider", PROVIDER),
        ("bin/x86_64/provider", PROVIDER),
    ];
    entries.extend_from_slice(extra);
    zip(&entries)
}
struct Fixture {
    temp: tempfile::TempDir,
    c: Configuration,
}
impl Fixture {
    fn new() -> Self {
        let temp = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let mut c = super::tests::c();
        c.install_path = temp.path().into();
        let env = temp.path().join(".env");
        std::fs::write(&env, "OPENMATES_APP_PACKAGES_ENABLED=true\n").unwrap();
        std::fs::set_permissions(&env, std::fs::Permissions::from_mode(0o600)).unwrap();
        Self { temp, c }
    }
    fn root(&self) -> PathBuf {
        self.temp.path().join(".openmates/app-packages")
    }
    fn archive(&self, name: &str, bytes: &[u8]) -> String {
        let path = self.temp.path().join(name);
        std::fs::write(&path, bytes).unwrap();
        path.to_string_lossy().into_owned()
    }
    fn run(&self, action: &str, args: &[String], flags: &[(&str, Value)]) -> Result<Value> {
        let flags = flags
            .iter()
            .map(|(k, v)| ((*k).to_owned(), v.clone()))
            .collect::<Flags>();
        validate_options(action, args, &flags)?;
        apps::execute(action, &self.c, args, &flags)
    }
    fn install(&self, bytes: &[u8]) -> Result<Value> {
        let path = self.archive(&format!("{}.zip", uuid::Uuid::new_v4()), bytes);
        self.run(
            "apps install",
            &[path],
            &[
                ("accept-server-execution", json!(true)),
                ("no-restart", json!(true)),
            ],
        )
    }
    fn registry(&self) -> Registry {
        serde_json::from_slice(&std::fs::read(self.root().join("registry.json")).unwrap()).unwrap()
    }
}
fn mode(path: &Path) -> u32 {
    std::fs::metadata(path).unwrap().permissions().mode() & 0o7777
}

#[test]
fn valid_install_stages_files_records_digests_and_activates() {
    let f = Fixture::new();
    let output = f.install(&package("1.0.0", &[])).unwrap();
    assert_eq!(output["status"], "installed");
    assert_eq!(output["package"]["providers"][0]["id"], "my_events");
    assert_eq!(output["restarted"], false);
    assert!(output["notice"].is_null());
    assert!(output["warning"].as_str().unwrap().contains("trust"));
    let version = f.root().join("packages/my.events/1.0.0");
    for path in [
        version.join("manifest.yml"),
        version.join("install.json"),
        version.join("files/manifest.yml"),
    ] {
        assert_eq!(mode(&path), 0o644);
    }
    for path in [
        f.root(),
        f.root().join("packages"),
        f.root().join("packages/my.events"),
        version.clone(),
        version.join("files/bin/x86_64"),
    ] {
        assert_eq!(mode(&path), 0o755);
    }
    assert_eq!(mode(&version.join("files/bin/aarch64/provider")), 0o755);
    assert_eq!(mode(&version.join("files/bin/x86_64/provider")), 0o755);
    let record: Value =
        serde_json::from_slice(&std::fs::read(version.join("install.json")).unwrap()).unwrap();
    assert_eq!(record["package_id"], "my.events");
    assert_eq!(record["version"], "1.0.0");
    assert_eq!(record["archive_sha256"], output["archiveSha256"]);
    let digests = record["file_digests"].as_object().unwrap();
    assert_eq!(
        digests.keys().collect::<Vec<_>>(),
        [
            "bin/aarch64/provider",
            "bin/x86_64/provider",
            "manifest.yml"
        ]
    );
    use sha2::{Digest, Sha256};
    assert_eq!(
        digests["bin/x86_64/provider"],
        format!("{:x}", Sha256::digest(PROVIDER))
    );
    let listed = f.run("apps list", &[], &[]).unwrap();
    assert_eq!(listed["packages"][0]["id"], "my.events");
    assert_eq!(listed["packages"][0]["activeVersion"], "1.0.0");
    assert_eq!(listed["packages"][0]["name"], "My events");
    // An identical archive is a no-op without a new registry revision.
    let again = f.install(&package("1.0.0", &[])).unwrap();
    assert_eq!(again["status"], "unchanged");
    assert_eq!(f.registry().revision, 1);
}

#[test]
fn registry_is_written_atomically_with_documented_content() {
    let f = Fixture::new();
    let output = f.install(&package("1.0.0", &[])).unwrap();
    let raw: Value =
        serde_json::from_slice(&std::fs::read(f.root().join("registry.json")).unwrap()).unwrap();
    assert_eq!(
        raw,
        json!({"format":1,"revision":1,"active":{"my.events":{"version":"1.0.0","sha256":output["archiveSha256"]}},"installed":{"my.events":["1.0.0"]}})
    );
    assert_eq!(mode(&f.root().join("registry.json")), 0o644);
    let leftovers = std::fs::read_dir(f.root())
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .filter(|name| name.ends_with(".tmp") || name.contains("staging"))
        .collect::<Vec<_>>();
    assert!(leftovers.is_empty(), "{leftovers:?}");
    let staging = std::fs::read_dir(f.root().join("packages/my.events"))
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect::<Vec<_>>();
    assert_eq!(staging, ["1.0.0"]);
}

#[test]
fn escaping_and_absolute_paths_are_rejected_before_anything_is_written() {
    let f = Fixture::new();
    for bad in [
        "../../etc/cron.d/job",
        "/etc/passwd",
        "bin\\provider",
        "a/./b",
    ] {
        let error = f.install(&package("1.0.0", &[(bad, b"x")])).unwrap_err();
        assert!(
            error.to_string().contains("Invalid package path"),
            "{bad}: {error}"
        );
    }
    assert!(!f.root().exists());
}

#[test]
fn symlink_entries_and_symlinked_root_are_rejected() {
    use zip::write::SimpleFileOptions;
    let f = Fixture::new();
    let manifest = manifest("1.0.0");
    let mut writer = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
    for (name, body) in [
        ("manifest.yml", manifest.as_bytes()),
        ("bin/aarch64/provider", PROVIDER),
        ("bin/x86_64/provider", PROVIDER),
    ] {
        writer
            .start_file(name, SimpleFileOptions::default())
            .unwrap();
        writer.write_all(body).unwrap();
    }
    writer
        .add_symlink("bin/link", "/etc/passwd", SimpleFileOptions::default())
        .unwrap();
    let bytes = writer.finish().unwrap().into_inner();
    let error = f.install(&bytes).unwrap_err();
    assert!(error.to_string().contains("symlinks"), "{error}");
    assert!(!f.root().exists());

    let elsewhere = f.temp.path().join("elsewhere");
    std::fs::create_dir(&elsewhere).unwrap();
    std::fs::create_dir_all(f.temp.path().join(".openmates")).unwrap();
    std::fs::set_permissions(
        f.temp.path().join(".openmates"),
        std::fs::Permissions::from_mode(0o700),
    )
    .unwrap();
    std::os::unix::fs::symlink(&elsewhere, f.root()).unwrap();
    assert!(f.install(&package("1.0.0", &[])).is_err());
    assert!(f.run("apps list", &[], &[]).is_err());
    assert_eq!(std::fs::read_dir(&elsewhere).unwrap().count(), 0);
}

#[test]
fn unsupported_contribution_kinds_and_bad_manifests_are_rejected() {
    let f = Fixture::new();
    let skills = manifest("1.0.0").replace(
        "contributes:\n",
        "contributes:\n  skills:\n    - id: custom\n",
    );
    let bytes = zip(&[
        ("manifest.yml", skills.as_bytes()),
        ("bin/aarch64/provider", PROVIDER),
        ("bin/x86_64/provider", PROVIDER),
    ]);
    let error = f.install(&bytes).unwrap_err();
    assert!(
        error.to_string().contains("Unsupported contribution kind"),
        "{error}"
    );
    for (from, to) in [
        ("format_version: 1", "format_version: 2"),
        ("id: my.events", "id: MyEvents"),
        ("version: 1.0.0", "version: one"),
        ("runtime: executable", "runtime: python"),
        ("contract: events.search@1", "contract: travel.search@1"),
        ("id: my_events", "id: x"),
    ] {
        let raw = manifest("1.0.0").replacen(from, to, 1);
        assert!(archive::parse_manifest(raw.as_bytes()).is_err(), "{to}");
    }
    let missing_target = zip(&[
        ("manifest.yml", manifest("1.0.0").as_bytes()),
        ("bin/other/provider", PROVIDER),
    ]);
    assert!(f.install(&missing_target).is_err());
    assert!(!f.root().exists());
}

#[test]
fn same_version_with_different_archive_is_rejected() {
    let f = Fixture::new();
    f.install(&package("1.0.0", &[])).unwrap();
    let error = f
        .install(&package("1.0.0", &[("README.md", b"changed")]))
        .unwrap_err();
    assert!(error.to_string().contains("different archive"), "{error}");
    assert_eq!(f.registry().revision, 1);
}

#[test]
fn non_interactive_install_without_acceptance_is_rejected() {
    let f = Fixture::new();
    let path = f.archive("pkg.zip", &package("1.0.0", &[]));
    let error = f
        .run("apps install", &[path], &[("no-restart", json!(true))])
        .unwrap_err();
    assert!(
        error.to_string().contains("--accept-server-execution"),
        "{error}"
    );
    assert!(!f.root().exists());
}

#[test]
fn restart_services_cover_package_consumers_in_selfhost_compose() {
    let expected: Vec<&str> = std::iter::once("api")
        .chain(
            super::WORKERS
                .iter()
                .copied()
                .filter(|s| *s != "task-scheduler"),
        )
        .chain(std::iter::once("app-packages-runner"))
        .collect();
    assert_eq!(RESTART_SERVICES, expected.as_slice());
    let compose = include_str!("../../assets/selfhost/core/docker-compose.selfhost.yml");
    for service in RESTART_SERVICES {
        assert!(
            compose.contains(&format!("\n  {service}:\n")),
            "{service} missing from the self-host compose"
        );
    }
}

#[test]
fn rollback_restores_previous_version_and_restarts_services() {
    let f = Fixture::new();
    f.install(&package("1.0.0", &[])).unwrap();
    f.install(&package("1.1.0", &[])).unwrap();
    assert_eq!(f.registry().active["my.events"].version, "1.1.0");
    let mut args = compose(&f.c);
    args.push("restart".into());
    args.extend(RESTART_SERVICES.iter().map(|s| (*s).to_owned()));
    let output = fake::with(
        vec![fake::Call {
            program: "docker",
            args,
            output: Ok(vec![]),
        }],
        || f.run("apps rollback", &["my.events".into()], &[]).unwrap(),
    );
    assert_eq!(output["activeVersion"], "1.0.0");
    assert_eq!(output["previousVersion"], "1.1.0");
    assert_eq!(output["restarted"], json!(RESTART_SERVICES));
    let registry = f.registry();
    assert_eq!(registry.active["my.events"].version, "1.0.0");
    assert_eq!(registry.installed["my.events"], ["1.0.0", "1.1.0"]);
    assert_eq!(registry.revision, 3);
    let inspected = f.run("apps inspect", &["my.events".into()], &[]).unwrap();
    assert_eq!(inspected["activeVersion"], "1.0.0");
    assert_eq!(inspected["versions"][1]["active"], false);
    // No earlier version remains below 1.0.0; --to selects explicitly.
    assert!(
        f.run(
            "apps rollback",
            &["my.events".into()],
            &[("no-restart", json!(true))]
        )
        .is_err()
    );
    let forward = f
        .run(
            "apps rollback",
            &["my.events".into()],
            &[("to", json!("1.1.0")), ("no-restart", json!(true))],
        )
        .unwrap();
    assert_eq!(forward["activeVersion"], "1.1.0");
}

#[test]
fn remove_deactivates_and_deletes_every_version() {
    let f = Fixture::new();
    f.install(&package("1.0.0", &[])).unwrap();
    f.install(&package("1.1.0", &[])).unwrap();
    let error = f
        .run(
            "apps remove",
            &["my.events".into()],
            &[("no-restart", json!(true))],
        )
        .unwrap_err();
    assert!(error.to_string().contains("--yes"), "{error}");
    let output = f
        .run(
            "apps remove",
            &["my.events".into()],
            &[("yes", json!(true)), ("no-restart", json!(true))],
        )
        .unwrap();
    assert_eq!(output["removedVersions"], json!(["1.0.0", "1.1.0"]));
    assert!(!f.root().join("packages/my.events").exists());
    let registry = f.registry();
    assert!(registry.active.is_empty() && registry.installed.is_empty());
    assert!(f.run("apps inspect", &["my.events".into()], &[]).is_err());
}

#[test]
fn inspect_reports_secret_state_without_values_and_disabled_notice() {
    let f = Fixture::new();
    f.install(&package("1.0.0", &[])).unwrap();
    let missing = f.run("apps inspect", &["my.events".into()], &[]).unwrap();
    let secret = &missing["providers"][0]["secrets"][0];
    assert_eq!(secret["variable"], "SECRET__MY_EVENTS__API_KEY");
    assert_eq!(secret["configured"], false);
    assert_eq!(missing["missingSecrets"], 1);
    let env = f.temp.path().join(".env");
    std::fs::write(&env, "SECRET__MY_EVENTS__API_KEY=synthetic-value\n").unwrap();
    let configured = f.run("apps inspect", &["my.events".into()], &[]).unwrap();
    assert_eq!(configured["providers"][0]["secrets"][0]["configured"], true);
    assert_eq!(configured["providers"][0]["available"], true);
    assert!(!configured.to_string().contains("synthetic-value"));
    assert_eq!(configured["enabled"], false);
    let installed = f.install(&package("1.2.0", &[])).unwrap();
    assert!(
        installed["notice"]
            .as_str()
            .unwrap()
            .contains("OPENMATES_APP_PACKAGES_ENABLED --value true")
    );
}

#[test]
fn source_installations_check_target_skill_contract_and_builtin_ids() {
    let mut f = Fixture::new();
    f.c.install_mode = "source".into();
    let app = f.temp.path().join("backend/apps/events");
    std::fs::create_dir_all(&app).unwrap();
    for dir in ["backend", "backend/apps", "backend/apps/events"] {
        std::fs::set_permissions(
            f.temp.path().join(dir),
            std::fs::Permissions::from_mode(0o755),
        )
        .unwrap();
    }
    let definition = "skills:\n  - id: search\n    provider_contract: events.search@1\n    providers:\n      - id: builtin_provider\n";
    let write = |body: &str| {
        std::fs::write(app.join("app.yml"), body).unwrap();
        std::fs::set_permissions(app.join("app.yml"), std::fs::Permissions::from_mode(0o644))
            .unwrap();
    };
    write(definition);
    f.install(&package("1.0.0", &[])).unwrap();
    write(&definition.replace("builtin_provider", "my_events"));
    let error = f.install(&package("1.1.0", &[])).unwrap_err();
    assert!(error.to_string().contains("built-in provider"), "{error}");
    write("skills:\n  - id: search\n");
    assert!(f.install(&package("1.2.0", &[])).is_err());
    // An id used by any other app's providers or a provider config is refused too.
    write(definition);
    let other = f.temp.path().join("backend/apps/travel");
    std::fs::create_dir_all(&other).unwrap();
    std::fs::set_permissions(&other, std::fs::Permissions::from_mode(0o755)).unwrap();
    std::fs::write(
        other.join("app.yml"),
        "skills:\n  - id: search\n    providers:\n      - name: My Events\n",
    )
    .unwrap();
    std::fs::set_permissions(
        other.join("app.yml"),
        std::fs::Permissions::from_mode(0o644),
    )
    .unwrap();
    let error = f.install(&package("1.3.0", &[])).unwrap_err();
    assert!(error.to_string().contains("built-in provider"), "{error}");
    std::fs::remove_file(other.join("app.yml")).unwrap();
    let providers = f.temp.path().join("backend/providers");
    std::fs::create_dir_all(&providers).unwrap();
    std::fs::write(providers.join("my_events.yml"), "provider_id: my_events\n").unwrap();
    let error = f.install(&package("1.4.0", &[])).unwrap_err();
    assert!(error.to_string().contains("built-in provider"), "{error}");
}

#[test]
fn semantic_versions_order_by_precedence() {
    let mut versions = vec!["1.10.0", "1.2.0", "1.2.0-rc.1", "1.2.0-alpha", "0.9.9"];
    versions.sort_by(|a, b| archive::compare_versions(a, b));
    assert_eq!(
        versions,
        ["0.9.9", "1.2.0-alpha", "1.2.0-rc.1", "1.2.0", "1.10.0"]
    );
    assert!(!archive::semantic_version("01.0.0"));
    assert!(!archive::semantic_version("1.0"));
    assert!(archive::package_id("my.events"));
    assert!(!archive::package_id("events"));
    assert!(archive::provider_id("my_events"));
    assert!(!archive::provider_id("My-events"));
}
#[test]
fn startup_prepares_operator_owned_package_root_before_compose() {
    let fixture = Fixture::new();
    assert!(!fixture.root().exists());
    apps::prepare_root(&fixture.c).unwrap();
    assert_eq!(mode(&fixture.root()), 0o755);
    assert_eq!(mode(&fixture.root().join("packages")), 0o755);
    // Idempotent on every later start, and installs still succeed afterwards.
    apps::prepare_root(&fixture.c).unwrap();
    fixture.install(&package("1.0.0", &[])).unwrap();
}

fn generic_package(version: &str) -> Vec<u8> {
    let manifest = manifest(version).replace("events.search@1", "skill.requests@1");
    zip(&[
        ("manifest.yml", manifest.as_bytes()),
        ("bin/aarch64/provider", PROVIDER),
        ("bin/x86_64/provider", PROVIDER),
    ])
}
fn source_fixture(definition: &str) -> (Fixture, PathBuf) {
    let mut f = Fixture::new();
    f.c.install_mode = "source".into();
    let app = f.temp.path().join("backend/apps/events");
    std::fs::create_dir_all(&app).unwrap();
    for dir in ["backend", "backend/apps", "backend/apps/events"] {
        std::fs::set_permissions(
            f.temp.path().join(dir),
            std::fs::Permissions::from_mode(0o755),
        )
        .unwrap();
    }
    let file = app.join("app.yml");
    std::fs::write(&file, definition).unwrap();
    std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o644)).unwrap();
    (f, file)
}
fn rewrite(file: &Path, body: &str) {
    std::fs::write(file, body).unwrap();
    std::fs::set_permissions(file, std::fs::Permissions::from_mode(0o644)).unwrap();
}

#[test]
fn generic_contract_is_accepted_syntactically_without_a_source_checkout() {
    let f = Fixture::new();
    let output = f.install(&generic_package("1.0.0")).unwrap();
    assert_eq!(
        output["package"]["providers"][0]["id"].as_str(),
        Some("my_events")
    );
    // A different skill's own-form contract is still rejected.
    let wrong = manifest("1.1.0").replace("events.search@1", "events.other@1");
    let bytes = zip(&[
        ("manifest.yml", wrong.as_bytes()),
        ("bin/aarch64/provider", PROVIDER),
        ("bin/x86_64/provider", PROVIDER),
    ]);
    assert!(f.install(&bytes).is_err());
}

#[test]
fn generic_contract_needs_a_paused_skill_without_contract_or_providers() {
    let paused = "skills:\n  - id: search\n    provider_required: true\n";
    let (f, file) = source_fixture(paused);
    f.install(&generic_package("1.0.0")).unwrap();
    rewrite(
        &file,
        "skills:\n  - id: search\n    provider_required: true\n    providers: []\n",
    );
    f.install(&generic_package("1.1.0")).unwrap();
    for (version, body) in [
        ("1.2.0", "skills:\n  - id: search\n"),
        (
            "1.3.0",
            "skills:\n  - id: search\n    provider_required: false\n",
        ),
        (
            "1.4.0",
            "skills:\n  - id: search\n    provider_required: true\n    provider_contract: events.search@1\n",
        ),
        (
            "1.5.0",
            "skills:\n  - id: search\n    provider_required: true\n    providers:\n      - id: builtin_provider\n",
        ),
    ] {
        rewrite(&file, body);
        let error = f.install(&generic_package(version)).unwrap_err();
        assert!(
            error
                .to_string()
                .contains("does not accept installed providers"),
            "{version}: {error}"
        );
    }
    // The own-skill contract keeps requiring the skill's declared contract.
    rewrite(&file, paused);
    assert!(f.install(&package("2.0.0", &[])).is_err());
}

#[test]
fn first_install_creates_private_metadata_and_non_writable_package_root() {
    let f = Fixture::new();
    assert!(!f.temp.path().join(".openmates").exists());
    f.install(&package("1.0.0", &[])).unwrap();
    let metadata = f.temp.path().join(".openmates");
    assert_eq!(mode(&metadata), 0o700);
    for path in [
        f.root(),
        f.root().join("packages"),
        f.root().join("packages/my.events"),
        f.root().join("packages/my.events/1.0.0"),
    ] {
        assert_eq!(mode(&path) & 0o022, 0, "{path:?} is group/world writable");
    }
    assert_eq!(mode(&f.root().join("registry.json")) & 0o022, 0);
}

#[test]
fn first_install_creates_a_nested_custom_root_from_the_server_environment() {
    let f = Fixture::new();
    let custom = f.temp.path().join("data/packages-root");
    std::fs::write(
        f.temp.path().join(".env"),
        format!(
            "OPENMATES_APP_PACKAGES_ENABLED=true\nOPENMATES_APP_PACKAGES_DIR={}\n",
            custom.display()
        ),
    )
    .unwrap();
    f.install(&package("1.0.0", &[])).unwrap();
    assert_eq!(mode(&custom) & 0o022, 0);
    assert_eq!(mode(&custom.join("packages")), 0o755);
    assert!(custom.join("registry.json").is_file());
}

#[test]
fn restart_list_adds_routing_worker_only_when_the_compose_file_defines_it() {
    let f = Fixture::new();
    let fixed = RESTART_SERVICES
        .iter()
        .map(|s| (*s).to_owned())
        .collect::<Vec<_>>();
    assert_eq!(apps::restart_services(&f.c).unwrap(), fixed);
    let compose = f.temp.path().join("backend/core");
    std::fs::create_dir_all(&compose).unwrap();
    for dir in ["backend", "backend/core"] {
        std::fs::set_permissions(
            f.temp.path().join(dir),
            std::fs::Permissions::from_mode(0o755),
        )
        .unwrap();
    }
    let file = compose.join("docker-compose.selfhost.yml");
    rewrite(&file, "services:\n  api:\n    image: x\n");
    assert_eq!(apps::restart_services(&f.c).unwrap(), fixed);
    rewrite(&file, "services:\n  app-ai-routing-worker:\n    image: x\n");
    let mut with_routing = fixed;
    with_routing.push("app-ai-routing-worker".into());
    assert_eq!(apps::restart_services(&f.c).unwrap(), with_routing);
}

fn with_optional(version: &str, optional: &str) -> Vec<u8> {
    let manifest = manifest(version).replace(
        "secrets: [api_key]\n",
        &format!("secrets: [api_key]\n      optional_secrets: {optional}\n"),
    );
    zip(&[
        ("manifest.yml", manifest.as_bytes()),
        ("bin/aarch64/provider", PROVIDER),
        ("bin/x86_64/provider", PROVIDER),
    ])
}

#[test]
fn optional_secrets_are_validated_and_do_not_make_a_provider_unavailable() {
    let f = Fixture::new();
    for (version, bad) in [
        ("1.0.0", "[api_key]"),
        ("1.0.1", "[token, token]"),
        ("1.0.2", "[Bad-Name]"),
    ] {
        let error = f.install(&with_optional(version, bad)).unwrap_err();
        assert!(error.to_string().contains("optional_secrets"), "{error}");
    }
    f.install(&with_optional("1.1.0", "[token]")).unwrap();
    std::fs::write(
        f.temp.path().join(".env"),
        "SECRET__MY_EVENTS__API_KEY=synthetic-value\n",
    )
    .unwrap();
    std::fs::set_permissions(
        f.temp.path().join(".env"),
        std::fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    let shown = f.run("apps inspect", &["my.events".into()], &[]).unwrap();
    let provider = &shown["providers"][0];
    assert_eq!(provider["available"], true);
    assert_eq!(shown["missingSecrets"], 0);
    assert_eq!(provider["optionalSecrets"][0]["name"], "token");
    assert_eq!(provider["optionalSecrets"][0]["configured"], false);
}
