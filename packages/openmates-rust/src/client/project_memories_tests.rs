//! Project Memory path filter and per-document send rules (web `listProjectRuleDocuments`).
use super::*;

const STYLE: &str = "---\ntitle: Press style\nwhen_to_use: When writing press releases.\nload_mode: auto_include\n---\nExample Solar GmbH, about 3,000 customers.\n";
const EXPIRED: &str = "---\ntitle: Trip\nvalid_until: 2020-01-01\n---\nIn Rome.\n";

#[test]
fn accepts_only_plain_markdown_files_in_memories_and_legacy_rules() {
    assert!(is_project_memory_path(".openmates/memories/press-style.md"));
    assert!(is_project_memory_path(".openmates/rules/Tone_1.md"));
    for path in [
        ".openmates/memories/.md",
        ".openmates/memories/a/b.md",
        ".openmates/memories/../x.md",
        ".openmates/memories/style.txt",
        ".openmates/facts/style.md",
        "memories/style.md",
        ".openmates/memories/stil ü.md",
    ] {
        assert!(!is_project_memory_path(path), "{path}");
    }
}

#[test]
fn sends_valid_memories_and_skips_expired_invalid_or_oversized_ones() {
    assert!(keep_project_memory(STYLE, 1_800_000_000_000));
    assert!(!keep_project_memory(EXPIRED, 1_800_000_000_000));
    assert!(!keep_project_memory("no frontmatter", 1_800_000_000_000));
    let big = format!("---\ntitle: Big\n---\n{}", "x".repeat(MAX_PROJECT_MEMORY_DOCUMENT_CHARS));
    assert!(!keep_project_memory(&big, 1_800_000_000_000));
}
