// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::super::parity_test_support::{mock, parsed};
use super::*;
use serde_json::{Value, json};

fn apps() -> Value {
    json!({"apps":[{"id":"web","name":"web","skills":[{"id":"search","name":"search"}],
        "focus_modes":[],"settings_and_memories":[]}]})
}

#[test]
fn routes_list_and_search_only() {
    for args in [
        vec!["openmates", "mentions", "list", "--type", "mate"],
        vec!["openmates", "mentions", "search", "web"],
    ] {
        let invocation = parsed(&args);
        assert!(supported(&invocation));
        assert!(super::super::handlers::requirements(&invocation).supported);
    }
    assert!(!supported(&parsed(&["openmates", "chats", "list"])));
}

#[tokio::test]
async fn list_groups_by_type_with_npm_columns() {
    let (mut client, server) = mock(vec![apps()]).await;
    let out = execute(&parsed(&["openmates", "mentions", "list", "--type", "skill"]), &mut client)
        .await
        .ok()
        .unwrap();
    assert_eq!(out.stdout, format!("\nSkills\n  {:<35} Skill: Web \u{2192} Search\n", "@Web-Search"));
    assert!(server.await.unwrap()[0].starts_with("GET /v1/apps?include_unavailable=true "));
}

#[tokio::test]
async fn list_json_and_search_render_npm_shapes() {
    let (mut client, _server) = mock(vec![apps(), apps(), apps()]).await;
    let out = execute(&parsed(&["openmates", "mentions", "list", "--type", "mate", "--json"]), &mut client)
        .await
        .ok()
        .unwrap();
    let rows: Vec<Value> = serde_json::from_str(&out.stdout).unwrap();
    assert_eq!(rows[0], json!({"type":"mate","displayName":"@Sophia","description":"Mate: Software Development"}));
    let out = execute(&parsed(&["openmates", "mentions", "search", "web", "search"]), &mut client)
        .await
        .ok()
        .unwrap();
    assert!(out.stdout.starts_with("\nMatches for 'web search':\n"));
    assert!(out.stdout.contains("Skill: Web \u{2192} Search (skill)"));
    let out = execute(&parsed(&["openmates", "mentions", "search", "nonexistent-zzz"]), &mut client)
        .await
        .ok()
        .unwrap();
    assert_eq!(out.stdout, "No mentions matching 'nonexistent-zzz'.\n");
}

#[tokio::test]
async fn invalid_type_and_empty_query_fail_before_network() {
    let (mut client, _server) = mock(vec![]).await;
    match execute(&parsed(&["openmates", "mentions", "list", "--type", "bogus"]), &mut client).await {
        Err(CliError::Invalid(m)) => assert_eq!(
            m,
            "Invalid type 'bogus'. Valid types: model, model_alias, mate, skill, focus_mode, settings_memory"
        ),
        _ => panic!("expected invalid type"),
    }
}
