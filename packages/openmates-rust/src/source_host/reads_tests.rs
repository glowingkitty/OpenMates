//! Host read operations: listing, bounded text reads, chunks and result bounds.
use super::reads::{
    HostRoot, RESULT_MAX_BYTES, count_lines, list, raster_mime, read_file_chunk, read_image_chunk, read_text,
    serialize_success,
};
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
    fs::write(root.join(".gitignore"), "build/\n").expect("write");
    fs::create_dir_all(root.join("src/nested")).expect("dirs");
    fs::create_dir_all(root.join("build")).expect("dirs");
    fs::write(root.join("README.md"), "# Title\nbody\n").expect("write");
    fs::write(root.join("src/main.rs"), "fn main() {}\n").expect("write");
    fs::write(root.join("src/nested/deep.txt"), "deep\n").expect("write");
    fs::write(root.join("build/out.txt"), "generated\n").expect("write");
    fs::write(root.join(".env"), "SECRET=1\n").expect("write");
    fs::write(root.join("logo.png"), [137, 80, 78, 71, 13, 10, 26, 10, 0, 0]).expect("write");
    Fixture {
        host: HostRoot {
            root,
            state_dir: state.path().to_path_buf(),
            policy_source: None,
        },
        _source: source,
        _state: state,
    }
}

fn paths(result: &Value) -> Vec<String> {
    result["entries"]
        .as_array()
        .expect("entries")
        .iter()
        .map(|e| e["path"].as_str().expect("path").to_owned())
        .collect()
}

#[test]
fn list_hides_dotfiles_ignored_and_private_entries() {
    let f = fixture();
    let result = list(&f.host, &json!({"path": "."})).expect("lists");
    assert_eq!(paths(&result), vec!["logo.png", "README.md", "src"]);
    assert_eq!(result["excluded"], 4, ".env, .git, .gitignore, build");
    assert_eq!(result["truncated"], false);
    let entries = result["entries"].as_array().expect("entries");
    assert_eq!(entries[0]["previewable"], false);
    assert_eq!(entries[1]["sizeBytes"], 13);
    assert_eq!(entries[2]["childFolderCount"], 1);
    assert_eq!(entries[2]["childFileCount"], 1);
    assert_eq!(entries[2]["children"][0]["path"], "src/nested");
}

#[test]
fn list_pages_with_a_basename_cursor() {
    let f = fixture();
    let first = list(&f.host, &json!({"path": ".", "maxEntries": 2})).expect("lists");
    assert_eq!(paths(&first), vec!["logo.png", "README.md"]);
    assert_eq!(first["nextCursor"], "README.md");
    assert_eq!(first["omitted"], 1);
    let second = list(&f.host, &json!({"path": ".", "maxEntries": 2, "cursor": "README.md"})).expect("lists");
    assert_eq!(paths(&second), vec!["src"]);
    assert!(second.get("nextCursor").is_none());
}

#[test]
fn list_refuses_ignored_directories_and_bad_bounds() {
    let f = fixture();
    assert_eq!(list(&f.host, &json!({"path": "build"})).expect_err("ignored").code, "protected_path");
    assert_eq!(list(&f.host, &json!({"path": "README.md"})).expect_err("file").code, "invalid_path");
    assert_eq!(list(&f.host, &json!({"maxEntries": 0})).expect_err("bound").code, "operation_failed");
    assert_eq!(list(&f.host, &json!({"cursor": "a/b"})).expect_err("cursor").code, "operation_failed");
}

#[test]
fn read_text_returns_content_and_expected_base() {
    let f = fixture();
    let result = read_text(&f.host, &json!({"path": "README.md"}), false).expect("reads");
    assert_eq!(result["content"], "# Title\nbody\n");
    assert_eq!(result["lineCount"], 2);
    assert_eq!(result["truncated"], false);
    assert_eq!(result["sizeBytes"], 13);
    assert_eq!(
        result["expected_base"],
        super::sha256_hex(b"# Title\nbody\n").as_str()
    );
}

#[test]
fn read_text_truncates_by_lines_and_bytes_without_expected_base() {
    let f = fixture();
    let lines = read_text(&f.host, &json!({"path": "README.md", "max_lines": 1}), false).expect("reads");
    assert_eq!(lines["content"], "# Title\n");
    assert_eq!(lines["truncated"], true);
    assert_eq!(lines["expected_base"], Value::Null);
    let bytes = read_text(&f.host, &json!({"path": "README.md", "max_bytes": 3}), false).expect("reads");
    assert_eq!(bytes["content"], "# T");
}

#[test]
fn read_text_enforces_policy_and_binary_detection() {
    let f = fixture();
    let read = |path: &str, approved: bool| read_text(&f.host, &json!({"path": path}), approved);
    assert_eq!(read(".env", false).expect_err("private").code, "protected_path");
    assert_eq!(read(".env", true).expect_err("private even approved").code, "protected_path");
    assert_eq!(
        read("build/out.txt", false).expect_err("ignored").code,
        "ignored_path_requires_approval"
    );
    assert_eq!(read("build/out.txt", true).expect("approved")["content"], "generated\n");
    assert_eq!(read("logo.png", false).expect_err("binary").code, "unsupported_file");
    assert_eq!(read("missing.txt", false).expect_err("missing").code, "invalid_path");
    assert!(read("../outside", false).is_err());
}

#[test]
fn symlinks_and_hardlinks_never_escape() {
    let f = fixture();
    let outside = tempfile::tempdir().expect("tempdir");
    fs::write(outside.path().join("secret.txt"), "outside\n").expect("write");
    std::os::unix::fs::symlink(outside.path().join("secret.txt"), f.host.root.join("link.txt")).expect("symlink");
    std::os::unix::fs::symlink(outside.path(), f.host.root.join("linkdir")).expect("symlink");
    assert!(read_text(&f.host, &json!({"path": "link.txt"}), false).is_err());
    assert!(read_text(&f.host, &json!({"path": "linkdir/secret.txt"}), false).is_err());
    fs::hard_link(f.host.root.join("README.md"), f.host.root.join("hard.md")).expect("hardlink");
    assert!(read_text(&f.host, &json!({"path": "hard.md"}), false).is_err());
    let listed = paths(&list(&f.host, &json!({})).expect("lists"));
    assert!(!listed.iter().any(|p| p == "link.txt" || p == "linkdir" || p == "hard.md"));
}

#[test]
fn file_and_image_chunks_validate_offsets() {
    let f = fixture();
    let chunk = read_file_chunk(&f.host, &json!({"path": "README.md", "offset": 0})).expect("chunk");
    assert_eq!(chunk["size_bytes"], 13);
    assert_eq!(chunk["chunk_hash"], super::sha256_hex(b"# Title\nbody\n").as_str());
    assert!(read_file_chunk(&f.host, &json!({"path": "README.md", "offset": 7})).is_err());
    let image = read_image_chunk(&f.host, &json!({"path": "logo.png", "offset": 0})).expect("image");
    assert_eq!(image["mime_type"], "image/png");
    assert_eq!(
        read_image_chunk(&f.host, &json!({"path": "README.md", "offset": 0})).expect_err("not image").code,
        "unsupported_file"
    );
}

#[test]
fn raster_mime_sniffs_magic_bytes() {
    assert_eq!(raster_mime(b"GIF89a..."), Some("image/gif"));
    assert_eq!(raster_mime(&[255, 216, 255, 0]), Some("image/jpeg"));
    assert_eq!(raster_mime(b"RIFF\0\0\0\0WEBP"), Some("image/webp"));
    assert_eq!(raster_mime(b"<svg>"), None);
}

#[test]
fn line_counts_match_npm() {
    assert_eq!(count_lines(""), 0);
    assert_eq!(count_lines("a"), 1);
    assert_eq!(count_lines("a\n"), 1);
    assert_eq!(count_lines("a\nb"), 2);
}

#[test]
fn oversized_text_results_are_cut_to_fit() {
    let content = "x".repeat(RESULT_MAX_BYTES + 10);
    let result = json!({"content": content, "truncated": false, "sizeBytes": 1, "lineCount": 1, "expected_base": "abc"});
    let text = serialize_success(result);
    assert!(text.len() <= RESULT_MAX_BYTES);
    let parsed: Value = serde_json::from_str(&text).expect("json");
    assert_eq!(parsed["ok"], true);
    assert_eq!(parsed["result"]["truncated"], true);
    assert_eq!(parsed["result"]["expected_base"], Value::Null);
    assert!(parsed["result"]["content"].as_str().expect("content").len() > RESULT_MAX_BYTES - 200);
    let other = serialize_success(json!({"blob": "y".repeat(RESULT_MAX_BYTES)}));
    let other: Value = serde_json::from_str(&other).expect("json");
    assert_eq!(other, json!({"ok": false, "error": "operation_failed"}));
}
