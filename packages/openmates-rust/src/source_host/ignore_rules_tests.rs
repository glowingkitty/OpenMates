//! npm `ignore` semantics of the host's gitignore matcher.
use super::ignore_rules::{Matcher, candidate};

fn m(lines: &[&str]) -> Matcher {
    Matcher::new(lines.iter().copied(), false).expect("patterns compile")
}

#[test]
fn unanchored_names_match_at_any_depth() {
    let rules = m(&["node_modules", "*.log"]);
    assert!(rules.ignores("node_modules/"));
    assert!(rules.ignores("a/b/node_modules/"));
    assert!(rules.ignores("a/node_modules/x.js"));
    assert!(rules.ignores("deep/dir/debug.log"));
    assert!(!rules.ignores("src/main.rs"));
}

#[test]
fn slash_anchors_to_the_base() {
    let rules = m(&["/build", "docs/tmp"]);
    assert!(rules.ignores("build/"));
    assert!(!rules.ignores("src/build/"));
    assert!(rules.ignores("docs/tmp/x"));
    assert!(!rules.ignores("a/docs/tmp/x"));
}

#[test]
fn directory_only_patterns_skip_files() {
    let rules = m(&["cache/"]);
    assert!(rules.ignores(&candidate("cache", true)));
    assert!(!rules.ignores(&candidate("cache", false)));
    assert!(rules.ignores("cache/item.txt"));
}

#[test]
fn negation_reincludes_but_not_inside_ignored_parents() {
    let rules = m(&["*.txt", "!keep.txt"]);
    assert!(rules.ignores("a.txt"));
    assert!(!rules.ignores("keep.txt"));
    assert!(rules.test("keep.txt").unignored);
    let rules = m(&["out/", "!out/keep.txt"]);
    assert!(rules.ignores("out/keep.txt"), "an ignored parent decides");
}

#[test]
fn double_star_forms() {
    let rules = m(&["**/gen", "a/**/b", "logs/**"]);
    assert!(rules.ignores("gen/"));
    assert!(rules.ignores("x/y/gen/"));
    assert!(rules.ignores("a/b/"));
    assert!(rules.ignores("a/x/y/b/"));
    assert!(rules.ignores("logs/today"));
    assert!(!rules.ignores("logs/"), "`dir/**` matches contents, not the directory");
}

#[test]
fn comments_blank_lines_and_escapes() {
    let rules = m(&["# comment", "", "   ", "\\#hash", "\\!bang", "trail\\ "]);
    assert!(rules.ignores("#hash"));
    assert!(rules.ignores("!bang"));
    assert!(rules.ignores("trail "));
    assert!(!rules.ignores("comment"));
}

#[test]
fn character_classes_and_case() {
    let rules = m(&["file[0-9].txt", "[!a]x"]);
    assert!(rules.ignores("file3.txt"));
    assert!(!rules.ignores("filea.txt"));
    assert!(rules.ignores("bx"));
    assert!(!rules.ignores("ax"));
    assert!(!m(&["Secret"]).ignores("secret"));
    let insensitive = Matcher::new(["Secret"], true).expect("compiles");
    assert!(insensitive.ignores("secret"));
}
