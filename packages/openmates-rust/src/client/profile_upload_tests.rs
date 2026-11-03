use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

fn rejected(result: std::result::Result<(), UploadError>) -> String {
    match result {
        Err(UploadError::Rejected(message)) => message,
        _ => panic!("expected rejection"),
    }
}

#[test]
fn multipart_form_puts_fields_before_the_file_part() {
    let body = multipart_form(
        "B",
        &[("team_id", "t1"), ("x\"y", "a\nb")],
        "p.png",
        "image/png",
        b"PX",
    );
    assert_eq!(
        String::from_utf8(body).unwrap(),
        "--B\r\nContent-Disposition: form-data; name=\"team_id\"\r\n\r\nt1\r\n\
         --B\r\nContent-Disposition: form-data; name=\"x%22y\"\r\n\r\na\r\nb\r\n\
         --B\r\nContent-Disposition: form-data; name=\"file\"; filename=\"p.png\"\r\nContent-Type: image/png\r\n\r\nPX\r\n--B--\r\n"
    );
}

#[test]
fn npm_status_messages_and_metadata_order() {
    assert!(check_status(&json!({"status":"ok"}), false).is_ok());
    assert_eq!(
        rejected(check_status(&json!({"status":"rejected"}), false)),
        "Profile image rejected by content safety checks."
    );
    assert_eq!(
        rejected(check_status(
            &json!({"status":"rejected","detail":"nsfw"}),
            true
        )),
        "nsfw"
    );
    assert_eq!(
        rejected(check_status(&json!({"status":"account_deleted"}), false)),
        "Account deleted due to repeated profile image policy violations."
    );
    assert_eq!(
        rejected(check_status(&json!({}), false)),
        "Profile image upload failed with status 'undefined'."
    );
    assert_eq!(
        rejected(check_status(&json!({"status":"ok"}), true)),
        "Team profile image upload failed with status 'ok'."
    );
    assert!(
        check_status(
            &json!({"status":"ok","url":"/v1/teams/t/profile-image"}),
            true
        )
        .is_ok()
    );
    assert_eq!(
        uploaded_team_profile_image_metadata("t1", "/v1/teams/t1/profile-image", 5),
        r#"{"version":1,"mode":"uploaded","image_url":"/v1/teams/t1/profile-image","content_safety_status":"accepted","updated_at":5,"team_id":"t1"}"#
    );
    assert!(
        matches!(profile_image_mime("a.gif"), Err(UploadError::Rejected(m)) if m == "Profile images must be JPEG or PNG files.")
    );
    assert_eq!(profile_image_mime("A.JPEG").ok(), Some("image/jpeg"));
    assert!(team_segment("../x").is_err());
}

fn signed_in() -> Client {
    let mut client = Client::new("https://api.dev.openmates.org", None).unwrap();
    client
        .cookies
        .insert("auth_refresh_token".into(), "fixture".into());
    client.session = Some(Session {
        api_url: "https://api.dev.openmates.org".into(),
        session_id: "fixture".into(),
        cookies: client.cookies.clone(),
        ws_token: None,
        master_key: Zeroizing::new([1; 32]),
        hashed_email: "hash".into(),
        user_email_salt: "salt".into(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    });
    client
}

async fn serve(response: &'static [u8]) -> (String, tokio::task::JoinHandle<Vec<u8>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!(
        "http://{}/v1/upload/profile-image",
        listener.local_addr().unwrap()
    );
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut request = Vec::new();
        let mut buffer = [0u8; 4096];
        loop {
            let n = stream.read(&mut buffer).await.unwrap();
            request.extend_from_slice(&buffer[..n]);
            if n == 0 || request.ends_with(b"--\r\n") {
                break;
            }
        }
        stream.write_all(response).await.unwrap();
        request
    });
    (url, server)
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn profile_form_sends_only_refresh_cookie_and_origin_with_sanitized_bytes() {
    let (url, server) =
        serve(b"HTTP/1.1 200 OK\r\nContent-Length: 34\r\nConnection: close\r\n\r\n{\"status\":\"ok\",\"url\":\"/a/b.png\"}  ").await;
    let mut client = signed_in();
    client.cookies.insert("other".into(), "never-sent".into());
    let prepared = PreparedUpload {
        bytes: b"CLEAN".to_vec(),
        mime_type: "image/png".into(),
        sanitized: true,
    };
    let data = client
        .post_profile_form(&url, &[("team_id", "t1")], "p.png", &prepared)
        .await
        .ok()
        .unwrap();
    assert_eq!(data["url"], "/a/b.png");
    let request = String::from_utf8_lossy(&server.await.unwrap()).into_owned();
    let lower = request.to_lowercase();
    assert!(lower.contains("origin: https://app.dev.openmates.org"));
    assert!(lower.contains("cookie: auth_refresh_token=fixture\r\n"));
    assert!(!request.contains("never-sent"));
    assert!(
        lower.contains("content-type: multipart/form-data; boundary=----openmatesformboundary")
    );
    assert!(request.contains("name=\"team_id\"\r\n\r\nt1\r\n"));
    assert!(request.contains("filename=\"p.png\"\r\nContent-Type: image/png\r\n\r\nCLEAN\r\n"));
}

#[tokio::test]
async fn profile_form_failure_without_status_uses_detail_or_http_message() {
    let (url, server) =
        serve(b"HTTP/1.1 413 Too Large\r\nContent-Length: 2\r\nConnection: close\r\n\r\nno").await;
    let mut client = signed_in();
    let prepared = PreparedUpload {
        bytes: b"X".to_vec(),
        mime_type: "image/png".into(),
        sanitized: false,
    };
    match client
        .post_profile_form(&url, &[], "p.png", &prepared)
        .await
    {
        Err(UploadError::Rejected(message)) => {
            assert_eq!(message, "Profile image upload failed (HTTP 413).")
        }
        _ => panic!("expected HTTP failure"),
    }
    server.await.unwrap();
}
