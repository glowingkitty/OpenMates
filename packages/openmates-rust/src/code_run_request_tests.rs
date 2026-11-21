// contract-test: supporting surface=rust assertions=cli.migration.complete-compatible
use super::*;

fn file(path: &str, body: &str) -> CodeRunFile {
    CodeRunFile {
        path: path.into(),
        content: body.as_bytes().to_vec(),
        language: None,
    }
}

#[test]
fn unsafe_paths_are_refused() {
    for bad in ["", "/etc/x", "~/x", "C:/x", "a/../b", "a//b", "./a", "a\0b"] {
        assert!(matches!(normalize_path(bad), Err(CodeRunError::UnsafePath(_))), "{bad}");
    }
    assert_eq!(normalize_path(" src\\main.py ").unwrap_or_default(), "src/main.py");
}

#[test]
fn body_shape_and_entry_selection() {
    let body = build_direct_request(vec![file("a.py", "x"), file("b.js", "y")], Some("b.js"), false, true)
        .unwrap_or_default();
    assert_eq!(body["allow_e2b_upload"], true);
    let request = &body["requests"][0];
    assert_eq!(request["entry_path"], "b.js");
    assert_eq!(request["enable_internet"], false);
    assert_eq!(request["files"][0]["is_target"], false);
    assert_eq!(request["files"][1]["is_target"], true);
    assert_eq!(request["files"][1]["language"], "javascript");
    assert_eq!(request["files"][0]["content_base64"], "eA==");
    let default = build_direct_request(vec![file("a.py", "x")], None, true, false).unwrap_or_default();
    assert!(default.get("allow_e2b_upload").is_none());
    assert_eq!(default["requests"][0]["entry_path"], "a.py");
}

#[test]
fn limits_duplicates_and_missing_entry_are_typed() {
    assert_eq!(
        build_direct_request(vec![file("a", ""), file("a", "")], None, true, false),
        Err(CodeRunError::DuplicatePath("a".into()))
    );
    let many = (0..51).map(|i| file(&format!("f{i}"), "")).collect();
    assert_eq!(build_direct_request(many, None, true, false), Err(CodeRunError::TooManyFiles));
    let big = file("big", &"x".repeat(MAX_FILE_BYTES + 1));
    assert_eq!(build_direct_request(vec![big], None, true, false), Err(CodeRunError::FileTooLarge("big".into())));
    let bundle = (0..11).map(|i| file(&format!("f{i}"), &"x".repeat(MAX_FILE_BYTES))).collect();
    assert_eq!(build_direct_request(bundle, None, true, false), Err(CodeRunError::BundleTooLarge));
    assert_eq!(build_direct_request(vec![], None, true, false), Err(CodeRunError::NoFiles));
    assert_eq!(
        build_direct_request(vec![file("a", "")], Some("b"), true, false),
        Err(CodeRunError::EntryMissing("b".into()))
    );
}

#[test]
fn inline_file_names_and_language() {
    let f = inline_file("print(1)", Some("python"), None, None).unwrap_or_else(|_| file("", ""));
    assert_eq!((f.path.as_str(), f.language.as_deref()), ("main.py", Some("python")));
    assert_eq!(inline_file("x", None, Some("s.sh"), Some("e.py")).map(|f| f.path), Ok("s.sh".into()));
    assert_eq!(inline_file("x", None, None, Some("e.py")).map(|f| f.path), Ok("e.py".into()));
}

#[test]
fn patterns_match_like_the_npm_cli() {
    assert!(matches_any("src/a.test.js", &["*.test.js"]));
    assert!(matches_any("node_modules/x/y.js", &["node_modules"]));
    assert!(matches_any("pkg/build", &["build"]));
    assert!(!matches_any("builder.py", &["build"]));
    assert!(matches_any("a/b/c.py", &["a"]));
    assert!(!matches_any("a.py", &[""]));
}

#[test]
fn final_status_formatting() {
    let status = json!({"output":"hi","artifacts":[{"path":"o.png","mime_type":"image/png","size_bytes":5,"download_url":"u"},{"normalized_path":"p"}],
        "skipped_artifacts":[{"path":"big.bin","reason":"too_large"}]});
    assert_eq!(
        format_final_status(&status),
        "hi\n\nArtifacts:\n- o.png (image/png, 5 bytes; signed download available via --json)\n- p (application/octet-stream, unknown size)\n\nSkipped artifacts:\n- big.bin (too_large)\n"
    );
    assert_eq!(format_final_status(&json!({})), "");
}
