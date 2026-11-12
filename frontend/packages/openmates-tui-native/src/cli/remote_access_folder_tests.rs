// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
//! `remote-access new-projects-folder`: path validation, parsing and output.
use super::*;

fn invocation(args: &[&str]) -> Invocation {
    super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|error| panic!("{error}"))
        .invocation
        .unwrap()
}
fn code(result: Result<PathBuf, CliError>) -> String {
    match result {
        Ok(_) => "ok".into(),
        Err(CliError::Contract { code, message }) => format!("{code}: {message}"),
        Err(_) => "other".into(),
    }
}

#[test]
fn parses_set_show_and_clear_as_local_commands() {
    for (word, extra) in [
        ("set", Some("/srv/projects")),
        ("show", None),
        ("clear", None),
    ] {
        let mut args = vec!["openmates", "remote-access", "new-projects-folder", word];
        args.extend(extra);
        let i = invocation(&args);
        assert!(supported(&i), "{word}");
        assert!(!crate::cli::requirements(&i).authenticated, "{word}");
    }
}

#[test]
fn refuses_relative_missing_file_and_symlink_folders() {
    assert!(code(validated_folder("relative/dir")).contains("absolute"));
    assert!(code(validated_folder("/definitely/not/here")).contains("does not exist"));
    let dir = std::env::temp_dir().join(format!("om-npf-{}", uuid::Uuid::new_v4().simple()));
    std::fs::create_dir_all(&dir).unwrap();
    let file = dir.join("file");
    std::fs::write(&file, b"x").unwrap();
    let link = dir.join("link");
    std::os::unix::fs::symlink(&dir, &link).unwrap();
    assert!(code(validated_folder(&file.to_string_lossy())).contains("not a directory"));
    assert!(code(validated_folder(&link.to_string_lossy())).contains("symlink"));
    assert_eq!(code(validated_folder(&dir.to_string_lossy())), "ok");
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn formats_set_cleared_and_unset_states() {
    let i = invocation(&["openmates", "remote-access", "new-projects-folder", "show"]);
    let text = |folder: Option<&Path>, action| match folder_output(&i, folder, action) {
        Ok(out) => out.stdout.trim_end().to_owned(),
        Err(_) => panic!("unexpected CliError"),
    };
    assert!(text(None, "").contains("does not create"));
    assert_eq!(text(Some(Path::new("/srv/p")), ""), "/srv/p");
    assert!(text(Some(Path::new("/srv/p")), "set").contains("set: /srv/p"));
    assert!(text(None, "cleared").contains("no longer creates"));
}
