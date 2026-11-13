//! `create_source` against real temporary directories and real Git: happy path, name derivation, refusals that leave everything untouched, digest binding and capability gating.
use super::create_source::{self, CreateProposal};
use super::{host_capability_names, store};
use serde_json::json;
use std::fs;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};
use std::process::Command;

struct Fixture {
    _tmp: tempfile::TempDir,
    folder: PathBuf,
    home: PathBuf,
}

fn fixture(identity: bool) -> Fixture {
    let tmp = tempfile::tempdir().expect("tempdir");
    let base = fs::canonicalize(tmp.path()).expect("canonical");
    let folder = base.join("projects");
    let home = base.join("home");
    fs::create_dir(&folder).expect("folder");
    fs::create_dir(&home).expect("home");
    if identity {
        fs::write(
            home.join(".gitconfig"),
            "[user]\n\tname = Ada Example\n\temail = ada@example.org\n",
        )
        .expect("gitconfig");
    }
    Fixture {
        _tmp: tmp,
        folder,
        home,
    }
}

fn git(dir: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .arg("-C")
        .arg(dir)
        .args(args)
        .output()
        .expect("git runs");
    assert!(out.status.success(), "git {args:?}");
    String::from_utf8(out.stdout)
        .expect("utf8")
        .trim_end()
        .to_owned()
}

fn entries(dir: &Path) -> Vec<String> {
    let mut names: Vec<String> = fs::read_dir(dir)
        .expect("read_dir")
        .map(|e| e.expect("entry").file_name().to_string_lossy().into_owned())
        .collect();
    names.sort();
    names
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn creates_a_git_repository_on_main_with_readme_and_one_commit() {
    let fx = fixture(true);
    let created =
        create_source::create_source(&fx.folder, "Kitchen renovation", &fx.home).expect("created");
    assert_eq!(created.folder_name, "kitchen-renovation");
    assert_eq!(created.path, fx.folder.join("kitchen-renovation"));
    assert_eq!(created.branch, "main");
    let path = &created.path;
    assert_eq!(git(path, &["symbolic-ref", "--short", "HEAD"]), "main");
    assert_eq!(git(path, &["rev-list", "--count", "HEAD"]), "1");
    assert_eq!(git(path, &["rev-parse", "HEAD"]), created.head);
    assert_eq!(git(path, &["log", "-1", "--format=%s"]), "Initial commit");
    assert_eq!(
        git(path, &["log", "-1", "--format=%an <%ae>"]),
        "Ada Example <ada@example.org>"
    );
    assert_eq!(
        fs::read_to_string(path.join("README.md")).expect("readme"),
        "# Kitchen renovation\n"
    );
    assert_eq!(git(path, &["status", "--porcelain"]), "");
    let mode =
        std::os::unix::fs::PermissionsExt::mode(&fs::metadata(path).expect("meta").permissions());
    assert_eq!(mode & 0o777, 0o755);
    assert_eq!(created.to_json()["folder_name"], "kitchen-renovation");
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn derives_safe_folder_names() {
    let table = [
        ("Kitchen renovation", Some("kitchen-renovation")),
        ("  My   App!! v2  ", Some("my-app-v2")),
        ("..", None),
        ("-.hidden", Some("hidden")),
        ("../../etc/passwd", Some("etc-passwd")),
        ("a/b\\c", Some("a-b-c")),
        ("Caf\u{e9} Cr\u{e8}me", Some("caf-cr-me")),
        ("\u{65e5}\u{672c}\u{8a9e}", None),
        ("***", None),
    ];
    for (input, expected) in table {
        match (create_source::folder_name(input), expected) {
            (Ok(name), Some(want)) => assert_eq!(name, want, "{input}"),
            (Err(error), None) => assert_eq!(error.code, "invalid_project_name", "{input}"),
            (other, _) => panic!("{input}: {other:?}"),
        }
    }
    let long = create_source::folder_name(&format!("{} tail", "a".repeat(63))).expect("long");
    assert_eq!(long, "a".repeat(63));
    let cut = create_source::folder_name(&"word ".repeat(30)).expect("cut");
    assert!(cut.len() <= 64 && !cut.ends_with('-'));
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn refuses_existing_targets_of_every_kind_and_leaves_them_untouched() {
    let fx = fixture(true);
    let outside = fx.home.join("elsewhere");
    fs::create_dir(&outside).expect("outside");
    fs::create_dir(fx.folder.join("folder")).expect("dir");
    fs::write(fx.folder.join("folder").join("keep.txt"), "mine").expect("keep");
    fs::write(fx.folder.join("file"), "mine").expect("file");
    symlink(&outside, fx.folder.join("link")).expect("link");
    for name in ["folder", "file", "link"] {
        let error = create_source::create_source(&fx.folder, name, &fx.home).expect_err(name);
        assert_eq!(error.code, "target_exists", "{name}");
    }
    assert_eq!(
        fs::read_to_string(fx.folder.join("folder/keep.txt")).expect("keep"),
        "mine"
    );
    assert_eq!(entries(&fx.folder.join("folder")), vec!["keep.txt"]);
    assert_eq!(
        fs::read_to_string(fx.folder.join("file")).expect("file"),
        "mine"
    );
    assert!(entries(&outside).is_empty());
    assert_eq!(entries(&fx.folder), vec!["file", "folder", "link"]);
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn refuses_missing_symlinked_file_and_relative_configured_folders() {
    let fx = fixture(true);
    let real = fx.home.join("real");
    fs::create_dir(&real).expect("real");
    let link = fx.home.join("link");
    symlink(&real, &link).expect("link");
    let file = fx.home.join("plain-file");
    fs::write(&file, "x").expect("file");
    for dir in [
        fx.home.join("missing"),
        link,
        file,
        PathBuf::from("relative/dir"),
    ] {
        let error = create_source::create_source(&dir, "Demo", &fx.home).expect_err("refused");
        assert_eq!(error.code, "creation_folder_unavailable", "{dir:?}");
    }
    assert!(entries(&real).is_empty());
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn refuses_unusable_name_before_touching_the_folder() {
    let fx = fixture(true);
    let error = create_source::create_source(&fx.folder, "...", &fx.home).expect_err("refused");
    assert_eq!(error.code, "invalid_project_name");
    assert!(entries(&fx.folder).is_empty());
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn refuses_without_git_identity_and_creates_nothing() {
    let fx = fixture(false);
    let error = create_source::create_source(&fx.folder, "Demo", &fx.home).expect_err("refused");
    assert_eq!(error.code, "identity_missing");
    assert!(entries(&fx.folder).is_empty());
    // A name without an email is still no identity.
    fs::write(fx.home.join(".gitconfig"), "[user]\n\tname = Ada\n").expect("partial");
    let error = create_source::create_source(&fx.folder, "Demo", &fx.home).expect_err("partial");
    assert_eq!(error.code, "identity_missing");
    assert!(entries(&fx.folder).is_empty());
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn removes_only_its_own_folder_when_a_step_fails() {
    let fx = fixture(true);
    let plan = create_source::preflight(&fx.folder, "Demo", &fx.home).expect("plan");
    // A concurrent creator wins the path: the call must not enter or remove it.
    fs::create_dir(fx.folder.join("demo")).expect("racer");
    fs::write(fx.folder.join("demo/theirs.txt"), "x").expect("theirs");
    let error = create_source::create(&plan, "Demo").expect_err("exists");
    assert_eq!(error.code, "target_exists");
    assert_eq!(entries(&fx.folder.join("demo")), vec!["theirs.txt"]);
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn digest_binds_every_proposal_field_and_the_project_key() {
    let key = [7u8; 32];
    let proposal = CreateProposal {
        operation_id: "op-1".into(),
        project_name: "Kitchen renovation".into(),
    };
    let base = create_source::digest(&key, "proj", "chat", &proposal).expect("digest");
    assert_eq!(base.len(), 64);
    assert_eq!(
        base,
        create_source::digest(&key, "proj", "chat", &proposal).expect("again")
    );
    let other_op = CreateProposal {
        operation_id: "op-2".into(),
        ..proposal.clone()
    };
    let other_name = CreateProposal {
        project_name: "Kitchen".into(),
        ..proposal.clone()
    };
    for changed in [
        create_source::digest(&key, "proj2", "chat", &proposal),
        create_source::digest(&key, "proj", "chat2", &proposal),
        create_source::digest(&key, "proj", "chat", &other_op),
        create_source::digest(&key, "proj", "chat", &other_name),
        create_source::digest(&[8u8; 32], "proj", "chat", &proposal),
    ] {
        assert_ne!(changed.expect("digest"), base);
    }
    assert_eq!(
        create_source::digest(&key, "", "chat", &proposal)
            .expect_err("empty")
            .code,
        "invalid_request"
    );
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn validates_the_create_arguments() {
    let ok = create_source::validate(&json!({"operation_id": "op-1", "project_name": "Demo"}));
    assert_eq!(ok.expect("valid").project_name, "Demo");
    for bad in [
        json!(null),
        json!({"operation_id": "op-1"}),
        json!({"operation_id": "op 1", "project_name": "Demo"}),
        json!({"operation_id": "op-1", "project_name": "  "}),
        json!({"operation_id": "op-1", "project_name": "a\nb"}),
        json!({"operation_id": "op-1", "project_name": "Demo", "path": "/etc"}),
    ] {
        assert_eq!(
            create_source::validate(&bad).expect_err("bad").code,
            "invalid_request",
            "{bad}"
        );
    }
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn capability_is_advertised_only_when_the_folder_is_configured() {
    let fx = fixture(true);
    assert!(!host_capability_names(true, false).contains(&"create_source"));
    assert!(host_capability_names(false, true).contains(&"create_source"));
    let state = fx.home.join("state");
    assert_eq!(store::load_new_projects_dir(&state).expect("unset"), None);
    let error = create_source::configured_folder(&state).expect_err("unset");
    assert_eq!(error.code, "creation_not_configured");
    store::save_new_projects_dir(&state, Some(&fx.folder)).expect("save");
    assert_eq!(
        store::load_new_projects_dir(&state).expect("set"),
        Some(fx.folder.clone())
    );
    assert_eq!(
        create_source::configured_folder(&state).expect("set"),
        fx.folder
    );
    assert!(store::save_new_projects_dir(&state, Some(Path::new("relative"))).is_err());
    store::save_new_projects_dir(&state, None).expect("clear");
    assert_eq!(
        create_source::configured_folder(&state)
            .expect_err("cleared")
            .code,
        "creation_not_configured"
    );
}
