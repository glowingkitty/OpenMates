//! API-key facades for the SDK domains B (feedback, design, transport helpers,
//! public utilities, learning mode, benchmark): wire shape against a loopback
//! server, anonymous rejection before any request, and pure npm-parity helpers.
use openmates_sdk::sdk_feedback::build_assistant_feedback_decision;
use openmates_sdk::sdk_public_utilities::{default_clone_branch_for_version, render_support_info};
use openmates_sdk::sdk_transport::{filename_from_disposition, with_query};
use openmates_sdk::{ApiKey, ClientOptions, OpenMates, SdkCredentials, SdkOptions};
use std::io::{Read, Write};
use std::net::TcpListener;

fn client(api_url: String, credentials: SdkCredentials) -> OpenMates {
    OpenMates::new(SdkOptions {
        api_url,
        credentials,
        device_id: "domains-b-device".into(),
        client_options: ClientOptions::default(),
    })
    .unwrap()
}

// contract-test: direct surface=sdks.rust assertions=sdk.library.explicit-headless
#[tokio::test]
async fn feedback_posts_rating_with_bearer_key_and_returns_envelope() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut request = Vec::new();
        let mut buffer = [0u8; 4096];
        loop {
            let read = stream.read(&mut buffer).unwrap();
            request.extend_from_slice(&buffer[..read]);
            let text = String::from_utf8_lossy(&request).to_string();
            if let Some(split) = text.find("\r\n\r\n") {
                if text.len() >= split + 4 + text[..split]
                    .to_ascii_lowercase()
                    .split("content-length: ")
                    .nth(1)
                    .and_then(|v| v.split("\r\n").next())
                    .and_then(|v| v.parse::<usize>().ok())
                    .unwrap_or(0)
                {
                    break;
                }
            }
            if read == 0 {
                break;
            }
        }
        let body = br#"{"ok":true}"#;
        write!(stream, "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n", body.len()).unwrap();
        stream.write_all(body).unwrap();
        String::from_utf8_lossy(&request).to_ascii_lowercase()
    });
    let sdk = client(
        format!("http://127.0.0.1:{port}"),
        SdkCredentials::ApiKey(ApiKey::new("sk-api-domainsb").unwrap()),
    );
    let response = sdk.feedback().assistant_response(4).await.unwrap();
    assert_eq!(response, serde_json::json!({"ok": true}));
    let request = server.join().unwrap();
    assert!(request.starts_with("post /v1/sdk/feedback/assistant-response "));
    assert!(request.contains("authorization: bearer sk-api-domainsb\r\n"));
    assert!(request.ends_with("{\"rating\":4}"));
}

// contract-test: direct surface=sdks.rust assertions=sdk.library.explicit-headless
#[tokio::test]
async fn anonymous_callers_are_rejected_before_any_request() {
    let sdk = client(
        "http://127.0.0.1:1".into(),
        SdkCredentials::Anonymous { anonymous_id: "anon-domains-b".into() },
    );
    assert!(sdk.feedback().assistant_response(5).await.is_err());
}

#[test]
fn feedback_decision_matches_npm() {
    let low = build_assistant_feedback_decision(3).unwrap();
    assert_eq!(low.action, "report_issue");
    assert!(low.report_title.is_some());
    let high = build_assistant_feedback_decision(4).unwrap();
    assert_eq!(high.action, "thanks");
    assert!(build_assistant_feedback_decision(0).is_err());
    assert!(build_assistant_feedback_decision(6).is_err());
}

#[test]
fn transport_and_public_helpers_match_npm() {
    assert_eq!(
        with_query("/v1/x", &[("a", Some("b c".into())), ("d", None)]),
        "/v1/x?a=b+c"
    );
    assert_eq!(
        filename_from_disposition("attachment; filename=\"report.csv\"").as_deref(),
        Some("report.csv")
    );
    assert_eq!(default_clone_branch_for_version("1.2.0-beta.3"), Some("dev"));
    assert_eq!(default_clone_branch_for_version("1.2.0"), None);
    assert!(render_support_info().contains("https://app.openmates.org/#settings/support"));
}
