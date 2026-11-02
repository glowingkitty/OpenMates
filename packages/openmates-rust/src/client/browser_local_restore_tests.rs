//! Local-only recovery of explicit existing resources. Native protocol mocks
//! do not prove actual Cookie Fetch/IDB/CryptoKey behavior; worker CI owns that.
// contract-test-file: tooling
use super::tests::{evidence, server_raw_response, server_raw_responses};
use super::*;
use crate::crypto::master::{MasterCapability, MasterCrypto, MasterCryptoFuture};
use std::sync::Arc;
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const SESSION: &str = "66666666-6666-4666-8666-666666666666";
struct AesPort;
impl MasterCrypto for AesPort {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plain: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            crypto::encrypt_aead(plain, &[7; 32], iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], cipher: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { crypto::decrypt_aead(cipher, &[7; 32], iv, &[]) })
    }
}
fn legacy_profile() -> BrowserProfileKey {
    let mut profile = evidence(7);
    profile.master = MasterCapability::opaque_for_test(Arc::new(AesPort));
    // These optional values are not a new login/enrollment prerequisite.
    profile.hashed_email.clear();
    profile.user_email_salt.clear();
    profile
}
async fn restore(url: &str, profile: BrowserProfileKey) -> Result<Client> {
    Client::restore_browser_credentials_inner(url, "https://app.example.invalid", SESSION, profile)
        .await
}
fn genuine() -> Value {
    json!({"success":true,"user":{"id":OWNER},"ws_token":"synthetic-token","client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]})
}
#[tokio::test]
async fn unavailable_response_keeps_explicit_legacy_key_in_read_only_non_ack_mode() {
    for status in [429, 500, 503] {
        let (url, peer) = server_raw_response("{}".into(), status).await;
        let mut c = restore(&url, legacy_profile()).await.unwrap();
        assert!(c.is_local_browser_profile());
        assert!(c.browser_session_status().unwrap().is_local_read_only());
        assert!(c.require_credentials().unwrap().ws_token.is_none());
        assert!(c.session.is_none());
        assert!(c.session().is_none());
        assert!(c.credential_snapshot().is_none());
        assert_eq!(c.credential_ack, 0);
        let master = c.master_capability().unwrap();
        let cipher = master
            .encrypt_bytes(b"synthetic already-owned cached row")
            .await
            .unwrap();
        assert_eq!(
            &*master.decrypt_bytes(&cipher).await.unwrap(),
            b"synthetic already-owned cached row"
        );
        // No GET, mutation, inference, stream or persistence capability follows
        // from local key availability. These checks dispatch no second request.
        for method in [Method::GET, Method::POST] {
            assert!(matches!(
                c.request(method, "/v1/projects", None).await,
                Err(Error::Unavailable {
                    code: "browser_offline_read_only",
                    ..
                })
            ));
        }
        assert!(
            c.begin_browser_credential_cas(
                serde_json::from_value(json!({"lifecycleGeneration":1,"workspaceEpoch":0}))
                    .unwrap()
            )
            .is_err()
        );
        assert!(c.prepare_browser_credential_snapshot().await.is_err());
        assert!(c.acknowledge_credentials(c.credential_revision).is_err());
        assert_eq!(c.credential_ack, 0);
        assert!(peer.await.unwrap().starts_with("POST /v1/auth/session "));
    }
}
#[tokio::test]
async fn hard_http_owner_protocol_denials_never_admit_local_fallback_and_revoke_resource() {
    for (status,body) in [
        (401,"{}".to_owned()),(403,"{}".to_owned()),
        (403,json!({"detail":{"error":"session_principal_mismatch"}}).to_string()),
        (400,"{}".to_owned()),(200,"not-json".to_owned()),
        (200,json!({"success":false}).to_string()),
        (200,json!({"success":true,"user":{"id":"77777777-7777-4777-8777-777777777777"},"ws_token":"other"}).to_string()),
        (200,json!({"success":true,"user":{"id":OWNER}}).to_string()),
    ] {
        let(url,peer)=server_raw_response(body,status).await;let profile=legacy_profile();let held=profile.master.clone();assert!(restore(&url,profile).await.is_err());
        assert!(matches!(held.encrypt_bytes(b"private stale output").await,Err(Error::Cancelled)));assert!(peer.await.unwrap().starts_with("POST /v1/auth/session "));
    }
}
#[tokio::test]
async fn genuine_fresh_validation_promotes_local_mode_then_known_expiry_fences_everything() {
    let (url, peer) = server_raw_responses(vec![
        ("{}".into(), 503),
        (genuine().to_string(), 200),
        ("{}".into(), 401),
    ])
    .await;
    let mut c = restore(&url, legacy_profile()).await.unwrap();
    let context = c.fresh_auth_binding().unwrap();
    let held = c.master_capability().unwrap();
    c.validate_session().await.unwrap();
    assert!(!c.is_local_browser_profile());
    assert!(!c.browser_session_status().unwrap().is_local_read_only());
    assert!(c.require_browser_owner_guards().is_ok());
    assert_ne!(context, c.fresh_auth_binding().unwrap());
    assert!(c.session.is_none());
    assert!(c.credential_snapshot().is_none());
    assert_eq!(c.credential_ack, 0);
    assert!(matches!(c.validate_session().await, Err(Error::Expired)));
    assert!(c.browser_session_status().is_none());
    assert!(c.require_credentials().is_err());
    assert!(!c.is_local_browser_profile());
    assert!(matches!(
        held.encrypt_bytes(b"stale").await,
        Err(Error::Cancelled)
    ));
    let requests = peer.await.unwrap();
    assert_eq!(requests.len(), 3);
    assert!(
        requests
            .iter()
            .all(|request| request.starts_with("POST /v1/auth/session "))
    );
}
#[tokio::test]
async fn known_paired_deadline_is_restricting_and_cannot_be_removed_or_extended() {
    let deadline = now_ms() + 60000;
    let p = legacy_profile()
        .with_existing_paired_deadline(Some(deadline))
        .unwrap();
    let p = p
        .with_existing_paired_deadline(None)
        .unwrap()
        .with_existing_paired_deadline(Some(deadline + 60000))
        .unwrap();
    assert_eq!(p.paired_session_expires_at, Some(deadline));
    let mut p = legacy_profile();
    let held = p.master.clone();
    p.paired_session_expires_at = Some(0);
    assert!(matches!(
        restore("http://127.0.0.1:9", p).await,
        Err(Error::Expired)
    ));
    assert!(matches!(
        held.encrypt_bytes(b"private").await,
        Err(Error::Cancelled)
    ));
}
#[tokio::test]
async fn explicit_logout_wipes_local_authority_even_when_backend_guard_is_unavailable() {
    let (url, peer) = server_raw_response("{}".into(), 503).await;
    let mut c = restore(&url, legacy_profile()).await.unwrap();
    let held = c.master_capability().unwrap();
    assert!(c.logout().await.is_err());
    assert!(c.browser_session_status().is_none());
    assert!(c.require_credentials().is_err());
    assert!(c.credential_snapshot().is_none());
    assert!(matches!(
        held.decrypt_bytes("AA==").await,
        Err(Error::Cancelled)
    ));
    peer.await.unwrap();
}
#[test]
fn unavailable_admission_never_overrides_auth_privacy_cancel_or_header_denial_evidence() {
    for error in [
        Error::Expired,
        Error::Authentication,
        Error::Forbidden,
        Error::Cancelled,
        Error::Protocol,
        Error::Crypto,
    ] {
        assert!(!browser_restore_network_unavailable(error, None));
    }
    for status in [
        Some(301),
        Some(400),
        Some(401),
        Some(403),
        Some(404),
        Some(409),
    ] {
        assert!(!browser_restore_network_unavailable(Error::Offline, status));
    }
    for status in [None, Some(200), Some(429), Some(500), Some(503)] {
        assert!(browser_restore_network_unavailable(Error::Offline, status));
    }
}

async fn raw_auth_sequence(
    tail_status: u16,
    tail: String,
    truncate: bool,
    first_genuine: bool,
    gate: Option<std::sync::Arc<(tokio::sync::Notify, tokio::sync::Notify)>>,
) -> (String, tokio::task::JoinHandle<usize>) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let peer = tokio::spawn(async move {
        let count = if first_genuine { 2 } else { 1 };
        for index in 0..count {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut request = vec![];
            loop {
                let mut bytes = [0u8; 2048];
                let n = stream.read(&mut bytes).await.unwrap();
                assert!(n > 0 && request.len() + n <= 65536);
                request.extend_from_slice(&bytes[..n]);
                if let Some(end) = request.windows(4).position(|part| part == b"\r\n\r\n") {
                    let head = std::str::from_utf8(&request[..end]).unwrap();
                    assert!(head.starts_with("POST /v1/auth/session "));
                    let len = head
                        .lines()
                        .find_map(|line| {
                            line.to_ascii_lowercase()
                                .strip_prefix("content-length:")
                                .map(|n| n.trim().parse::<usize>().unwrap())
                        })
                        .unwrap_or(0);
                    if request.len() == end + 4 + len {
                        break;
                    }
                }
            }
            let last = index == count - 1;
            let status = if last { tail_status } else { 200 };
            let body = if last {
                tail.clone()
            } else {
                genuine().to_string()
            };
            let declared = body.len() + if last && truncate { 8 } else { 0 };
            stream.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {declared}\r\nConnection: close\r\n\r\n").as_bytes()).await.unwrap();
            if last && let Some(gate) = &gate {
                gate.0.notify_one();
                gate.1.notified().await;
            }
            let _ = stream.write_all(body.as_bytes()).await;
        }
        count
    });
    (url, peer)
}
#[tokio::test]
async fn observed_200_body_io_is_local_only_but_401_403_truncation_never_falls_back() {
    for initial in [false, true] {
        for status in [200, 401, 403] {
            let (url, peer) = raw_auth_sequence(status, "{".into(), true, !initial, None).await;
            if initial {
                let profile = legacy_profile();
                let held = profile.master.clone();
                let result = restore(&url, profile).await;
                if status == 200 {
                    let c = result.unwrap();
                    assert!(c.is_local_browser_profile());
                    assert!(c.require_credentials().unwrap().ws_token.is_none());
                } else {
                    assert!(result.is_err());
                    assert!(matches!(
                        held.encrypt_bytes(b"private").await,
                        Err(Error::Cancelled)
                    ));
                }
            } else {
                let mut c = restore(&url, legacy_profile()).await.unwrap();
                let held = c.master_capability().unwrap();
                let old_authority = c.task_watch_authority.clone();
                let prepared = c.prepare_task_socket().unwrap();
                let prepared_source = c.prepare_source_host_socket().unwrap();
                assert!(c.validate_session().await.is_err());
                if status == 200 {
                    assert!(c.is_local_browser_profile());
                    assert!(c.require_credentials().unwrap().ws_token.is_none());
                    assert!(!c.browser_authority.as_ref().unwrap().owner_guards);
                    assert!(old_authority.cancel.is_cancelled());
                    assert!(matches!(
                        c.prepare_task_socket(),
                        Err(Error::Unavailable {
                            code: "browser_offline_read_only",
                            ..
                        })
                    ));
                    assert!(c.prepare_source_host_socket().is_err());
                } else {
                    assert!(c.browser_session_status().is_none());
                    assert!(c.require_credentials().is_err());
                    assert!(matches!(
                        held.encrypt_bytes(b"private").await,
                        Err(Error::Cancelled)
                    ));
                }
                assert!(matches!(
                    transport::connect_task_socket(prepared).await,
                    Err(Error::Cancelled)
                ));
                assert!(matches!(
                    transport::connect_source_host_socket(prepared_source).await,
                    Err(Error::Cancelled)
                ));
            }
            assert_eq!(peer.await.unwrap(), if initial { 1 } else { 2 });
        }
    }
}
#[tokio::test]
async fn pending_cancelled_auth_cannot_publish_token_guards_or_promote_local_profile() {
    let gate = std::sync::Arc::new((tokio::sync::Notify::new(), tokio::sync::Notify::new()));
    let (url, peer) =
        raw_auth_sequence(200, genuine().to_string(), false, false, Some(gate.clone())).await;
    let mut c = Client::with_options(
        &url,
        None,
        ClientOptions {
            app_url: Some("https://app.example.invalid".into()),
            ..Default::default()
        },
    )
    .unwrap();
    c.browser_transport = true;
    c.browser_authority = Some(BrowserAuthority {
        principal: OWNER.into(),
        persistence: BrowserPersistence::MemoryOnly,
        owner_guards: false,
    });
    let profile = legacy_profile();
    c.browser_credentials = Some(credentials::BrowserCredentials {
        api_url: url.clone(),
        session_id: SESSION.into(),
        cookies: Default::default(),
        ws_token: None,
        master: profile.master.clone(),
        hashed_email: String::new(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: now_ms(),
        paired_session_expires_at: None,
        active_team_id: None,
    });
    c.user = json!({"id":OWNER});
    c.browser_local_read_only = true;
    let external = CancellationToken::new();
    c.set_operation_cancel(external.clone());
    let revision = c.credential_revision;
    let task = tokio::spawn(async move {
        let result = c.validate_session().await;
        (c, result)
    });
    gate.0.notified().await;
    external.cancel();
    gate.1.notify_one();
    let (c, result) = task.await.unwrap();
    assert!(matches!(result, Err(Error::Cancelled)));
    assert!(c.is_local_browser_profile());
    assert!(c.require_credentials().unwrap().ws_token.is_none());
    assert!(!c.browser_authority.as_ref().unwrap().owner_guards);
    assert_eq!(c.credential_revision, revision);
    assert_eq!(c.credential_ack, 0);
    assert_eq!(peer.await.unwrap(), 1);
}
#[tokio::test]
async fn complete_protocol_failure_during_refresh_revokes_instead_of_retaining_local_grant() {
    for body in [
        "not-json".to_owned(),
        json!({"success":true,"user":{"id":OWNER}}).to_string(),
        json!({"success":false}).to_string(),
        json!({"success":true,"user":{"id":"77777777-7777-4777-8777-777777777777"},"ws_token":"other"}).to_string(),
    ] {
        let (url, peer) = server_raw_responses(vec![("{}".into(), 503), (body, 200)]).await;
        let mut c = restore(&url, legacy_profile()).await.unwrap();
        let held = c.master_capability().unwrap();
        assert!(c.validate_session().await.is_err());
        assert!(c.require_credentials().is_err());
        assert!(!c.is_local_browser_profile());
        assert!(matches!(
            held.encrypt_bytes(b"private").await,
            Err(Error::Cancelled)
        ));
        assert_eq!(peer.await.unwrap().len(), 2);
    }
}

#[tokio::test]
async fn cancelled_online_refresh_revokes_already_prepared_task_and_source_sockets() {
    let gate=std::sync::Arc::new((tokio::sync::Notify::new(),tokio::sync::Notify::new()));
    let(url,peer)=raw_auth_sequence(200,genuine().to_string(),false,true,Some(gate.clone())).await;
    let mut c=restore(&url,legacy_profile()).await.unwrap();let prepared=c.prepare_task_socket().unwrap();let source=c.prepare_source_host_socket().unwrap();let old_authority=c.task_watch_authority.clone();
    let external=CancellationToken::new();c.set_operation_cancel(external.clone());let task=tokio::spawn(async move{let result=c.validate_session().await;(c,result)});
    gate.0.notified().await;external.cancel();gate.1.notify_one();let(c,result)=task.await.unwrap();assert!(matches!(result,Err(Error::Cancelled)));assert!(c.require_credentials().unwrap().ws_token.is_none());assert!(old_authority.cancel.is_cancelled());assert!(!c.browser_authority.as_ref().unwrap().owner_guards);
    // A retained status is profile context, never a replacement transport grant.
    assert!(c.require_browser_owner_guards().is_err());assert_eq!(c.credential_ack,0);
    assert!(matches!(transport::connect_task_socket(prepared).await,Err(Error::Cancelled)));assert!(matches!(transport::connect_source_host_socket(source).await,Err(Error::Cancelled)));assert_eq!(peer.await.unwrap(),2);
}

#[tokio::test]
async fn known_expired_prepared_task_source_and_live_context_refuse_without_network() {
    let(url,peer)=server_raw_response(genuine().to_string(),200).await;let mut c=restore(&url,legacy_profile()).await.unwrap();let held=c.master_capability().unwrap();
    let mut task=c.prepare_task_socket().unwrap();let mut source=c.prepare_source_host_socket().unwrap();
    transport::expire_prepared_socket_for_test(&mut task);transport::expire_prepared_source_socket_for_test(&mut source);
    assert!(matches!(transport::connect_task_socket(task).await,Err(Error::Expired)));assert!(matches!(transport::connect_source_host_socket(source).await,Err(Error::Expired)));
    c.browser_credentials.as_mut().unwrap().paired_session_expires_at=Some(0);
    assert!(matches!(c.require_credentials(),Err(Error::Expired)));assert!(c.browser_session_status().is_none());assert!(c.task_watch_authority.cancel.is_cancelled());assert!(c.operation_cancel.is_cancelled());assert!(matches!(held.encrypt_bytes(b"private").await,Err(Error::Cancelled)));assert!(matches!(c.request(Method::GET,"/v1/projects",None).await,Err(Error::Expired)));assert!(matches!(c.validate_session().await,Err(Error::Expired)));peer.await.unwrap();
}

#[tokio::test]
async fn successful_refresh_retires_prepared_urls_preserving_healthy_monitor_and_owner() {
    let(url,peer)=server_raw_responses(vec![(genuine().to_string(),200),(genuine().to_string(),200)]).await;
    let mut c=restore(&url,legacy_profile()).await.unwrap();let held=c.master_capability().unwrap();
    let task=c.prepare_task_socket().unwrap();let source=c.prepare_source_host_socket().unwrap();let old=c.task_watch_authority.clone();
    old.deny_cached_chat(Some("retained-denial")).unwrap();
    let denial_revision=old.cached_denial_revision().unwrap();
    let monitor=c.retain_browser_monitor_for_test().unwrap();
    let monitor_cancel=c.monitor_cancel.as_ref().unwrap().clone();
    c.validate_chat_monitor(&monitor).await.unwrap();
    assert!(!old.cancel.is_cancelled());assert!(std::sync::Arc::ptr_eq(&old,&c.task_watch_authority));assert!(!monitor_cancel.is_cancelled());
    assert!(!c.task_watch_authority.cached_chat_allowed("retained-denial"));
    assert_eq!(old.cached_denial_revision().unwrap(),denial_revision);
    old.deny_cached_chat(Some("late-negative")).unwrap();
    assert!(!c.task_watch_authority.cached_chat_allowed("late-negative"));assert!(c.require_browser_owner_guards().is_ok());
    assert!(c.require_credentials().unwrap().ws_token.is_some());assert!(!c.browser_session_status().unwrap().is_local_read_only());assert_eq!(c.credential_ack,0);
    assert!(matches!(transport::connect_task_socket(task).await,Err(Error::Cancelled)));assert!(matches!(transport::connect_source_host_socket(source).await,Err(Error::Cancelled)));
    assert!(held.encrypt_bytes(b"retained local key").await.is_ok());assert!(c.prepare_task_socket().is_ok());assert_eq!(peer.await.unwrap().len(),2);
}

#[tokio::test]
async fn offline_and_cancelled_grant_clear_retain_same_owner_negative_fences() {
    for local in [false,true] {
        let(url,peer)=server_raw_response(genuine().to_string(),200).await;let mut c=restore(&url,legacy_profile()).await.unwrap();
        let old=c.task_watch_authority.clone();old.deny_cached_chat(Some("denied-chat")).unwrap();let old_revision=old.cached_denial_revision().unwrap();
        if local{c.enter_browser_local_read_only();}else{c.clear_browser_transport_grant();}
        assert!(old.cancel.is_cancelled());assert!(!c.task_watch_authority.cancel.is_cancelled());assert!(!c.task_watch_authority.cached_chat_allowed("denied-chat"));assert!(old.commit_cached_chat_recovery("denied-chat",false,old_revision).is_err());
        old.deny_cached_chat(Some("late-denied-chat")).unwrap();assert!(!c.task_watch_authority.cached_chat_allowed("late-denied-chat"));
        assert!(c.require_credentials().unwrap().ws_token.is_none());assert!(!c.browser_authority.as_ref().unwrap().owner_guards);assert_eq!(c.is_local_browser_profile(),local);peer.await.unwrap();
    }
}
