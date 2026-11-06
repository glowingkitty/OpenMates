//! Replays the TS-generated natural-language request vectors
//! (request_ts_vectors.json, checked against appsWorkspaceRequestService.ts by
//! appsRequestVectors.test.ts), driving the same decisions as the web adapter
//! (rustAppsRequest.ts). The privacy transform stays on the page, so the vectors
//! carry its exact JSON output as `pieces`.
use super::*;
use crate::web_apps::schema::validate_skill_input;

/// Expands `@@R:<unit>:<count>@@` runs (long bound-test strings) before parsing.
pub(crate) fn expand_vectors(text: &str) -> Value {
    let runs = regex::Regex::new("@@R:([^:@]*):([0-9]+)@@").unwrap();
    let expanded = runs.replace_all(text, |c: &regex::Captures| {
        c[1].repeat(c[2].parse().unwrap())
    });
    serde_json::from_str(&expanded).unwrap()
}

fn parse(text: &str) -> Value {
    serde_json::from_str(text).unwrap()
}
fn s(value: &Value) -> &str {
    value.as_str().unwrap_or("")
}
fn restore(value: &Value) -> Value {
    match value {
        Value::String(text) => Value::from(text.replace("PERSON_1", "Alice")),
        Value::Array(items) => Value::Array(items.iter().map(restore).collect()),
        Value::Object(map) => {
            Value::Object(map.iter().map(|(k, v)| (k.clone(), restore(v))).collect())
        }
        other => other.clone(),
    }
}

struct Run {
    handoffs: Vec<Value>,
    bodies: Vec<String>,
    executes: Vec<Value>,
}

fn handoff_of(case: &Value, decision: &Value, text: &str, run: &mut Run) -> Result<(), Value> {
    if let Some(message) = decision["unavailable"].as_str() {
        return Err(json!({"ok":false,"message":message}));
    }
    let names: Vec<Value> = case["options"]["attachments"]
        .as_array()
        .map(|a| a.iter().map(|f| f["name"].clone()).collect())
        .unwrap_or_default();
    let reason = decision["reason"]
        .as_str()
        .map(parse)
        .unwrap_or(Value::Null);
    run.handoffs.push(json!({"target":decision["target"],"text":text,"context":case["options"]["context"],"attachments":names,"reason":reason}));
    Ok(())
}

/// The adapter's runRustAppsWorkspaceRequest, decision for decision.
fn run(case: &Value, run: &mut Run) -> Value {
    let options = &case["options"];
    let auth = &case["auth"];
    let types: Vec<Value> = options["attachments"]
        .as_array()
        .map(|a| a.iter().map(|f| f["type"].clone()).collect())
        .unwrap_or_default();
    let facts = json!({
        "text": options["text"], "appId": "web", "requestId": "req-1", "timezone": "Europe/Berlin", "locale": "en-US",
        "teamId": options["teamId"], "guest": options["guest"].as_bool().unwrap_or(false), "attachmentTypes": types,
        "expectedUserId": if auth["authenticated"] == json!(true) { auth["userId"].clone() } else { Value::Null },
        "hasChat": options["chat"].as_bool().unwrap_or(false),
    })
    .to_string();
    let pieces = &case["pieces"];
    let plan = parse(&request_plan_json(&facts, s(&pieces["contextJson"])).unwrap());
    if plan["kind"] == "error" {
        return json!({"ok":false,"message":plan["message"]});
    }
    let (text, request_id) = (
        s(&plan["text"]).to_owned(),
        s(&plan["requestId"]).to_owned(),
    );
    let next = &plan["next"];
    let chat_result = |reason: &Value| {
        let mut value = json!({"action":"chat","requestId":request_id});
        if let Some(raw) = reason.as_str() {
            value["reason"] = parse(raw);
        }
        json!({"ok":true,"value":value})
    };
    match s(&next["kind"]) {
        "error" => return json!({"ok":false,"message":next["message"]}),
        "handoff" => {
            return match handoff_of(case, next, &text, run) {
                Ok(()) => chat_result(&next["reason"]),
                Err(error) => error,
            };
        }
        _ => {}
    }
    let protected = ProtectedRequest {
        protected_text: s(&pieces["protectedText"]),
        protected_context_json: s(&pieces["protectedContextJson"]),
        attachments_json: s(&pieces["attachmentsJson"]),
        protected_attachments_json: s(&pieces["protectedAttachmentsJson"]),
        assets_json: s(&pieces["assetsJson"]),
    };
    let body = parse(&request_body_json(&facts, &request_id, &protected).unwrap());
    match s(&body["kind"]) {
        "error" => return json!({"ok":false,"message":body["message"]}),
        "handoff" => {
            return match handoff_of(case, &body, &text, run) {
                Ok(()) => chat_result(&body["reason"]),
                Err(error) => error,
            };
        }
        _ => run.bodies.push(s(&body["body"]).to_owned()),
    }
    let response = &case["interpret"];
    let status = response["status"].as_u64().unwrap();
    let decision = parse(&interpretation_json(
        (200..300).contains(&status),
        s(&response["text"]),
        !types.is_empty(),
        options["chat"].as_bool().unwrap_or(false),
        options["workflow"].as_bool().unwrap_or(false),
    ));
    match s(&decision["kind"]) {
        "syntax" => json!({"ok":false,"name":"SyntaxError"}),
        "error" => json!({"ok":false,"message":decision["message"]}),
        "handoff" => match handoff_of(case, &decision, &text, run) {
            Err(error) => error,
            Ok(()) => {
                let mut value = json!({"action":decision["action"],"requestId":request_id});
                if let Some(raw) = decision["resultReason"].as_str() {
                    value["reason"] = parse(raw);
                }
                json!({"ok":true,"value":value})
            }
        },
        _ => {
            let input = restore(&parse(s(&decision["input"])));
            if !validate_skill_input(&case["search"], &input).is_empty() {
                return json!({"ok":false,"message":"invalid_native_input"});
            }
            run.executes
                .push(json!({"skillId":decision["skillId"],"input":input}));
            let mut value = json!({"action":"execute","requestId":request_id,"skillId":decision["skillId"],"input":input,"embedId":"embed-1"});
            if let Some(raw) = decision["reason"].as_str() {
                value["reason"] = parse(raw);
            }
            json!({"ok":true,"value":value})
        }
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary,apps.requests.natural-language
#[test]
fn request_flow_equals_typescript() {
    let vectors = expand_vectors(include_str!("request_ts_vectors.json"));
    for case in vectors["cases"].as_array().unwrap() {
        let mut case = case.clone();
        case["search"] = vectors["search"]["input_schema"].clone();
        let mut state = Run {
            handoffs: Vec::new(),
            bodies: Vec::new(),
            executes: Vec::new(),
        };
        let out = run(&case, &mut state);
        let name = &case["name"];
        assert_eq!(out, case["out"], "{name}");
        assert_eq!(json!(state.handoffs), case["handoffs"], "{name}");
        assert_eq!(json!(state.executes), case["executes"], "{name}");
        let bodies: Vec<String> = case["fetches"]
            .as_array()
            .unwrap()
            .iter()
            .map(|f| s(&f["body"]).to_owned())
            .collect();
        // Byte-exact: the interpreter body is the same text TypeScript sends.
        assert_eq!(state.bodies, bodies, "{name}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn trim_and_bounds_follow_ecmascript() {
    assert_eq!(js_trim("\u{feff}\u{a0} a \u{85}"), "a \u{85}");
    assert_eq!(js_trim("\u{2028}\u{3000}b\u{2029}"), "b");
    let facts = |text: &str| {
        json!({"text":text,"appId":"web","requestId":null,"timezone":"UTC","locale":"en","teamId":null,"expectedUserId":null,"guest":false,"attachmentTypes":[],"hasChat":false}).to_string()
    };
    let minted = parse(&request_plan_json(&facts("hi"), "").unwrap());
    assert!(uuid::Uuid::parse_str(s(&minted["requestId"])).is_ok());
    assert_eq!(request_plan_json("{}", ""), Err("protocol".into()));
    assert_eq!(request_plan_json(&facts("hi"), "{"), Err("protocol".into()));
    assert_eq!(
        parse(&interpretation_json(true, "null", false, false, false))["message"],
        "invalid_interpretation"
    );
    assert_eq!(
        parse(&interpretation_json(false, "null", false, false, false))["message"],
        "interpretation_failed"
    );
}
