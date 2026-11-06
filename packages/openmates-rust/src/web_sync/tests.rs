//! Replays the TypeScript-generated vectors (`ts_vectors.json`, checked against
//! the web services by `syncPolicyVectors.test.ts`) against the web sync policy,
//! driving the same orchestration as the flag-on page adapter.
use serde_json::{json, Map, Value};

use super::{merge, message_keys, phased};

fn vectors() -> Value {
    serde_json::from_str(include_str!("ts_vectors.json")).expect("committed vectors are valid JSON")
}
fn parse(text: &str) -> Value {
    serde_json::from_str(text).expect("policy output is JSON")
}
fn local_of<'a>(v: &'a Value, name: &Value) -> &'a Value {
    &v["mergeLocals"][name.as_str().expect("local name")]
}
fn server_of<'a>(v: &'a Value, name: &Value) -> &'a Value {
    &v["mergeServers"][name.as_str().expect("server name")]
}

/// The page adapter's raw-key comparison under the generator's stub unwrappers:
/// a wrapper's raw key is its prefix before `:`; `bad…` fails master unwrapping
/// and `…throw…` fails Team/direct unwrapping (both count as a mismatch).
fn settle(plan: &Value, server: &Value, local: &Value) -> bool {
    if plan["kind"] == "decided" {
        return plan["mismatch"].as_bool().expect("decided mismatch");
    }
    // Only `direct`/`master` plans reach the raw compare: both wrappers exist.
    let (s, l) = (
        server["encrypted_chat_key"]
            .as_str()
            .expect("server wrapper"),
        local["encrypted_chat_key"].as_str().expect("local wrapper"),
    );
    let raw = |w: &str| w.split(':').next().unwrap().to_string();
    match plan["kind"].as_str().expect("plan kind") {
        "master" => s.starts_with("bad") || l.starts_with("bad") || raw(s) != raw(l),
        "direct" => s.contains("throw") || l.contains("throw") || raw(s) != raw(l),
        other => panic!("unknown plan {other}"),
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn merge_matches_typescript_for_every_local_and_server_shape() {
    let v = vectors();
    for case in v["merge"].as_array().unwrap() {
        let server = server_of(&v, &case["server"]);
        let local = local_of(&v, &case["local"]);
        let mut input = json!({
            "server": server["chat"], "serverUndefined": server["undefinedKeys"], "local": local,
            "keyMismatch": null, "now": v["now"],
        });
        if case["hasUser"].as_bool().unwrap() {
            input["currentUserId"] = case["currentUserId"].clone();
        }
        let mut result = parse(&merge::merge_json(&input.to_string()).unwrap());
        if result["kind"] == "compareKeys" {
            let settled = settle(&result["plan"], &server["chat"], local);
            assert_eq!(
                json!(settled),
                case["keyMismatch"],
                "settled mismatch {case}"
            );
            input["keyMismatch"] = json!(settled);
            result = parse(&merge::merge_json(&input.to_string()).unwrap());
        }
        assert_eq!(result["kind"], "merged");
        assert_eq!(
            result["chat"], case["out"],
            "{}/{}",
            case["local"], case["server"]
        );
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn key_mismatch_plan_matches_typescript() {
    let v = vectors();
    for case in v["keyMismatch"].as_array().unwrap() {
        let server = &server_of(&v, &case["server"])["chat"];
        let local = local_of(&v, &case["local"]);
        let plan = parse(
            &merge::key_mismatch_json(&json!({"server": server, "local": local}).to_string())
                .unwrap(),
        );
        let mismatch = if local.is_null() {
            plan["mismatch"].as_bool().unwrap()
        } else {
            settle(&plan, server, local)
        };
        assert_eq!(json!(mismatch), case["out"], "{case}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn malformed_merge_input_is_refused_with_protocol() {
    for input in [
        "",
        "[]",
        r#"{"server":{},"now":1}"#,
        r#"{"server":1,"serverUndefined":[],"now":1}"#,
        r#"{"server":{},"serverUndefined":[],"local":3,"now":1}"#,
        r#"{"server":{},"serverUndefined":[1],"now":1}"#,
        r#"{"server":{"id":"c"},"serverUndefined":[],"local":{"chat_id":"c"},"keyMismatch":"yes","now":1}"#,
    ] {
        assert_eq!(
            merge::merge_json(input),
            Err("protocol".to_string()),
            "{input}"
        );
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn retry_delay_matches_typescript() {
    let v = vectors();
    for case in v["retryDelay"].as_array().unwrap() {
        let hint = case["hasRetryAfter"]
            .as_bool()
            .unwrap()
            .then_some(&case["retryAfterMs"]);
        let got = phased::retry_delay_ms(case["attempt"].as_f64().unwrap(), hint);
        assert_eq!(got, case["out"].as_f64().unwrap(), "{case}");
    }
}

/// The flag-on adapter's retry state machine over `retry_json` (rustChatSyncPolicy.ts).
#[derive(Default)]
struct RetryState {
    attempt: u64,
    timer: bool,
}

impl RetryState {
    fn on_error(&mut self, payload: &Value) -> Vec<Value> {
        let mut input = json!({"retryable": payload.get("retryable"), "timerPending": self.timer, "attempt": self.attempt});
        if payload.get("retryable").is_none() {
            input.as_object_mut().unwrap().remove("retryable");
        }
        if let Some(hint) = payload.get("retry_after_ms") {
            input["retryAfterMs"] = hint.clone();
        }
        let step = parse(&phased::retry_json(&input.to_string()).unwrap());
        match step["kind"].as_str().unwrap() {
            "ignore" => vec![],
            "pending" => vec![json!(["clear"])],
            "exhausted" => {
                *self = Self::default();
                vec![
                    json!(["clear"]),
                    json!(["markSyncCompleted"]),
                    json!("complete"),
                    json!("notify"),
                ]
            }
            "schedule" => {
                self.attempt = step["attempt"].as_u64().unwrap();
                self.timer = true;
                vec![json!(["clear"]), json!(["schedule", step["delayMs"]])]
            }
            other => panic!("unknown step {other}"),
        }
    }
}

/// Effects with the TS-owned completion detail and notice reduced to their kind.
fn kinds(effects: &Value) -> Vec<Value> {
    effects
        .as_array()
        .unwrap()
        .iter()
        .map(|e| match e[0].as_str().unwrap() {
            kind @ ("complete" | "notify") => json!(kind),
            _ => e.clone(),
        })
        .collect()
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn retry_state_machine_matches_typescript_sequences() {
    let v = vectors();
    for sequence in v["retry"].as_array().unwrap() {
        let mut state = RetryState::default();
        for step in sequence.as_array().unwrap() {
            let event = &step["event"];
            let got = if event.get("reset").is_some() {
                state = RetryState::default();
                vec![]
            } else if event.get("fire").is_some() {
                let fired = std::mem::take(&mut state.timer);
                let connected = event
                    .get("connected")
                    .and_then(Value::as_bool)
                    .unwrap_or(true);
                if fired && connected {
                    vec![json!(["start"])]
                } else {
                    vec![]
                }
            } else {
                state.on_error(&event["p"])
            };
            assert_eq!(got, kinds(&step["effects"]), "{step}");
        }
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn message_key_plan_matches_typescript() {
    let v = vectors();
    for case in v["messageKeys"].as_array().unwrap() {
        let plan = parse(
            &message_keys::plan_json(&json!({"messages": case["messages"]}).to_string()).unwrap(),
        );
        assert_eq!(plan, case["out"], "{case}");
    }
    assert_eq!(
        message_keys::plan_json(r#"{"messages":[1]}"#),
        Err("protocol".to_string())
    );
    assert_eq!(
        message_keys::plan_json(r#"{}"#),
        Err("protocol".to_string())
    );
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn key_admission_and_metadata_chats_match_typescript() {
    let v = vectors();
    let now = &v["now"];
    for case in v["admission"].as_array().unwrap() {
        let input =
            json!({"chatId": case["chatId"], "server": case["server"], "local": case["local"]});
        let got = parse(&phased::admission_json(&input.to_string()).unwrap());
        assert_eq!(got["skip"], case["skip"], "{case}");
        let chat = parse(
            &phased::metadata_chat_json(
                &json!({"chatId": case["chatId"], "server": case["server"],
            "local": case["local"], "now": now})
                .to_string(),
            )
            .unwrap(),
        );
        assert_eq!(
            chat["kind"] == "skip",
            case["skip"].as_bool().unwrap(),
            "{case}"
        );
    }
    for case in v["metadataChat"].as_array().unwrap() {
        let input = json!({"chatId": case["server"]["id"], "server": case["server"], "local": case["local"], "now": now});
        let got = parse(&phased::metadata_chat_json(&input.to_string()).unwrap());
        assert_eq!(got["chat"], case["out"], "{case}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn deletion_plan_matches_typescript() {
    let v = vectors();
    for case in v["deletion"].as_array().unwrap() {
        let mut input = Map::new();
        if case["hasDeleted"].as_bool().unwrap() {
            input.insert("deleted".into(), case["deleted"].clone());
        }
        if case["hasExplicit"].as_bool().unwrap() {
            input.insert("explicit".into(), case["explicit"].clone());
        }
        let plan = parse(&phased::deletion_plan_json(&Value::Object(input).to_string()).unwrap());
        assert_eq!(plan, case["out"], "{case}");
    }
    assert_eq!(
        phased::deletion_plan_json(r#"{"deleted":"a"}"#),
        Err("protocol".to_string())
    );
}
