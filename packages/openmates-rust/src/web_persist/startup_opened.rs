//! Startup recency request and browser retained-history paging decisions.
use crate::client::{message_window::MessageWindowCursor, opened_tail_needs_read, opened_wire_version, parse_startup_opened_chat_ids};
use serde::Deserialize;
use serde_json::{json, Value};

const PAGE_LIMIT: usize = 20;
const RUN_PAGE_LIMIT: usize = 256;


#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Progress {
    chat_id: String,
    previous: Option<MessageWindowCursor>,
    start: Option<MessageWindowCursor>,
    has_more_before: bool,
    has_more_after: bool,
    rows_confirmed: bool,
    pages_read: usize,
    retained_rows: usize,
    server_message_count: Option<usize>,
    messages_version: Option<u64>,
    expected_version: Option<u64>,
    confirmed_coverage: Option<ConfirmedCoverage>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ConfirmedCoverage {
    cursor: Option<MessageWindowCursor>,
    messages_version: u64,
    retained_rows: usize,
}

fn selector(before: Option<&MessageWindowCursor>) -> Value {
    match before {
        Some(cursor) => json!({"direction":"before","cursor":cursor,"limit":PAGE_LIMIT,
                              "respectCompressionBoundary":false}),
        None => json!({"direction":"latest","limit":PAGE_LIMIT,"respectCompressionBoundary":false}),
    }
}

fn record(input: &Value) -> Result<Value, &'static str> {
    let chat = input.get("chatId").ok_or("protocol")?;
    let ids = parse_startup_opened_chat_ids(&json!([chat])).map_err(|_| "protocol")?;
    let mut path = format!("/v1/chats/{}/opened", ids[0]);
    match &input["teamId"] {
        Value::Null => {}
        Value::String(team) if !team.is_empty() && team.len() <= 128 => {
            let mut query = url::form_urlencoded::Serializer::new(String::new());
            query.append_pair("team_id", team);
            let query = query.finish();
            path.push('?');
            path.push_str(&query);
        }
        _ => return Err("protocol"),
    }
    Ok(json!({"path":path}))
}

// The offer is a hint about the current server snapshot. It can skip a read
// only for an already confirmed complete transcript of that exact version.
// Partial transcripts always authenticate a new tail before reusing cursors.
fn begin(input: &Value) -> Result<Value, &'static str> {
    let ids = parse_startup_opened_chat_ids(&input["ids"]).map_err(|_| "protocol")?;
    let refresh_head = input["refreshHead"].as_bool().unwrap_or(false);
    let latest: Vec<_> = ids
        .iter()
        .enumerate()
        .filter_map(|(index, id)| {
            let retained = &input["complete"][id.as_str()];
            let needs_latest = !retained.is_object() || opened_tail_needs_read(
                index == 0 && refresh_head,
                retained["verifiedOnConnection"].as_bool() == Some(true),
                opened_wire_version(&retained["messagesVersion"]),
                opened_wire_version(&input["messagesVersions"][id.as_str()]),
            );
            needs_latest.then_some(id)
        })
        .collect();
    Ok(
        json!({"chatIds":ids,"latestChatIds":latest,"selector":selector(None),"pageBudget":RUN_PAGE_LIMIT}),
    )
}

fn advance(progress: Progress) -> Result<Value, &'static str> {
    if !progress.rows_confirmed
        || progress.pages_read == 0
        || progress.pages_read > RUN_PAGE_LIMIT
        || (progress.previous.is_none() && progress.has_more_after)
        || (progress.previous.is_some()
            && (progress.messages_version.is_none()
                || progress.expected_version != progress.messages_version))
    {
        return Err("protocol");
    }
    if let Some(start) = &progress.start {
        if start.chat_id != progress.chat_id
            || progress.previous.as_ref().is_some_and(|before| {
                start.scope != before.scope
                    || (start.created_at, start.message_id.as_str())
                        >= (before.created_at, before.message_id.as_str())
            })
        {
            return Err("protocol");
        }
    }
    if let Some(decision) = reuse_matching_coverage(&progress) {
        return Ok(decision);
    }
    if !progress.has_more_before {
        if progress
            .server_message_count
            .is_some_and(|count| count != progress.retained_rows)
        {
            return Err("protocol");
        }
        return Ok(json!({"done":true,"selector":null}));
    }
    // The lease budget stops the caller from issuing another read. Preserve
    // the verified boundary on the last permitted page for the next lease.
    if progress.messages_version.is_none() {
        return Err("protocol");
    }
    let before = progress.start.as_ref().ok_or("protocol")?;
    Ok(json!({"done":false,"selector":selector(Some(before))}))
}

// An interrupted browser lease loses its cursor scope. A freshly authenticated
// latest page can rebind an already confirmed boundary when the history version
// and count still agree. The old scope never authorizes a request.
fn reuse_matching_coverage(progress: &Progress) -> Option<Value> {
    let confirmed = progress.confirmed_coverage.as_ref()?;
    let start = progress.start.as_ref()?;
    if progress.previous.is_some()
        || !progress.has_more_before
        || progress.messages_version != Some(confirmed.messages_version)
        || confirmed.retained_rows < progress.retained_rows
        || progress.server_message_count.is_some_and(|count| {
            if confirmed.cursor.is_some() {
                count <= confirmed.retained_rows
            } else {
                count != confirmed.retained_rows
            }
        })
    {
        return None;
    }
    let Some(cursor) = &confirmed.cursor else {
        return Some(json!({"done":true,"selector":null,"reusedRows":confirmed.retained_rows}));
    };
    if cursor.chat_id != progress.chat_id
        || cursor.scope.is_empty()
        || (cursor.created_at, cursor.message_id.as_str())
            > (start.created_at, start.message_id.as_str())
    {
        return None;
    }
    let rebound = MessageWindowCursor {
        chat_id: cursor.chat_id.clone(),
        scope: start.scope.clone(),
        created_at: cursor.created_at,
        message_id: cursor.message_id.clone(),
    };
    Some(
        json!({"done":false,"selector":selector(Some(&rebound)),"reusedRows":confirmed.retained_rows}),
    )
}

/// Return a closed, content-free request or cursor decision for the browser.
///
/// # Errors
/// Returns the fixed protocol code for malformed input or unproven coverage.
pub fn decide_json(encoded: &str) -> Result<String, String> {
    let decide = || {
        let input: Value = serde_json::from_str(encoded).map_err(|_| "protocol")?;
        match input["kind"].as_str() {
            Some("record") => record(&input),
            Some("begin") => begin(&input),
            Some("coverageReceipt") => super::startup_coverage::coverage_decision(&input),
            Some("coverageDigest") => super::startup_coverage::coverage_digest(&input),
            Some("advance") => {
                advance(serde_json::from_value(input["progress"].clone()).map_err(|_| "protocol")?)
            }
            _ => Err("protocol"),
        }
    };
    decide()
        .map(|value| value.to_string())
        .map_err(|code| code.to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    // contract-test: infrastructure
    #[test]
    fn refuses_repeated_cursor_or_changed_history_version() {
        let cursor = MessageWindowCursor {
            chat_id: "fixture".into(),
            scope: "scope".into(),
            created_at: 1,
            message_id: "message".into(),
        };
        let mut progress = json!({"chatId":"fixture","previous":cursor,"start":cursor,
            "hasMoreBefore":true,"hasMoreAfter":true,"rowsConfirmed":true,"pagesRead":2,
            "messagesVersion":3,"expectedVersion":3,"retainedRows":3,"serverMessageCount":3});
        assert!(decide_json(&json!({"kind":"advance","progress":progress}).to_string()).is_err());
        progress["start"]["createdAt"] = json!(0);
        assert!(decide_json(&json!({"kind":"advance","progress":progress}).to_string()).is_ok());
        progress["messagesVersion"] = json!(4);
        assert!(decide_json(&json!({"kind":"advance","progress":progress}).to_string()).is_err());
    }

    // contract-test: infrastructure
    #[test]
    fn only_matching_confirmed_versions_skip_replacement_latest_checks() {
        let head = "00000000-0000-0000-0000-000000000001";
        let matched = "00000000-0000-0000-0000-000000000002";
        let changed = "00000000-0000-0000-0000-000000000003";
        let partial = "00000000-0000-0000-0000-000000000004";
        let mut input = json!({
            "kind": "begin",
            "ids": [head, matched, changed, partial],
            "messagesVersions": {(matched): 0, (changed): 8, (partial): 7},
            "complete": {
                (head): {"messagesVersion": 7},
                (matched): {"messagesVersion": 0},
                (changed): {"messagesVersion": 7}
            }
        });
        let latest = |input: &Value| -> Value {
            serde_json::from_str::<Value>(&decide_json(&input.to_string()).unwrap()).unwrap()
                ["latestChatIds"]
                .clone()
        };
        assert_eq!(latest(&input), json!([head, changed, partial]));
        input["messagesVersions"][head] = json!(7);
        input["messagesVersions"][changed] = json!(1u64 << 53);
        assert_eq!(latest(&input), json!([changed, partial]));

        input["messagesVersions"] = Value::Null;
        input["complete"][head]["verifiedOnConnection"] = json!(true);
        assert_eq!(latest(&input), json!([matched, changed, partial]));
        input["refreshHead"] = json!(true);
        assert_eq!(latest(&input), json!([head, matched, changed, partial]));
    }

    // contract-test: infrastructure
    #[test]
    fn paging_budget_preserves_and_rebinds_coverage_larger_than_one_lease() {
        let previous = MessageWindowCursor {
            chat_id: "fixture".into(),
            scope: "original".into(),
            created_at: 2,
            message_id: "previous".into(),
        };
        let start = MessageWindowCursor {
            created_at: 1,
            message_id: "start".into(),
            ..previous.clone()
        };
        let retained_rows = RUN_PAGE_LIMIT * PAGE_LIMIT;
        let mut progress = json!({
            "chatId":"fixture","previous":previous,"start":start,"hasMoreBefore":true,
            "hasMoreAfter":true,"rowsConfirmed":true,"pagesRead":RUN_PAGE_LIMIT,
            "messagesVersion":3,"expectedVersion":3,"retainedRows":retained_rows,
            "serverMessageCount":retained_rows + 200
        });
        let decide = |progress: &Value| -> Result<Value, String> {
            let encoded = json!({"kind":"advance","progress":progress}).to_string();
            decide_json(&encoded).map(|output| serde_json::from_str(&output).unwrap())
        };
        let final_page = decide(&progress).unwrap();
        assert_eq!(final_page["done"], false);
        assert_eq!(final_page["selector"]["cursor"]["messageId"], "start");

        progress["pagesRead"] = json!(RUN_PAGE_LIMIT + 1);
        assert!(decide(&progress).is_err());

        // A later connection checked the tail again and can authenticate
        // a boundary whose total confirmed rows span several leases.
        progress["pagesRead"] = json!(1);
        progress["previous"] = Value::Null;
        progress["expectedVersion"] = Value::Null;
        progress["hasMoreAfter"] = json!(false);
        progress["start"] = json!({
            "chatId":"fixture","scope":"replacement","createdAt":100,"messageId":"latest"
        });
        progress["retainedRows"] = json!(PAGE_LIMIT);
        progress["confirmedCoverage"] = json!({
            "cursor":start,"messagesVersion":3,"retainedRows":retained_rows + PAGE_LIMIT
        });
        let resumed = decide(&progress).unwrap();
        assert_eq!(resumed["selector"]["cursor"]["scope"], "replacement");
        assert_eq!(resumed["selector"]["cursor"]["messageId"], "start");
        assert_eq!(resumed["reusedRows"], retained_rows + PAGE_LIMIT);
    }

    // contract-test: infrastructure
    #[test]
    fn rebinds_only_matching_confirmed_history_to_a_new_cursor_scope() {
        let latest = MessageWindowCursor {
            chat_id: "fixture".into(),
            scope: "new_scope".into(),
            created_at: 12,
            message_id: "latest".into(),
        };
        let prior = MessageWindowCursor {
            chat_id: latest.chat_id.clone(),
            scope: "old_scope".into(),
            created_at: 7,
            message_id: "prior".into(),
        };
        let mut progress = json!({
            "chatId":"fixture","previous":null,"start":latest,"hasMoreBefore":true,
            "hasMoreAfter":false,"rowsConfirmed":true,"pagesRead":3,"messagesVersion":3,
            "expectedVersion":null,"retainedRows":20,"serverMessageCount":90,
            "confirmedCoverage":{"cursor":prior,"messagesVersion":3,"retainedRows":40}
        });
        let decision = |progress: &Value| -> Value {
            let input = json!({"kind":"advance","progress":progress});
            serde_json::from_str(&decide_json(&input.to_string()).unwrap()).unwrap()
        };
        let matched = decision(&progress);
        assert_eq!(matched["reusedRows"], 40);
        assert_eq!(matched["selector"]["cursor"]["scope"], "new_scope");
        assert_eq!(matched["selector"]["cursor"]["messageId"], "prior");

        progress["messagesVersion"] = json!(4);
        let changed = decision(&progress);
        assert!(changed.get("reusedRows").is_none());
        assert_eq!(changed["selector"]["cursor"]["messageId"], "latest");

        progress["messagesVersion"] = json!(3);
        progress["confirmedCoverage"]["cursor"] = Value::Null;
        assert!(decision(&progress).get("reusedRows").is_none());
        progress["confirmedCoverage"]["retainedRows"] = json!(90);
        let proven_complete = decision(&progress);
        assert_eq!(proven_complete["done"], true);
        assert_eq!(proven_complete["reusedRows"], 90);
    }
}
