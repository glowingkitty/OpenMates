//! Replays TypeScript-generated vectors (web_apps_ts_vectors.json, checked
//! against the web service by appsSkillVectors.test.ts) against the shared
//! Rust Apps skill execution policy, driving the same orchestration as the web
//! adapter (rustAppsSkillExecution.ts) over scripted responses.
use super::*;
use std::collections::{HashMap, VecDeque};

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_apps_ts_vectors.json")).unwrap()
}
fn parse(text: &str) -> Value {
    serde_json::from_str(text).unwrap()
}
fn s(value: &Value) -> &str {
    value.as_str().unwrap()
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn error_detail_failure_and_task_ids_equal_typescript() {
    let v = vectors();
    for case in v["errorDetail"].as_array().unwrap() {
        assert_eq!(error_detail(&case["body"], case["status"].as_u64().unwrap() as u16), s(&case["out"]), "{case}");
    }
    for case in v["errorDetailRaw"].as_array().unwrap() {
        assert_eq!(error_detail(&parse(s(&case["text"])), case["status"].as_u64().unwrap() as u16), s(&case["out"]));
    }
    for case in v["failure"].as_array().unwrap() {
        assert_eq!(skill_failure(&case["body"]).map(Value::from).unwrap_or(Value::Null), case["out"], "{case}");
    }
    for case in v["taskIds"].as_array().unwrap() {
        assert_eq!(json!(accepted_task_ids(&case["envelope"])), case["out"], "{case}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn details_and_availability_equal_typescript() {
    let v = vectors();
    for case in v["details"].as_array().unwrap() {
        let request = parse(&details_request_json(s(&case["app"]), s(&case["skill"]), true));
        assert_eq!(request["path"], case["url"]);
        assert_eq!(request["credentials"], case["credentials"]);
        assert_eq!(request["cacheable"], json!(false));
        let response = &case["response"];
        let status = response["status"].as_u64().unwrap() as u16;
        let outcome = parse(&details_outcome_json(status, (200..300).contains(&status), s(&response["text"])));
        let got = if outcome["kind"] == "error" {
            json!({"ok":false,"message":outcome["message"]})
        } else {
            json!({"ok":true,"value": if outcome["valid"] == json!(true) { parse(s(&response["text"])) } else { json!({}) }})
        };
        assert_eq!(got, case["out"], "{case}");
    }
    for case in v["availability"].as_array().unwrap() {
        assert_eq!(parse(&availability_request_json("web", "search"))["path"], case["url"]);
        let response = &case["response"];
        let status = response["status"].as_u64().unwrap() as u16;
        assert_eq!(parse(&availability_outcome_json(status, (200..300).contains(&status), s(&response["text"]))), case["out"], "{case}");
    }
}

struct Routes {
    queues: HashMap<String, VecDeque<(u16, String)>>,
    calls: Vec<String>,
}
impl Routes {
    fn fetch(&mut self, key: &str) -> (u16, bool, String) {
        self.calls.push(key.to_owned());
        let (status, text) = self.queues.get_mut(key).and_then(VecDeque::pop_front).unwrap_or_else(|| panic!("unscripted {key}"));
        (status, (200..300).contains(&status), text)
    }
}

fn poll(routes: &mut Routes, id: &str) -> Result<String, String> {
    loop {
        let (status, ok, text) = routes.fetch(&format!("GET /v1/tasks/{id}"));
        let step = parse(&poll_step_json(id, status, ok, &text));
        match s(&step["kind"]) {
            "completed" => return Ok(text),
            "error" => return Err(s(&step["message"]).to_owned()),
            _ => assert_eq!(step["delayMs"], json!(2000)),
        }
    }
}

/// The adapter's executeOnce + resolveAccepted, decision for decision.
fn execute(case: &Value, routes: &mut Routes) -> Result<Value, String> {
    let (app, skill, guest) = (s(&case["app"]), s(&case["skill"]), case["guest"].as_bool().unwrap());
    let team = case["teamId"].as_str().unwrap_or("");
    let request = parse(&execution_request_json(app, skill, guest, team, &case["metadata"].to_string()).unwrap());
    if request["kind"] == "error" {
        return Err(s(&request["message"]).to_owned());
    }
    if let Some(path) = request["availabilityPath"].as_str() {
        let (status, ok, text) = routes.fetch(&format!("POST {path}"));
        let quote = parse(&availability_outcome_json(status, ok, &text));
        if quote["allowed"] != json!(true) {
            return Err(quote["reason"].as_str().unwrap_or("signup_required").to_owned());
        }
    }
    let mut key = format!("POST {}", s(&request["path"]));
    if let Some(team) = request["teamId"].as_str() {
        key.push_str(&format!("?team_id={team}"));
    }
    let (status, ok, text) = routes.fetch(&key);
    let outcome = parse(&skill_response_json(status, ok, &text, guest));
    match s(&outcome["kind"]) {
        "error" => Err(s(&outcome["message"]).to_owned()),
        "done" => Ok(if outcome["valid"] == json!(true) { parse(&text) } else { json!({}) }),
        _ => {
            let mut polls = Vec::new();
            for id in outcome["ids"].as_array().unwrap() {
                polls.push(poll(routes, s(id))?);
            }
            let assembled = parse(&assemble_tasks_json(&text, &serde_json::to_string(&polls).unwrap(), true).unwrap());
            if assembled["kind"] == "error" {
                return Err(s(&assembled["message"]).to_owned());
            }
            Ok(parse(s(&assembled["text"])))
        }
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn skill_execution_equals_typescript() {
    for case in vectors()["execute"].as_array().unwrap() {
        let queues = case["routes"].as_object().unwrap().iter().map(|(key, responses)| {
            (key.clone(), responses.as_array().unwrap().iter().map(|r| (r["status"].as_u64().unwrap() as u16, s(&r["text"]).to_owned())).collect())
        }).collect();
        let mut routes = Routes { queues, calls: Vec::new() };
        let got = match execute(case, &mut routes) {
            Ok(value) => json!({"ok":true,"value":value}),
            Err(message) => json!({"ok":false,"message":message}),
        };
        assert_eq!(got, case["out"], "{}", case["name"]);
        routes.calls.sort();
        assert_eq!(json!(routes.calls), case["calls"], "{}", case["name"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn assembled_envelope_keeps_source_order_and_number_spelling() {
    let envelope = r#"{"z":1,"data":{"task_id":"t"},"a":1.50,"z":2}"#;
    let poll = r#"{"task_id":"t","status":"completed","result":{"y":1e2,"b":[3,1]}}"#;
    let out = parse(&assemble_tasks_json(envelope, &json!([poll]).to_string(), true).unwrap());
    // JSON.parse keeps a repeated key at its first position with its last value.
    assert_eq!(s(&out["text"]), r#"{"z":2,"data":{"y":1e2,"b":[3,1]},"a":1.50}"#);
    let two = parse(&assemble_tasks_json(r#"{"x":0}"#, &json!([poll, r#"{"status":"completed"}"#]).to_string(), true).unwrap());
    assert_eq!(s(&two["text"]), r#"{"x":0,"data":[{"y":1e2,"b":[3,1]},null]}"#);
    let failed = r#"{"status":"completed","result":{"success":false}}"#;
    assert_eq!(parse(&assemble_tasks_json("{}", &json!([failed]).to_string(), true).unwrap())["kind"], "error");
    assert_eq!(parse(&assemble_tasks_json("{}", &json!([failed]).to_string(), false).unwrap())["kind"], "done");
    assert_eq!(assemble_tasks_json("[1]", "[]", true), Err("protocol".into()));
    assert_eq!(parse(&task_result_json(poll).unwrap())["text"], json!(r#"{"y":1e2,"b":[3,1]}"#));
    assert_eq!(parse(&task_result_json(r#"{"status":"completed"}"#).unwrap())["kind"], "absent");
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn details_cache_policy_and_poll_budget() {
    assert_eq!(parse(&details_request_json("web", "search", false))["cacheable"], json!(true));
    assert_eq!(parse(&details_request_json("mail", "search", false))["cacheable"], json!(false));
    let retry = parse(&poll_step_json("t", 200, true, r#"{"status":"processing"}"#));
    assert_eq!(retry["deadlineMs"], json!(600000));
    assert_eq!(s(&retry["timeoutMessage"]), "Task t is still processing; retain its ID to reopen the result.");
    assert_eq!(parse(&poll_step_json("t", 200, true, "null"))["kind"], "error");
    assert_eq!(parse(&skill_response_json(200, true, "null", false))["message"], "invalid_skill_response");
    assert_eq!(parse(&skill_response_json(200, true, r#"{"task_id":"x"}"#, true))["kind"], "done");
    assert_eq!(execution_request_json("web", "search", false, "", "nope"), Err("protocol".into()));
    for (value, text) in [(0.1, "0.1"), (1e21, "1e+21"), (123456789012.0, "123456789012"), (-1.5e-9, "-1.5e-9"), (2.5e-6, "0.0000025")] {
        assert_eq!(js_number(value), text);
    }
}
