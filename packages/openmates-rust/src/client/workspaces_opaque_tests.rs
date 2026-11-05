//! Public sharedRust facade tests with explicit synthetic credentials + real AES.
//! The primitive ports do not claim actual CryptoKey/server/account authentication.
// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use crate::crypto::master::{MasterCrypto, MasterCryptoFuture};
use std::sync::Arc;
struct Port {
    gate: Option<Arc<(tokio::sync::Notify, tokio::sync::Notify)>>,
}
impl MasterCrypto for Port {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plain: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            if let Some(gate) = &self.gate {
                gate.0.notify_one();
                gate.1.notified().await;
            }
            crypto::encrypt_aead(plain, &[7; 32], iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], cipher: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            if let Some(gate) = &self.gate {
                gate.0.notify_one();
                gate.1.notified().await;
            }
            crypto::decrypt_aead(cipher, &[7; 32], iv, &[])
        })
    }
}
fn client(
    base: &str,
    mode: &str,
    team: bool,
    gate: Option<Arc<(tokio::sync::Notify, tokio::sync::Notify)>>,
) -> Client {
    let mut c = super::delete_tests::client(base, team, false);
    c.user = json!({"id":"11111111-1111-4111-8111-111111111111","username":"synthetic"});
    if mode != "native" {
        let mut credentials = super::super::credentials::BrowserCredentials::from_native_session(
            c.session.take().unwrap(),
        );
        if mode == "opaque" {
            credentials.master = MasterCapability::opaque_for_test(Arc::new(Port { gate }));
        }
        c.browser_credentials = Some(credentials);
        c.browser_authority = Some(super::super::browser::BrowserAuthority {
            principal: "11111111-1111-4111-8111-111111111111".into(),
            persistence: super::super::browser::BrowserPersistence::MemoryOnly,
            owner_guards: true,
        });
        c.browser_transport = true;
    }
    if team {
        c.team_key = Some((
            "22222222-2222-4222-8222-222222222222".into(),
            zeroize::Zeroizing::new([7; 32]),
        ));
    }
    c
}
fn fields(workspace: Workspace, explicit: bool) -> Value {
    let mut fields =
        json!({"title":"Synthetic private title","description":"Synthetic private description"});
    if explicit {
        fields["slug"] = json!("synthetic-explicit-slug");
    }
    if workspace == Workspace::Projects {
        fields["default_focus_id"] = json!("33333333-3333-4333-8333-333333333333");
        fields["write_mode"] = json!("always_ask");
        fields["settings"] = json!({"private":"synthetic"});
    }
    fields
}
#[tokio::test]
async fn public_create_real_raw_and_opaque_keys_preserve_native_team_index_and_id_only_contract() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/workspace-opaque-capability.json"
    ))
    .unwrap();
    assert_eq!(fixture["cases"].as_array().unwrap().len(), 10);
    for mode in ["native", "raw_browser", "opaque"] {
        for team in [false, true] {
            for workspace in [Workspace::Tasks, Workspace::Projects] {
                let (base, peer) =
                    super::server_field_tests::peer(if workspace == Workspace::Tasks {
                        "task"
                    } else {
                        "project"
                    })
                    .await;
                let mut c = client(&base, mode, team, None);
                let item = c
                    .mutate(Mutation::Create {
                        workspace,
                        fields: fields(workspace, false),
                    })
                    .await
                    .unwrap()
                    .unwrap();
                assert_eq!(item.title, "Synthetic private title");
                let body = peer.await.unwrap();
                let id_only = mode == "opaque" && !team;
                assert_eq!(body.get("encrypted_slug").is_none(), id_only);
                assert_eq!(body.get("slug_lookup_hash").is_none(), id_only);
                if !id_only {
                    assert_eq!(
                        body["slug_lookup_hash"],
                        crypto::object_slug_lookup_hash("synthetic-private-title", &[7; 32])
                            .unwrap()
                    );
                }
                let key_field = if workspace == Workspace::Tasks {
                    "encrypted_task_key"
                } else {
                    "encrypted_project_key"
                };
                let key = key_from_bytes(&super::server_field_tests::strict_legacy(
                    body[key_field].as_str().unwrap(),
                    &[7; 32],
                ))
                .unwrap();
                for (name, value) in body.as_object().unwrap() {
                    if name.starts_with("encrypted_") && name != key_field {
                        let plain =
                            super::server_field_tests::strict_legacy(value.as_str().unwrap(), &key);
                        assert!(!plain.is_empty());
                    }
                }
                if team {
                    assert_eq!(body["key_wrappers"][0][key_field], body[key_field]);
                    assert_eq!(body["key_wrappers"][0]["team_key_epoch"], 1);
                }
            }
        }
    }
}
#[tokio::test]
async fn explicit_opaque_slug_fails_closed_before_http_and_does_not_publish_or_change_cache() {
    for workspace in [Workspace::Tasks, Workspace::Projects, Workspace::Workflows] {
        for update in [false, true] {
            let mut c = client("http://127.0.0.1:1", "opaque", false, None);
            let before = c
                .inventory_network
                .load(std::sync::atomic::Ordering::SeqCst);
            let cache = c.chats.clone();
            let mut input = fields(workspace, true);
            if workspace == Workspace::Workflows {
                input =
                    json!({"title":"Synthetic","graph":{"nodes":[],"edges":[]},"slug":"synthetic"});
            }
            assert!(matches!(
                c.mutate(if update {
                    Mutation::Update {
                        workspace,
                        id: "44444444-4444-4444-8444-444444444444".into(),
                        fields: input,
                    }
                } else {
                    Mutation::Create {
                        workspace,
                        fields: input,
                    }
                })
                .await,
                Err(Error::Unavailable {
                    code: "opaque_slug_index_unavailable",
                    ..
                })
            ));
            assert_eq!(
                c.inventory_network
                    .load(std::sync::atomic::Ordering::SeqCst),
                before
            );
            assert_eq!(c.chats, cache);
        }
    }
}
#[tokio::test]
async fn pending_master_wrapper_cancel_never_dispatches_mutation() {
    let gate = Arc::new((tokio::sync::Notify::new(), tokio::sync::Notify::new()));
    let mut c = client("http://127.0.0.1:1", "opaque", false, Some(gate.clone()));
    let cancel = CancellationToken::new();
    c.set_operation_cancel(cancel.clone());
    let before = c
        .inventory_network
        .load(std::sync::atomic::Ordering::SeqCst);
    let call = tokio::spawn(async move {
        let result = c
            .mutate(Mutation::Create {
                workspace: Workspace::Tasks,
                fields: fields(Workspace::Tasks, false),
            })
            .await;
        (c, result)
    });
    gate.0.notified().await;
    cancel.cancel();
    gate.1.notify_one();
    let (c, result) = call.await.unwrap();
    assert!(matches!(result, Err(Error::Cancelled)));
    assert_eq!(
        c.inventory_network
            .load(std::sync::atomic::Ordering::SeqCst),
        before
    );
}
#[tokio::test]
async fn pending_real_unwrap_checks_cancel_owner_denial_and_master_revocation() {
    for event in ["cancel", "owner", "denial", "master"] {
        let gate = Arc::new((tokio::sync::Notify::new(), tokio::sync::Notify::new()));
        let mut c = client("http://127.0.0.1:1", "opaque", false, Some(gate.clone()));
        let cancel = CancellationToken::new();
        c.set_operation_cancel(cancel.clone());
        let owner = c.task_watch_authority.clone();
        let master = c.master_capability().unwrap();
        let cap = master.clone();
        let row = json!({"project_id":"44444444-4444-4444-8444-444444444444","encrypted_project_key":crypto::server_fields::encrypt_bytes(&[8;32],&[7;32],&[]).unwrap()});
        let scope = AsyncCryptoScope::begin(&c).unwrap();
        let call = tokio::spawn(async move {
            c.object_key_with_capability(Workspace::Projects, &row, &cap, &scope)
                .await
                .map(|_| ())
        });
        gate.0.notified().await;
        match event {
            "cancel" => cancel.cancel(),
            "owner" => owner.cancel.cancel(),
            "denial" => owner.deny_cached_chat(Some("chat-denied")).unwrap(),
            "master" => master.invalidate(),
            _ => unreachable!(),
        };
        gate.1.notify_one();
        assert!(matches!(call.await.unwrap(), Err(Error::Cancelled)));
    }
}
#[tokio::test]
async fn local_mode_refuses_untagged_canonical_read_and_list_without_network() {
    let mut c = client("http://127.0.0.1:1", "opaque", false, None);
    c.browser_local_read_only = true;
    let before = c
        .inventory_network
        .load(std::sync::atomic::Ordering::SeqCst);
    for workspace in [
        Workspace::Chats,
        Workspace::Tasks,
        Workspace::Projects,
        Workspace::Workflows,
        Workspace::Settings,
        Workspace::Apps,
    ] {
        assert!(matches!(
            c.list(workspace).await,
            Err(Error::Unavailable {
                code: "local_profile_read_only",
                ..
            })
        ));
        assert!(matches!(
            c.detail(workspace, "id").await,
            Err(Error::Unavailable {
                code: "local_profile_read_only",
                ..
            })
        ));
    }
    assert_eq!(
        c.inventory_network
            .load(std::sync::atomic::Ordering::SeqCst),
        before
    );
}
#[tokio::test]
async fn actual_wrapper_selector_keeps_wrong_team_and_wrong_key_fail_closed() {
    let c = client("http://127.0.0.1:1", "opaque", false, None);
    let cap = c.master_capability().unwrap();
    let scope = AsyncCryptoScope::begin(&c).unwrap();
    let id = "44444444-4444-4444-8444-444444444444";
    let foreign = json!({"project_id":id,"hashed_team_id":"foreign","encrypted_project_key":crypto::server_fields::encrypt_bytes(&[8;32],&[7;32],&[]).unwrap()});
    assert!(matches!(
        c.object_key_with_capability(Workspace::Projects, &foreign, &cap, &scope)
            .await,
        Err(Error::Forbidden)
    ));
    let wrong = json!({"project_id":id,"encrypted_project_key":crypto::server_fields::encrypt_bytes(&[8;32],&[9;32],&[]).unwrap()});
    assert!(matches!(
        c.object_key_with_capability(Workspace::Projects, &wrong, &cap, &scope)
            .await,
        Err(Error::Crypto)
    ));
}

#[tokio::test]
async fn workflow_item_pending_optional_decrypt_is_refused_on_owner_cancel_or_future_drop() {
    for dropped in [false, true] {
        let gate = Arc::new((tokio::sync::Notify::new(), tokio::sync::Notify::new()));
        let c = client("http://127.0.0.1:1", "opaque", false, Some(gate.clone()));
        let owner = c.task_watch_authority.clone();
        let cap = c.master_capability().unwrap();
        let scope = AsyncCryptoScope::begin(&c).unwrap();
        let row = json!({"id":"44444444-4444-4444-8444-444444444444","title":"private already allocated workflow title","encrypted_slug":crypto::server_fields::encrypt_text("private slug",&[7;32],&[]).unwrap()});
        let call = tokio::spawn(async move {
            c.object_item_with_capability(Workspace::Workflows, &row, &cap, &scope)
                .await
                .map(|_| ())
        });
        gate.0.notified().await;
        if dropped {
            call.abort();
            assert!(call.await.unwrap_err().is_cancelled());
        } else {
            owner.cancel.cancel();
            gate.1.notify_one();
            assert!(matches!(call.await.unwrap(), Err(Error::Cancelled)));
        }
    }
}

#[tokio::test]
async fn project_detail_late_metadata_parse_failure_never_releases_partial_item_or_files() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let id = "44444444-4444-4444-8444-444444444444";
    let enc = |value: &str| crypto::server_fields::encrypt_text(value, &[8; 32], &[]).unwrap();
    let response = json!({"project":{"project_id":id,"encrypted_project_key":crypto::server_fields::encrypt_bytes(&[8;32],&[7;32],&[]).unwrap(),"encrypted_name":enc("private project title"),"encrypted_description":enc("private project description"),"encrypted_slug":enc("private-project"),"version":1},"folders":[{"folder_id":"folder","encrypted_name":enc("private first folder")}],"items":[{"item_type":"note","target_id_encrypted":enc("private-target"),"encrypted_display_name":enc("private second child"),"encrypted_metadata":enc("not-json"),"encrypted_note":enc("private note")}]});
    let peer = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = vec![];
        let mut chunk = [0; 4096];
        loop {
            let n = stream.read(&mut chunk).await.unwrap();
            assert!(n > 0);
            bytes.extend_from_slice(&chunk[..n]);
            if bytes.windows(4).any(|w| w == b"\r\n\r\n") {
                break;
            }
        }
        let request = String::from_utf8(bytes).unwrap();
        assert!(request.starts_with("GET /v1/projects/44444444-4444-4444-8444-444444444444 "));
        let body = response.to_string();
        stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
    });
    let mut c = client(&base, "opaque", false, None);
    let cached = c.chats.clone();
    assert!(c.detail(Workspace::Projects, id).await.is_err());
    assert_eq!(c.chats, cached);
    peer.await.unwrap();
}
