//! Rust API-key SDK operation facades (billing, settings, reminders, notifications,
//! finance, connected accounts) against a loopback fixture server. No purchase,
//! refund or deletion ever reaches a real backend: the server is local and every
//! response is a recorded synthetic shape. Credential separation is covered by
//! `sdk_api_key_cli_login_isolation.rs`.
// contract-test-file: tooling
use aes_gcm::{Aes256Gcm, KeyInit, aead::Aead};
use base64::{
    Engine,
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
};
use openmates_sdk::sdk_finance::CheckAccountsOptions;
use openmates_sdk::sdk_settings::ModelDefaults;
use openmates_sdk::{ApiKey, ClientOptions, Error, OpenMates, SdkCredentials, SdkOptions};
use serde_json::{Value, json};
use std::io::{Read, Write};
use std::net::TcpListener;

struct Reply {
    status: u16,
    headers: Vec<(&'static str, &'static str)>,
    body: Vec<u8>,
}
fn json_reply(value: Value) -> Reply {
    Reply {
        status: 200,
        headers: vec![("Content-Type", "application/json")],
        body: value.to_string().into_bytes(),
    }
}
struct Seen {
    head: String,
    body: Value,
}
impl Seen {
    fn line(&self) -> &str {
        self.head.lines().next().unwrap()
    }
    fn header(&self, name: &str) -> Option<String> {
        self.head.lines().skip(1).find_map(|l| {
            let (k, v) = l.split_once(':')?;
            k.eq_ignore_ascii_case(name).then(|| v.trim().to_owned())
        })
    }
}
fn serve(replies: Vec<Reply>) -> (String, std::thread::JoinHandle<Vec<Seen>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let handle = std::thread::spawn(move || {
        let mut seen = vec![];
        for reply in replies {
            let (mut stream, _) = listener.accept().unwrap();
            let mut bytes = vec![];
            let mut buffer = [0u8; 4096];
            let (end, len) = loop {
                let n = stream.read(&mut buffer).unwrap();
                assert!(n > 0);
                bytes.extend_from_slice(&buffer[..n]);
                if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    let head = String::from_utf8_lossy(&bytes[..end]).to_string();
                    let len = head
                        .lines()
                        .find_map(|l| {
                            l.split_once(':')
                                .filter(|(k, _)| k.eq_ignore_ascii_case("content-length"))
                                .and_then(|(_, v)| v.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    break (end + 4, len);
                }
            };
            while bytes.len() < end + len {
                let n = stream.read(&mut buffer).unwrap();
                assert!(n > 0);
                bytes.extend_from_slice(&buffer[..n]);
            }
            let body = if len == 0 {
                Value::Null
            } else {
                serde_json::from_slice(&bytes[end..end + len]).unwrap()
            };
            seen.push(Seen {
                head: String::from_utf8_lossy(&bytes[..end]).to_string(),
                body,
            });
            let mut head = format!(
                "HTTP/1.1 {} Fixture\r\nContent-Length: {}\r\nConnection: close\r\n",
                reply.status,
                reply.body.len()
            );
            for (k, v) in reply.headers {
                head.push_str(&format!("{k}: {v}\r\n"));
            }
            stream.write_all(head.as_bytes()).unwrap();
            stream.write_all(b"\r\n").unwrap();
            stream.write_all(&reply.body).unwrap();
        }
        seen
    });
    (url, handle)
}
const KEY: &str = "sk-api-opsOwnerA.localSetupSuffix";
fn client(url: &str, credentials: SdkCredentials) -> OpenMates {
    OpenMates::new(SdkOptions {
        api_url: url.into(),
        credentials,
        device_id: "ops-device".into(),
        client_options: ClientOptions::default(),
    })
    .unwrap()
}
fn api(url: &str) -> OpenMates {
    client(url, SdkCredentials::ApiKey(ApiKey::new(KEY).unwrap()))
}
fn ok() -> Reply {
    json_reply(json!({"ok": true}))
}

#[tokio::test]
async fn billing_routes_queries_bodies_and_bearer_only_auth() {
    let (url, server) = serve((0..9).map(|_| ok()).collect());
    let c = api(&url);
    let b = c.billing();
    b.overview().await.unwrap();
    b.usage(&[("year_month", "2026-10"), ("q", "a&b")])
        .await
        .unwrap();
    b.usage_details("chat", "id/1", "2026-10").await.unwrap();
    b.save_buyer_address(Some(json!({"country": "DE"})))
        .await
        .unwrap();
    b.create_bank_transfer_order(1000, Some("k"), Some(json!({"country": "DE"})))
        .await
        .unwrap();
    b.bank_transfer_status("a/b c").await.unwrap();
    b.redeem_gift_card("GIFT-CODE").await.unwrap();
    b.request_refund("inv-1", true, None).await.unwrap();
    b.set_low_balance_auto_topup(json!({"enabled": false}))
        .await
        .unwrap();
    let seen = server.join().unwrap();
    assert_eq!(seen[0].line(), "GET /v1/sdk/billing HTTP/1.1");
    assert_eq!(
        seen[0].header("authorization").as_deref(),
        Some("Bearer sk-api-opsOwnerA")
    );
    assert!(!seen[0].head.contains("localSetupSuffix"));
    assert!(
        seen[1]
            .line()
            .starts_with("GET /v1/sdk/billing/usage?year_month=2026-10&q=a%26b ")
    );
    assert!(seen[2].line().starts_with(
        "GET /v1/sdk/billing/usage/details?type=chat&identifier=id%2F1&year_month=2026-10 "
    ));
    assert_eq!(
        (seen[3].line().split(' ').next(), &seen[3].body),
        (Some("PUT"), &json!({"buyer_address": {"country": "DE"}}))
    );
    assert_eq!(
        seen[4].body,
        json!({"credits_amount": 1000, "currency": "eur", "email_encryption_key": "k", "buyer_address": {"country": "DE"}})
    );
    assert!(
        seen[5]
            .line()
            .starts_with("GET /v1/sdk/billing/bank-transfer-orders/a%2Fb%20c ")
    );
    assert_eq!(seen[6].body, json!({"code": "GIFT-CODE"}));
    assert_eq!(
        (seen[7].line().split(' ').nth(1), &seen[7].body),
        (
            Some("/v1/sdk/billing/refund"),
            &json!({"invoice_id": "inv-1", "email_encryption_key": null})
        )
    );
    assert_eq!(
        seen[8].line().split(' ').nth(1),
        Some("/v1/sdk/billing/auto-topup/low-balance")
    );
}

#[tokio::test]
async fn refund_needs_confirmation_and_unconfirmed_calls_make_no_request() {
    let c = api("http://127.0.0.1:1");
    assert!(matches!(
        c.billing().request_refund("inv-1", false, None).await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        c.reminders().delete("r1", false).await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        c.settings().share_debug_logs(false, "1h").await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        c.settings().share_debug_logs(true, "1h").await,
        Err(Error::Unavailable { .. })
    ));
    assert!(matches!(
        c.billing().bank_transfer_status("").await,
        Err(Error::Invalid(_))
    ));
}

#[tokio::test]
async fn invoice_and_export_downloads_return_raw_bytes_with_safe_filenames() {
    let pdf = Reply {
        status: 200,
        headers: vec![
            ("Content-Type", "application/pdf"),
            (
                "Content-Disposition",
                "attachment; filename=\"../../inv-1.pdf\"",
            ),
        ],
        body: b"%PDF-1.7 synthetic".to_vec(),
    };
    let csv = Reply {
        status: 200,
        headers: vec![("Content-Type", "text/csv")],
        body: b"a,b\n1,2\n".to_vec(),
    };
    let denied = Reply {
        status: 403,
        headers: vec![],
        body: b"{}".to_vec(),
    };
    let (url, server) = serve(vec![pdf, csv, denied]);
    let c = api(&url);
    let invoice = c.billing().download_invoice("inv-1").await.unwrap();
    assert_eq!(
        (
            invoice.content_type.as_str(),
            invoice.filename.as_deref(),
            invoice.data.as_slice()
        ),
        (
            "application/pdf",
            Some("inv-1.pdf"),
            b"%PDF-1.7 synthetic".as_slice()
        )
    );
    let export = c.billing().usage_export(Some(3)).await.unwrap();
    assert_eq!(
        (export.filename, export.data),
        (None, b"a,b\n1,2\n".to_vec())
    );
    assert_eq!(
        c.billing().download_credit_note("inv-1").await.unwrap_err(),
        Error::Forbidden
    );
    let seen = server.join().unwrap();
    assert_eq!(
        seen[0].line(),
        "GET /v1/sdk/billing/invoices/inv-1/download HTTP/1.1"
    );
    assert_eq!(
        seen[1].line(),
        "GET /v1/sdk/billing/usage/export?months=3 HTTP/1.1"
    );
    assert!(seen[2].line().contains("/credit-note/download"));
}

#[tokio::test]
async fn settings_reminders_notifications_and_finance_wire_shapes() {
    let (url, server) = serve((0..11).map(|_| ok()).collect());
    let c = api(&url);
    c.settings().set_language("de").await.unwrap();
    c.settings().set_dark_mode(true).await.unwrap();
    c.settings().set_font("Lexend").await.unwrap();
    c.settings()
        .set_model_defaults(ModelDefaults {
            default_ai_model_simple: Some("m1".into()),
            ..Default::default()
        })
        .await
        .unwrap();
    c.settings().set_chat_auto_delete("30d").await.unwrap();
    c.reminders().list().await.unwrap();
    c.reminders()
        .update("r/1", json!({"prompt": "x"}))
        .await
        .unwrap();
    c.reminders().delete("r1", true).await.unwrap();
    c.notifications().status().await.unwrap();
    c.notifications().list(Some(5)).await.unwrap();
    let options = CheckAccountsOptions {
        connected_account_token_ref_inputs: vec![json!({"ref": "t1"})],
        prompt_injection_protection: Some(false),
        ..Default::default()
    };
    c.finance()
        .check_accounts(json!({"security": {"keep": 1}, "accounts": []}), options)
        .await
        .unwrap();
    let seen = server.join().unwrap();
    let route = |i: usize| {
        (
            seen[i].line().split(' ').next().unwrap().to_owned(),
            seen[i].line().split(' ').nth(1).unwrap().to_owned(),
        )
    };
    assert_eq!(
        route(0),
        ("POST".into(), "/v1/sdk/settings/language".into())
    );
    assert_eq!(seen[1].body, json!({"enabled": true}));
    assert_eq!(seen[2].body, json!({"font": "Lexend"}));
    assert_eq!(
        seen[3].body,
        json!({"default_ai_model_simple": "m1", "default_ai_model_complex": null, "default_ai_model_most_demanding": null})
    );
    assert_eq!(
        route(4),
        ("POST".into(), "/v1/sdk/settings/auto-delete/chats".into())
    );
    assert_eq!(route(5), ("GET".into(), "/v1/sdk/reminders".into()));
    assert_eq!(route(6), ("PATCH".into(), "/v1/sdk/reminders/r%2F1".into()));
    assert_eq!(route(7), ("DELETE".into(), "/v1/sdk/reminders/r1".into()));
    assert_eq!(
        route(8),
        ("GET".into(), "/v1/sdk/notifications/status".into())
    );
    assert_eq!(
        route(9),
        ("GET".into(), "/v1/sdk/notifications?limit=5".into())
    );
    assert_eq!(
        route(10),
        (
            "POST".into(),
            "/v1/sdk/connected-account-skills/finance/check_accounts".into()
        )
    );
    assert_eq!(
        seen[10].body,
        json!({
        "input": {"security": {"keep": 1, "prompt_injection_protection": "disabled"}, "accounts": []},
        "connected_account_token_ref_inputs": [{"ref": "t1"}], "chat_id": null, "message_id": null})
    );
}

#[tokio::test]
async fn anonymous_clients_cannot_reach_any_operation_facade() {
    let c = client(
        "http://127.0.0.1:1",
        SdkCredentials::Anonymous {
            anonymous_id: "ops-anon".into(),
        },
    );
    assert_eq!(
        c.billing().overview().await.unwrap_err(),
        Error::Authentication
    );
    assert_eq!(
        c.billing().download_invoice("i").await.unwrap_err(),
        Error::Authentication
    );
    assert_eq!(
        c.settings().set_font("x").await.unwrap_err(),
        Error::Authentication
    );
    assert_eq!(
        c.reminders().list().await.unwrap_err(),
        Error::Authentication
    );
    assert_eq!(
        c.notifications().status().await.unwrap_err(),
        Error::Authentication
    );
    assert_eq!(
        c.finance()
            .check_accounts(json!({}), Default::default())
            .await
            .unwrap_err(),
        Error::Authentication
    );
}

fn omca1(passcode: &str, payload: &Value) -> String {
    let (salt, iv) = ([3u8; 16], [4u8; 12]);
    let mut key = [0u8; 32];
    pbkdf2::pbkdf2_hmac::<sha2::Sha256>(passcode.as_bytes(), &salt, 100_000, &mut key);
    let text = Aes256Gcm::new_from_slice(&key)
        .unwrap()
        .encrypt((&iv).into(), payload.to_string().as_bytes())
        .unwrap();
    let envelope = json!({"version": 1, "kdf": {"name": "PBKDF2-SHA256", "iterations": 100_000, "salt": URL_SAFE_NO_PAD.encode(salt)},
        "cipher": {"name": "AES-256-GCM", "iv": URL_SAFE_NO_PAD.encode(iv), "text": URL_SAFE_NO_PAD.encode(text)}});
    format!("OMCA1.{}", URL_SAFE_NO_PAD.encode(envelope.to_string()))
}

#[tokio::test]
async fn connected_account_import_reencrypts_locally_and_never_posts_plaintext() {
    let master = [9u8; 32];
    let (salt, iv) = ([3u8; 16], [4u8; 12]);
    let mut wrapping = [0u8; 32];
    pbkdf2::pbkdf2_hmac::<sha2::Sha256>(b"localSetupSuffix", &salt, 100_000, &mut wrapping);
    let wrapped = Aes256Gcm::new_from_slice(&wrapping)
        .unwrap()
        .encrypt((&iv).into(), master.as_slice())
        .unwrap();
    let wrapper = json!({"key_wrapper": {"salt": STANDARD.encode(salt), "key_iv": STANDARD.encode(iv), "encrypted_key": STANDARD.encode(wrapped)}});
    let (url, server) = serve(vec![
        json_reply(json!({"id": "owner-1"})),
        json_reply(wrapper),
        json_reply(json!({"id": "stored-1"})),
    ]);
    let mut c = api(&url);
    let payload = json!({"version": 1, "provider_id": "google_calendar", "app_id": "google_calendar", "label": "Work",
        "capabilities": ["read", "write"], "runtime_modes": {}, "refresh_token_bundle": {"refresh_token": "secret-refresh", "scopes": ["calendar"]}});
    let transfer = omca1("1234", &payload);
    let result = c
        .connected_accounts()
        .import_account(&transfer, "1234", None)
        .await
        .unwrap();
    assert_eq!(result, json!({"id": "stored-1"}));
    let seen = server.join().unwrap();
    assert_eq!(seen[0].line(), "GET /v1/sdk/account HTTP/1.1");
    assert_eq!(seen[1].line(), "POST /v1/sdk/session HTTP/1.1");
    assert_eq!(
        seen[2].line(),
        "POST /v1/sdk/connected-accounts/import HTTP/1.1"
    );
    let raw = seen[2].body.to_string();
    assert!(
        !raw.contains("secret-refresh")
            && !raw.contains("1234")
            && !raw.contains("localSetupSuffix")
    );
    let row = &seen[2].body["row"];
    let open = |field: &str| {
        let bytes = STANDARD.decode(row[field].as_str().unwrap()).unwrap();
        let plain = Aes256Gcm::new_from_slice(&master)
            .unwrap()
            .decrypt(bytes[..12].into(), &bytes[12..])
            .unwrap();
        String::from_utf8(plain).unwrap()
    };
    assert_eq!(open("encrypted_provider_type"), "google_calendar");
    assert!(open("encrypted_refresh_token_bundle").contains("secret-refresh"));
    assert_eq!(row["hashed_user_id"].as_str().unwrap().len(), 64);
}

#[tokio::test]
async fn connected_account_import_refuses_teams_bad_passcodes_and_bad_payloads_before_any_request()
{
    let mut c = api("http://127.0.0.1:1");
    let payload = json!({"version": 1, "provider_id": "p", "app_id": "a", "label": "L", "capabilities": ["read"], "runtime_modes": {}, "refresh_token_bundle": {"refresh_token": "t"}});
    let transfer = omca1("1234", &payload);
    assert!(matches!(
        c.connected_accounts()
            .import_account(&transfer, "1234", Some("team-1"))
            .await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        c.connected_accounts()
            .import_account(&transfer, "wrong", None)
            .await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        c.connected_accounts()
            .import_account("not-a-payload", "1234", None)
            .await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        c.connected_accounts()
            .import_account(&transfer, "  ", None)
            .await,
        Err(Error::Invalid(_))
    ));
}

// One mapping for the gate example and this test (sdk-api-key-shared-conformance).
#[path = "../examples/sdk-api-key-shared-conformance/dispatch.rs"]
mod shared_dispatch;
use shared_dispatch::dispatch;

#[tokio::test]
async fn shared_operation_wire_vectors() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../tests/sdk-conformance/fixtures/sdk-api-key-operations.json"
    );
    let fixture: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let vectors = fixture["capabilities"]["sdk.api-key-operations.v1"]["vectors"]
        .as_array()
        .unwrap();
    assert!(vectors.len() >= 20);
    for vector in vectors {
        let (url, server) = serve(vec![ok()]);
        let c = api(&url);
        let args = vector["args"].as_array().unwrap();
        dispatch(
            &c,
            vector["operation"].as_str().unwrap(),
            args,
            &vector["kwargs"],
            vector["confirmed"].as_bool().unwrap_or(false),
        )
        .await
        .unwrap_or_else(|e| panic!("{}: {e}", vector["id"]))
        .unwrap_or_else(|e| panic!("{}: {e}", vector["id"]));
        let seen = server.join().unwrap().remove(0);
        let mut line = seen.line().split(' ');
        let expected = &vector["expect"];
        assert_eq!(
            line.next(),
            expected["method"].as_str(),
            "{} method",
            vector["id"]
        );
        assert_eq!(
            line.next(),
            expected["path"].as_str(),
            "{} path",
            vector["id"]
        );
        assert_eq!(seen.body, expected["body"], "{} body", vector["id"]);
    }
}
