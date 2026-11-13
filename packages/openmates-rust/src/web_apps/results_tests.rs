//! Replays the TS-generated retention, outbox-scope and freshness vectors
//! (results_ts_vectors.json, produced by running the flag-off `retainAppsResult`,
//! `stagePendingAppsResult` scope check and `freshAppsRecommendations`).
use super::*;

fn resolve<'a>(root: &'a Value, path: &Value) -> &'a Value {
    path.as_array()
        .unwrap()
        .iter()
        .fold(root, |value, segment| match segment {
            Value::String(key) => &value[key.as_str()],
            index => &value[index.as_u64().unwrap() as usize],
        })
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn retention_plan_rebuilds_the_typescript_graph() {
    let vectors: Value = serde_json::from_str(include_str!("results_ts_vectors.json")).unwrap();
    for case in vectors["retention"].as_array().unwrap() {
        let name = &case["name"];
        let response = &case["response"];
        let plan: Value = serde_json::from_str(
            &retention_plan_json(
                &case["facts"].to_string(),
                &response.to_string(),
                case["previous"].as_str().unwrap(),
            )
            .unwrap(),
        )
        .unwrap();
        let out = &case["out"];
        if out["ok"] == json!(false) {
            assert_eq!(
                plan,
                json!({"kind":"error","message":out["message"]}),
                "{name}"
            );
            continue;
        }
        let embeds = out["embeds"].as_array().unwrap();
        let (root, children) = embeds.split_first().unwrap();
        assert_eq!(out["linked"], plan["persistedIds"], "{name}");
        assert_eq!(root["status"], plan["status"], "{name}");
        let content = &root["content"];
        assert_eq!(content["result_count"], plan["resultCount"], "{name}");
        assert_eq!(
            content.get("task_ids").cloned().unwrap_or(json!([])),
            plan["taskIds"],
            "{name}"
        );
        let child_ids: Vec<Value> = plan["children"]
            .as_array()
            .unwrap()
            .iter()
            .map(|c| c["id"].clone())
            .collect();
        let mut embed_ids = child_ids.clone();
        embed_ids.extend(plan["persistedIds"].as_array().unwrap().iter().cloned());
        assert_eq!(root["embed_ids"], json!(embed_ids), "{name}");
        if case["facts"]["childType"].is_null() {
            let results: Vec<Value> = plan["results"]
                .as_array()
                .unwrap()
                .iter()
                .map(|p| resolve(response, p).clone())
                .collect();
            assert_eq!(content["results"], json!(results), "{name}");
        } else {
            // A registered child type stores results only as child rows.
            assert!(content.get("results").is_none(), "{name}");
        }
        assert_eq!(children.len(), child_ids.len(), "{name}");
        for (row, child) in children.iter().zip(plan["children"].as_array().unwrap()) {
            assert_eq!(row["id"], child["id"], "{name}");
            assert_eq!(row["type"], child["type"], "{name}");
            assert_eq!(
                row["content"]["result"],
                *resolve(response, &child["path"]),
                "{name}"
            );
            assert_eq!(row["parent"], case["facts"]["rootId"], "{name}");
        }
        let resolved_ids: Vec<&Value> = plan["resultIds"].as_array().unwrap().iter().collect();
        for id in resolved_ids {
            assert!(
                child_ids.contains(id),
                "{name}: result id {id} must be a child"
            );
        }
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn outbox_scope_matches_typescript_validate_record() {
    let vectors: Value = serde_json::from_str(include_str!("results_ts_vectors.json")).unwrap();
    for case in vectors["scopes"].as_array().unwrap() {
        assert_eq!(
            outbox_scope_valid_json(&case["scope"].to_string()),
            Ok(case["valid"].as_bool().unwrap()),
            "{}",
            case["name"]
        );
    }
    assert_eq!(outbox_scope_valid_json("{}"), Err("protocol".into()));
    assert_eq!(pending_result_id("u", None, "r"), r#"["u",null,"r"]"#);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn fresh_recommendations_match_typescript_coercion() {
    let vectors: Value = serde_json::from_str(include_str!("results_ts_vectors.json")).unwrap();
    let freshness = &vectors["freshness"];
    let got = fresh_recommendations_json(
        &freshness["items"].to_string(),
        freshness["now"].as_f64().unwrap(),
    )
    .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&got).unwrap(),
        freshness["fresh"]
    );
    assert_eq!(
        fresh_recommendations_json("{}", 0.0),
        Err("protocol".into())
    );
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn stable_child_id_is_a_v4_shaped_sha256_prefix() {
    let id = stable_child_id("11111111-2222-4333-8444-555555555555", 0);
    assert_eq!(&id[..8], "9838ebaa");
    assert_eq!(id.as_bytes()[14], b'4');
    assert_eq!(stable_child_id("root", 1), stable_child_id("root", 1));
}
