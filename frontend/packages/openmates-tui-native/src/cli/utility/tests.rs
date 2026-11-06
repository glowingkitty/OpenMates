use super::super::{CliError, Invocation};
use super::*;
use serde_json::{Value, json};
use std::cmp::Ordering;

fn invocation(path: &str, positionals: &[&str], flags: &[(&str, Value)]) -> Invocation {
    Invocation {
        path: path.split(' ').map(str::to_owned).collect(),
        positionals: positionals.iter().map(|p| (*p).to_owned()).collect(),
        flags: flags
            .iter()
            .map(|(k, v)| ((*k).to_owned(), v.clone()))
            .collect(),
    }
}
fn invalid(error: CliError) -> String {
    match error {
        CliError::Invalid(message) => message,
        _ => panic!("expected an invalid-argument error"),
    }
}

#[test]
fn routing_marks_local_network_and_session_commands() {
    let compare = invocation("benchmark prompt-budget compare", &[], &[]);
    assert!(is_public(&compare) && public(&compare).is_some());
    let update = invocation("update", &[], &[]);
    assert!(is_network_public(&update) && public(&update).is_none());
    let finance = invocation("finance check_accounts", &[], &[]);
    assert!(supported(&finance) && !is_public(&finance));
    assert!(!supported(&invocation("benchmark model", &[], &[])));
}

#[test]
fn memories_root_prints_the_legacy_help() {
    let out = public(&invocation("settings memories", &[], &[]))
        .unwrap()
        .ok()
        .unwrap();
    assert!(
        out.stdout
            .starts_with("Memories commands:\n  openmates settings memories list")
    );
    let error = public(&invocation("settings memories", &["bogus"], &[]))
        .unwrap()
        .err()
        .unwrap();
    assert!(invalid(error).contains("Unknown memories action 'bogus'"));
}

fn artifact(duration: f64, judge: f64, turn_score: f64, continuity: f64) -> Value {
    json!({
        "command": "benchmark prompt-budget", "corpusHash": "abc",
        "summary": {"averageTurnDurationMs": duration, "averageJudgeScore": judge, "averageContinuityScore": null},
        "cases": [{"id": "case-a", "promptHashes": ["h1", "h2"],
            "turns": [{"turn": 1, "judge": {"score": turn_score}}],
            "continuityJudge": {"score": continuity}}],
    })
}

#[test]
fn prompt_budget_compare_matches_legacy_deltas_and_regressions() {
    let base = artifact(1000.0, 4.5, 5.0, 5.0);
    let improved = artifact(900.0, 4.5, 5.0, 5.0);
    let result = prompt_budget::comparison("b.json", "p.json", &base, &improved)
        .ok()
        .unwrap();
    assert_eq!(result["status"], "passed");
    assert_eq!(result["recommendation"], "keep");
    assert_eq!(
        result["deltas"]["averageTurnDurationMs"],
        json!({"baseline":1000,"postchange":900,"delta":-100,"percent":-10})
    );
    assert_eq!(
        result["deltas"]["averageContinuityScore"]["delta"],
        Value::Null
    );
    let text = prompt_budget::comparison_text(&result);
    assert_eq!(
        text,
        "Prompt-budget comparison passed: keep\nCorpus: abc\nDuration delta: 1000ms -> 900ms (-100ms) (-10%)\nQuality delta: 4.5 -> 4.5 (0) (0%)\n"
    );

    let worse = artifact(1100.0, 3.0, 3.0, 2.5);
    let result = prompt_budget::comparison("b.json", "p.json", &base, &worse)
        .ok()
        .unwrap();
    assert_eq!(result["status"], "needs_fix");
    assert_eq!(result["recommendation"], "adjust_or_revert");
    assert_eq!(
        result["regressions"],
        json!([
            "case-a turn 1: score dropped below pass threshold (5 -> 3)",
            "case-a: continuity score dropped below pass threshold (5 -> 2.5)"
        ])
    );

    let mut other = artifact(900.0, 4.5, 5.0, 5.0);
    other["corpusHash"] = json!("different");
    let error = prompt_budget::comparison("b", "p", &base, &other)
        .err()
        .unwrap();
    assert_eq!(
        invalid(error),
        "prompt-budget artifacts use different corpus hashes and cannot be compared"
    );
    let missing =
        json!({"command":"benchmark prompt-budget","corpusHash":"abc","summary":{},"cases":[]});
    assert_eq!(
        prompt_budget::regressions(&base, &missing),
        vec!["case-a: missing post-change case".to_owned()]
    );
}

#[test]
fn prompt_budget_compare_requires_both_paths() {
    let out = public(&invocation(
        "benchmark prompt-budget compare",
        &[],
        &[("baseline", json!("x"))],
    ));
    assert_eq!(
        invalid(out.unwrap().err().unwrap()),
        "prompt-budget compare requires --baseline <path> and --postchange <path>"
    );
}

#[test]
fn examples_index_lists_linked_chats_like_the_npm_cli() {
    let chats = examples::embedded();
    assert!(!chats.is_empty());
    let finance = examples::matching(chats, "finance", Some("check_accounts"));
    assert!(!finance.is_empty());
    assert!(finance.iter().all(|c| {
        c.app_skill_examples
            .iter()
            .any(|k| k == "finance.check_accounts")
    }));
    let none = examples::matching(chats, "no-such-app", None);
    assert_eq!(
        examples::text("no-such-app", None, &none),
        "\x1b[1mExample chats for no-such-app\x1b[0m\n\nNo example chats are linked to no-such-app yet.\n\nInspect available skills:\n  openmates apps no-such-app\n"
    );
    let out = examples::execute(&invocation(
        "apps examples",
        &["finance"],
        &[("json", json!(true))],
    ))
    .ok()
    .unwrap();
    let value: Value = serde_json::from_str(&out.stdout).unwrap();
    assert_eq!(value["app_id"], "finance");
    assert_eq!(value["skill_id"], Value::Null);
    let first = &value["examples"][0];
    assert_eq!(first["source"], "example");
    assert_eq!(
        first["commands"]["show"],
        format!(
            "openmates chats show {}",
            first["chat_id"].as_str().unwrap()
        )
    );
    assert!(
        invalid(
            examples::execute(&invocation("apps examples", &[], &[]))
                .err()
                .unwrap()
        )
        .starts_with("Missing app ID.")
    );
}

#[test]
fn self_update_versions_and_plan_follow_npm_rules() {
    use self_update::*;
    assert_eq!(
        compare_versions("1.2.3", "1.2.3").ok(),
        Some(Ordering::Equal)
    );
    assert_eq!(
        compare_versions("1.2.3-alpha.2", "1.2.3").ok(),
        Some(Ordering::Less)
    );
    assert_eq!(
        compare_versions("1.2.3-alpha.10", "1.2.3-alpha.9").ok(),
        Some(Ordering::Greater)
    );
    assert_eq!(
        compare_versions("1.2.3-alpha", "1.2.3-alpha.1").ok(),
        Some(Ordering::Less)
    );
    assert_eq!(
        compare_versions("1.2.3-1", "1.2.3-alpha").ok(),
        Some(Ordering::Less)
    );
    assert_eq!(
        compare_versions("2.0.0", "10.0.0").ok(),
        Some(Ordering::Less)
    );
    assert!(compare_versions("next", "1.0.0").is_err());
    assert_eq!(
        invalid(parse_target("1.0.0;rm").err().unwrap()),
        "--version contains unsupported characters"
    );
    assert_eq!(parse_channel("main").ok(), Some(Channel::Stable));
    let registry = json!({"crate":{"max_version":"0.2.0-alpha.1","max_stable_version":"0.1.5"}});
    assert_eq!(
        resolve_from_registry("latest", &registry).ok().as_deref(),
        Some("0.1.5")
    );
    assert_eq!(
        resolve_from_registry("alpha", &registry).ok().as_deref(),
        Some("0.2.0-alpha.1")
    );
    assert!(resolve_from_registry("beta", &registry).is_err());

    let refused = plan(
        &invocation("update", &[], &[("package-manager", json!("npm"))]),
        "0.1.0",
    );
    assert!(invalid(refused.err().unwrap()).contains("must be cargo"));
    let planned = plan(
        &invocation(
            "update",
            &[],
            &[
                ("channel", json!("dev")),
                ("version", json!("0.2.0")),
                ("dry-run", json!(true)),
            ],
        ),
        "0.1.0",
    )
    .ok()
    .unwrap();
    assert_eq!(planned.channel, Channel::Dev);
    assert!(planned.persist_channel && planned.dry_run);
    assert_eq!(
        planned.run(),
        [
            "cargo",
            "install",
            "openmates",
            "--version",
            "0.2.0",
            "--locked"
        ]
    );
}

#[test]
fn finance_input_selection_and_text_follow_npm_shape() {
    use finance::*;
    assert_eq!(
        csv_list(Some(" a, ,b ")),
        Some(vec!["a".to_owned(), "b".to_owned()])
    );
    assert_eq!(csv_list(Some(" , ")), None);
    let account = json!({"id":"acc-1","account_ref":"ref-9","refresh_token_bundle":{"environment":"sandbox"}});
    let i = invocation(
        "finance check-accounts",
        &[],
        &[
            ("from", json!("2026-01-01")),
            ("categories", json!("rent,food")),
            ("direction", json!("expense")),
        ],
    );
    let value = input(
        &i,
        &[json!({"filename":"a.csv","content":"x"})],
        Some(&account),
    );
    assert_eq!(value["period"], "monthly");
    assert_eq!(value["projection_horizon"], "monthly");
    assert_eq!(value["start_date"], "2026-01-01");
    assert_eq!(value["category_filters"], json!(["rent", "food"]));
    assert_eq!(value["direction_filter"], "expense");
    assert_eq!(
        value["connected_account_requests"],
        json!([{"source_ref":"revolut_business:ref-9","environment":"sandbox"}])
    );
    assert_eq!(value["security"]["prompt_injection_protection"], "disabled");
    assert!(value.get("end_date").is_none());

    assert!(
        invalid(select(vec![], None).err().unwrap())
            .starts_with("No revolut_business connected account found.")
    );
    assert!(
        invalid(select(vec![], Some("x")).err().unwrap())
            .contains("Connected account x was not found")
    );
    assert!(
        invalid(select(vec![json!({}), json!({})], None).err().unwrap())
            .starts_with("Multiple revolut_business accounts")
    );

    let text = result_text(&json!({
        "account_count": 1, "transaction_count": 2,
        "overview": {"summaries": {"income_total": 10.5, "expense_total": 3, "net_total": 7.5,
            "time_series": [{"bucket": "2026-01", "income": 10.5, "expense": 3, "net": 7.5}]},
            "transactions": [{"posted_at": "2026-01-02", "direction": "expense", "amount": 3, "currency": "EUR", "category": "food", "counterparty_placeholder": "[MERCHANT_1]"}]},
        "warnings": [{"code": "partial"}],
    }));
    assert!(text.starts_with(
        "\x1b[1mFinance › Check accounts\x1b[0m\n  \x1b[2mAccounts        \x1b[0m 1\n"
    ));
    assert!(text.contains("\nTime series\n  2026-01  income 10.5  expenses 3  net 7.5\n"));
    assert!(text.contains("\nTransactions\n  2026-01-02  expense  3 EUR  food  [MERCHANT_1]\n"));
    assert!(text.ends_with("\nWarning: partial\n"));
}

#[test]
fn js_number_formatting_matches_javascript() {
    assert_eq!(js_number(3.0), "3");
    assert_eq!(js_number(-0.5), "-0.5");
    assert_eq!(json_number(2.0), json!(2));
    assert_eq!(json_number(2.25), json!(2.25));
}

#[test]
fn revolut_setup_helpers_follow_npm_rules() {
    use revolut::*;
    assert!(supported(&invocation(
        "connect-account revolut-business",
        &[],
        &[]
    )));
    assert_eq!(subject("A/B\\C\nD"), "/CN=A\\/B\\\\C D");
    assert_eq!(
        configured_ips(" 2.2.2.2;1.1.1.1, 2.2.2.2 ,"),
        vec!["1.1.1.1", "2.2.2.2"]
    );
    assert_eq!(
        default_redirect(false),
        "https://app.dev.openmates.org/oauth/revolut-business/callback"
    );
    let text = certificate_text("T", "https://x", &[], "PEM", std::path::Path::new("/k.pem"));
    assert!(text.contains("Production IP whitelist: unavailable"));
    assert!(text.contains("Private key saved locally: /k.pem\n"));
}

fn key_sdk(api: &str) -> openmates_sdk::sdk::OpenMates {
    openmates_sdk::sdk::OpenMates::new(openmates_sdk::SdkOptions {
        api_url: api.into(),
        credentials: openmates_sdk::SdkCredentials::ApiKey(
            openmates_sdk::ApiKey::new("sk-api-synthetic.synthetic").unwrap(),
        ),
        device_id: "synthetic".into(),
        client_options: Default::default(),
    })
    .unwrap()
}

#[tokio::test]
async fn api_key_finance_requires_explicit_csv_only_before_any_request() {
    let sdk = key_sdk("http://127.0.0.1:9");
    for flags in [
        vec![("csv", json!("a.csv"))],
        vec![("csv-only", json!(true)), ("csv", json!("a.csv")), ("connected-account", json!("acc"))],
    ] {
        let i = invocation("finance check-accounts", &[], &flags);
        match execute_finance_key(&i, &sdk).await {
            Err(CliError::Unsupported { reason, .. }) => assert_eq!(reason, finance::KEY_CSV_ONLY),
            _ => panic!("expected the explicit csv-only refusal"),
        }
    }
    let empty = invocation("finance check_accounts", &[], &[("csv-only", json!(true))]);
    assert_eq!(
        invalid(execute_finance_key(&empty, &sdk).await.err().unwrap()),
        "Check accounts requires a Revolut Business connected account or --csv <file.csv>."
    );
}

#[tokio::test]
async fn api_key_finance_posts_csv_statements_to_the_key_skill_route_without_token_refs() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let directory = tempfile::tempdir().unwrap();
    let csv = directory.path().join("statement.csv");
    std::fs::write(&csv, "date,amount\n2026-01-01,1\n").unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut buf = Vec::new();
        loop {
            let mut bytes = [0; 4096];
            let n = socket.read(&mut bytes).await.unwrap();
            assert!(n > 0);
            buf.extend_from_slice(&bytes[..n]);
            if let Some(end) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                let head = String::from_utf8_lossy(&buf[..end]).to_ascii_lowercase();
                let size = head
                    .lines()
                    .find_map(|l| l.strip_prefix("content-length:").and_then(|n| n.trim().parse::<usize>().ok()))
                    .unwrap_or(0);
                if buf.len() >= end + 4 + size {
                    break;
                }
            }
        }
        let body = r#"{"success":true}"#;
        socket
            .write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes())
            .await
            .unwrap();
        String::from_utf8(buf).unwrap()
    });
    let sdk = key_sdk(&api);
    let i = invocation(
        "finance check-accounts",
        &[],
        &[("csv-only", json!(true)), ("csv", json!(csv.to_str().unwrap())), ("json", json!(true))],
    );
    let out = execute_finance_key(&i, &sdk).await.ok().unwrap();
    assert_eq!(serde_json::from_str::<Value>(&out.stdout).unwrap(), json!({"success": true}));
    let request = server.await.unwrap();
    assert!(request.starts_with("POST /v1/sdk/connected-account-skills/finance/check_accounts "));
    assert!(request.to_ascii_lowercase().contains("authorization: bearer sk-api-synthetic"));
    let body: Value = serde_json::from_str(request.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(body["connected_account_token_ref_inputs"], json!([]));
    assert_eq!(body["input"]["csv_statements"][0]["filename"], "statement.csv");
    assert!(body["chat_id"].as_str().unwrap().starts_with("cli-finance-"));
}
