//! Host search: filename search, content search (ripgrep or literal fallback) and rg parsing.
use super::reads::HostRoot;
use super::search::{normalize_rg_path, parse_rg_match, search, within};
use serde_json::{Value, json};
use std::fs;

struct Fixture {
    _source: tempfile::TempDir,
    _state: tempfile::TempDir,
    host: HostRoot,
}

fn fixture() -> Fixture {
    let source = tempfile::tempdir().expect("tempdir");
    let state = tempfile::tempdir().expect("tempdir");
    let root = fs::canonicalize(source.path()).expect("canonical");
    fs::create_dir(root.join(".git")).expect("git");
    fs::write(root.join(".gitignore"), "dist/\n").expect("write");
    fs::create_dir_all(root.join("src/widgets")).expect("dirs");
    fs::create_dir_all(root.join("dist")).expect("dirs");
    fs::write(root.join("src/widget.ts"), "export const needle = 1;\n").expect("write");
    fs::write(root.join("src/widgets/a.ts"), "nothing here\n").expect("write");
    fs::write(root.join("dist/widget.js"), "needle\n").expect("write");
    fs::write(root.join(".env"), "needle=secret\n").expect("write");
    Fixture {
        host: HostRoot {
            root,
            state_dir: state.path().to_path_buf(),
        },
        _source: source,
        _state: state,
    }
}

fn match_paths(result: &Value) -> Vec<String> {
    result["matches"]
        .as_array()
        .expect("matches")
        .iter()
        .map(|m| m["path"].as_str().expect("path").to_owned())
        .collect()
}

#[test]
fn filename_search_skips_ignored_private_and_hidden() {
    let f = fixture();
    let result = search(&f.host, &json!({"query": "widget", "target": "files"})).expect("searches");
    // Names match on the whole relative path, like npm.
    assert_eq!(match_paths(&result), vec!["src/widget.ts", "src/widgets", "src/widgets/a.ts"]);
    assert_eq!(result["truncated"], false);
}

#[test]
fn filename_search_respects_limits_and_regex() {
    let f = fixture();
    let limited = search(&f.host, &json!({"query": "widget", "target": "files", "max_results": 1})).expect("searches");
    assert_eq!(match_paths(&limited).len(), 1);
    assert_eq!(limited["omitted"], 2);
    assert_eq!(limited["truncated"], true);
    let regex = search(&f.host, &json!({"query": "a\\.ts$", "target": "files", "mode": "regex"})).expect("searches");
    assert_eq!(match_paths(&regex), vec!["src/widgets/a.ts"]);
}

#[test]
fn filename_search_can_include_bounded_content() {
    let f = fixture();
    let result = search(
        &f.host,
        &json!({"query": "widget", "target": "files", "include_content": true}),
    )
    .expect("searches");
    assert_eq!(result["contents"][0]["path"], "src/widget.ts");
    assert_eq!(result["contents"][0]["content"], "export const needle = 1;\n");
    assert_eq!(result["content_omissions"][0]["reason"], "directory");
    assert_eq!(result["content_incomplete"], true);
}

#[test]
fn content_search_finds_lines_outside_ignored_and_private_files() {
    let f = fixture();
    let result = search(&f.host, &json!({"query": "needle"})).expect("searches");
    assert_eq!(match_paths(&result), vec!["src/widget.ts"]);
    assert_eq!(result["matches"][0]["line"], 1);
}

#[test]
fn ignored_or_private_search_paths_are_protected() {
    let f = fixture();
    let refused = search(&f.host, &json!({"query": "x", "path": "dist"})).expect_err("ignored");
    assert_eq!(refused.code, "protected_path");
    let invalid = search(&f.host, &json!({"query": "x", "target": "nope"})).expect_err("invalid");
    assert_eq!(invalid.code, "invalid_search_target");
}

#[test]
fn rg_output_parsing_rejects_escaping_paths() {
    let line = r#"{"type":"match","data":{"path":{"text":"./src/a.ts"},"line_number":3,"lines":{"text":"hit\n"}}}"#;
    assert_eq!(
        parse_rg_match(line),
        Some(("src/a.ts".to_owned(), 3, "hit\n".to_owned()))
    );
    assert_eq!(parse_rg_match(r#"{"type":"begin"}"#), None);
    assert_eq!(normalize_rg_path("../etc/passwd"), None);
    assert_eq!(normalize_rg_path("/abs"), None);
    assert_eq!(normalize_rg_path("a\\b"), Some("a/b".to_owned()));
    assert!(within("src/a.ts", "src"));
    assert!(!within("srcx/a.ts", "src"));
    assert!(within("anything", "."));
}
