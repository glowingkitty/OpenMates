//! Replays the TS-generated hosted Project file vectors (`hosted_files_ts_vectors.json`).

use super::run_json;
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!("hosted_files_ts_vectors.json")).expect("vectors parse")
}

#[test]
fn hosted_file_ops_equal_typescript() {
    let doc = vectors();
    let ops = doc["ops"].as_object().expect("ops");
    assert_eq!(ops.len(), 3, "vector file covers every hosted file op");
    for (op, cases) in ops {
        for case in cases.as_array().expect("cases") {
            let output = run_json(op, &case["input"].to_string())
                .unwrap_or_else(|e| panic!("{op} {}: {e}", case["name"]));
            let actual: Value = serde_json::from_str(&output).expect("output json");
            assert_eq!(actual, case["expected"], "{op}: {}", case["name"]);
        }
    }
}

#[test]
fn hosted_list_caps_entries_at_five_hundred_visible_files() {
    let rows = |count: usize, hidden_index: usize| -> Value {
        (0..count)
            .map(|i| serde_json::json!({ "path": format!("f/{i}.txt"), "hidden": i == hidden_index }))
            .collect()
    };
    let list = |files: Value| -> Value {
        let input = serde_json::json!({ "files": files }).to_string();
        serde_json::from_str(&run_json("projectHostedList", &input).expect("list")).expect("json")
    };
    let exact = list(rows(501, 0));
    assert_eq!(exact["entries"].as_array().expect("entries").len(), 500);
    assert_eq!(
        exact["entries"][0],
        serde_json::json!({ "path": "f/1.txt", "kind": "file" })
    );
    assert_eq!(exact["truncated"], false);
    let over = list(rows(502, 3));
    assert_eq!(over["entries"].as_array().expect("entries").len(), 500);
    assert_eq!(over["entries"][499]["path"], "f/500.txt");
    assert_eq!(over["truncated"], true);
}

/// Mirrors `length limits count UTF-16 units` in `projectFilePolicyVectors.test.ts`.
#[test]
fn hosted_length_limits_count_utf16_units() {
    let long = format!("{}ab", "a/".repeat(2047));
    let paths = serde_json::json!({ "paths": [long, format!("{long}b")] }).to_string();
    let answer: Value =
        serde_json::from_str(&run_json("projectHostedPaths", &paths).expect("paths"))
            .expect("json");
    assert_eq!(
        answer,
        serde_json::json!({ "results": [{ "path": long }, { "code": "invalid_path" }] })
    );
    let plan = |args: Value| -> Value {
        let input = serde_json::json!({ "args": args, "files": [], "excluded": 0 }).to_string();
        serde_json::from_str(&run_json("projectHostedSearchPlan", &input).expect("plan"))
            .expect("json")
    };
    let refused = |code: &str| serde_json::json!({ "searchError": code });
    assert_eq!(
        plan(serde_json::json!({ "query": "q".repeat(2001) })),
        refused("invalid_search_query")
    );
    assert_eq!(
        plan(serde_json::json!({ "query": "q".repeat(2000) }))["search"]["query"],
        "q".repeat(2000)
    );
    assert_eq!(
        plan(serde_json::json!({ "query": "📁".repeat(1000) }))["search"]["query"],
        "📁".repeat(1000)
    );
    assert_eq!(
        plan(serde_json::json!({ "query": "📁".repeat(1001) })),
        refused("invalid_search_query")
    );
    assert_eq!(
        plan(serde_json::json!({ "query": "a", "path": "p".repeat(2048) }))["search"]["path"],
        "p".repeat(2048)
    );
    assert_eq!(
        plan(serde_json::json!({ "query": "a", "path": "p".repeat(2049) })),
        refused("invalid_search_path")
    );
    assert_eq!(
        plan(serde_json::json!({ "query": "a", "glob": "*".repeat(512) }))["search"]["glob"],
        "*".repeat(512)
    );
    assert_eq!(
        plan(serde_json::json!({ "query": "a", "glob": "*".repeat(513) })),
        refused("invalid_search_glob")
    );
    assert_eq!(
        plan(serde_json::json!({ "query": "a", "glob": "📁".repeat(257) })),
        refused("invalid_search_glob")
    );
}

#[test]
fn hosted_file_ops_refuse_malformed_input() {
    assert!(run_json("projectHostedPaths", "{}").is_err());
    assert!(run_json("projectHostedList", "{\"files\":[{\"path\":\"a\"}]}").is_err());
    assert!(
        run_json(
            "projectHostedSearchPlan",
            "{\"args\":null,\"files\":[],\"excluded\":0}"
        )
        .is_err()
    );
    assert!(
        run_json(
            "projectHostedSearchPlan",
            "{\"args\":{\"query\":\"a\"},\"files\":[]}"
        )
        .is_err()
    );
}
