//! Synthetic real AES and inert barrier/HTTP regressions; authored UNRUN.
//! No test asserts genuine account authority, browser resources or native ACK.
// contract-test-file: tooling
use super::*;
use crate::crypto::master::{MasterCapability, MasterCrypto, MasterCryptoFuture};
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
use tokio::sync::Notify;
const PROJECT: &str = "11111111-1111-4111-8111-111111111111";
const SECOND: &str = "22222222-2222-4222-8222-222222222222";
const CHAT: &str = "33333333-3333-4333-8333-333333333333";
struct Gate {
    entered: Notify,
    release: Notify,
    calls: AtomicUsize,
    at: usize,
}
struct AesPort {
    gate: Option<Arc<Gate>>,
}
impl MasterCrypto for AesPort {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], bytes: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            crypto::encrypt_aead(bytes, &[7; 32], iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], bytes: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            if let Some(gate) = &self.gate {
                if gate.calls.fetch_add(1, Ordering::SeqCst) + 1 == gate.at {
                    gate.entered.notify_one();
                    gate.release.notified().await;
                }
            }
            crypto::decrypt_aead(bytes, &[7; 32], iv, &[])
        })
    }
}
fn fixture(opaque: bool, gate: Option<Arc<Gate>>) -> Client {
    let mut client = client("http://127.0.0.1:9");
    client.user = json!({"id":PROJECT,"username":"Synthetic"});
    if opaque {
        let mut credentials =
            credentials::BrowserCredentials::from_native_session(client.session.take().unwrap());
        credentials.master = MasterCapability::opaque_for_test(Arc::new(AesPort { gate }));
        client.browser_credentials = Some(credentials);
        client.browser_authority = Some(browser::BrowserAuthority {
            principal: PROJECT.into(),
            persistence: browser::BrowserPersistence::MemoryOnly,
            owner_guards: true,
        });
        // This models admitted mode only; no server/account proof is claimed.
        client.browser_local_read_only = false;
    }
    client
}
fn candidate(id: &str, name: &str, summary: Option<&str>) -> Value {
    let mut row = json!({"project_id":id,"auto_selection":true,"focus_activation_policy":"delayed","encrypted_project_key":crypto::server_fields::encrypt_bytes(&[8;32],&[7;32],&[]).unwrap(),"encrypted_name":crypto::encrypt_combined(name,&[8;32]).unwrap()});
    if let Some(summary) = summary {
        row["encrypted_description"] = json!(crypto::encrypt_combined(summary, &[8; 32]).unwrap());
    }
    row
}
#[tokio::test]
async fn native_and_opaque_candidates_preserve_actual_child_decode_optional_and_character_bounds() {
    for opaque in [false, true] {
        let client = fixture(opaque, None);
        let rows = vec![
            candidate(PROJECT, &"Δ".repeat(200), Some(&"界".repeat(700))),
            candidate(SECOND, "Second", None),
        ];
        let output = client.decode_project_candidates(&rows).await.unwrap();
        assert_eq!(output[0]["name"], "Δ".repeat(160));
        assert_eq!(output[0]["summary"], "界".repeat(640));
        assert_eq!(output[1]["summary"], "");
        assert_eq!(output[0]["focus_activation_policy"], "delayed");
        assert_eq!(client.credential_ack, 0);
        for invalid in [
            json!({"encrypted_description":7}),
            json!({"focus_activation_policy":"unknown"}),
            json!({"auto_selection":false}),
        ] {
            let mut row = rows[0].clone();
            for (k, v) in invalid.as_object().unwrap() {
                row[k] = v.clone();
            }
            assert!(client.decode_project_candidates(&[row]).await.is_err());
        }
        assert!(matches!(
            client
                .decode_project_candidates(&vec![rows[0].clone(); 41])
                .await,
            Err(Error::Protocol)
        ));
        assert!(matches!(
            client
                .decode_project_candidates(&[rows[0].clone(), rows[0].clone()])
                .await,
            Err(Error::Protocol)
        ));
    }
}
#[tokio::test]
async fn candidate_authentication_failure_never_returns_already_decrypted_partial_rows() {
    for opaque in [false, true] {
        let client = fixture(opaque, None);
        let first = candidate(PROJECT, "Secret first", Some("Private summary"));
        let mut second = candidate(SECOND, "Second", None);
        second["encrypted_project_key"] =
            json!(crypto::server_fields::encrypt_bytes(&[8; 32], &[9; 32], &[]).unwrap());
        assert!(
            client
                .decode_project_candidates(&[first, second])
                .await
                .is_err()
        );
    }
}
#[tokio::test]
async fn pending_second_real_aes_unwrap_refuses_cancel_denial_owner_cancel_and_revocation() {
    for change in 0..4 {
        let gate = Arc::new(Gate {
            entered: Notify::new(),
            release: Notify::new(),
            calls: AtomicUsize::new(0),
            at: 2,
        });
        let client = fixture(true, Some(gate.clone()));
        let rows = vec![
            candidate(PROJECT, "Secret first", Some("Private")),
            candidate(SECOND, "Secret second", None),
        ];
        let operation = client.operation_cancel.clone();
        let authority = client.task_watch_authority.clone();
        let master = client.master_capability().unwrap();
        let mut read = Box::pin(client.decode_project_candidates(&rows));
        tokio::select! {biased;_=&mut read=>panic!("real primitive must wait"),_=gate.entered.notified()=>{}}
        assert_eq!(gate.calls.load(Ordering::SeqCst), 2);
        match change {
            0 => operation.cancel(),
            1 => {
                authority.deny_cached_chat(Some(CHAT)).unwrap();
            }
            2 => authority.cancel.cancel(),
            _ => master.invalidate(),
        }
        gate.release.notify_one();
        assert!(read.await.is_err());
        assert_eq!(client.credential_ack, 0);
    }
}
#[tokio::test]
async fn local_mode_and_scope_owner_generation_key_replacement_refuse_context_release() {
    let mut client = fixture(true, None);
    client.browser_local_read_only = true;
    assert!(matches!(
        client
            .decode_project_candidates(&[candidate(PROJECT, "Hidden", None)])
            .await,
        Err(Error::Unavailable { .. })
    ));
    for change in 0..3 {
        let mut client = fixture(true, None);
        let scope = AsyncCryptoScope::begin(&client).unwrap();
        match change {
            0 => client.generation += 1,
            1 => client.user["username"] = json!("Replaced"),
            _ => {
                client.browser_credentials.as_mut().unwrap().master =
                    MasterCapability::opaque_for_test(Arc::new(AesPort { gate: None }))
            }
        }
        assert!(scope.check(&client).is_err());
    }
}
#[test]
fn discarded_context_json_recursively_wipes_strings_arrays_and_keys() {
    let mut values = ContextValues(vec![
        json!({"private-key":["Private document",{"nested":"Private summary"}]}),
    ]);
    values.wipe();
    assert_eq!(values.0, vec![Value::Null]);
    let mut value = ContextValue(json!({"document":"Private"}));
    crate::model::zeroize_json(&mut value.0);
    assert!(value.is_null());
}
fn project_row() -> Value {
    json!({"project_id":PROJECT,"encrypted_project_key":crypto::server_fields::encrypt_bytes(&[8;32],&[7;32],&[]).unwrap()})
}
fn folder_detail() -> Value {
    json!({"project":project_row(),"items":[],"folders":[{"folder_id":"folder","updated_at":1,"encrypted_name":crypto::encrypt_combined("Folder title",&[8;32]).unwrap(),"encrypted_description":crypto::encrypt_combined("Private folder document",&[8;32]).unwrap()}]})
}
#[tokio::test]
async fn catalog_preserves_exact_focus_path_filter_bounds_and_archived_refusal() {
    let mut items = vec![];
    for index in 0..22 {
        items.push(json!({"item_type":"embed","target_id_hash":"hash","project_item_id":format!("item{index}"),"encrypted_metadata":crypto::encrypt_combined(&json!({"display_path":format!(".openmates/focuses/focus{index}/SKILL.md"),"focus_title":"Δ".repeat(200),"focus_description":"Private","focus_when_to_use":"Use"}).to_string(),&[8;32]).unwrap()}));
    }
    items.insert(0,json!({"item_type":"embed","target_id_hash":"hash","project_item_id":"bad","encrypted_metadata":crypto::encrypt_combined(r#"{"display_path":".openmates/focuses/../SKILL.md"}"#,&[8;32]).unwrap()}));
    let mut archived = project_row();
    archived["archived"] = json!(true);
    let (api, server) = mock(vec![
        json!({"project":project_row(),"items":items}),
        json!({"project":archived,"items":[]}),
    ])
    .await;
    let mut client = client(&api);
    let out = client.project_routing_catalog(PROJECT).await.unwrap();
    assert_eq!(out.len(), 20);
    assert_eq!(out[0]["item_id"], "item0");
    assert_eq!(out[0]["title"], "Δ".repeat(180));
    assert!(matches!(
        client.project_routing_catalog(PROJECT).await,
        Err(Error::Forbidden)
    ));
    assert_eq!(server.await.unwrap().len(), 2);
}
#[tokio::test]
async fn active_folder_context_preserves_selection_revision_and_final_owner_scope() {
    let active = json!({"project_id":PROJECT,"focus_id":"focus","team_id":null});
    let detail = folder_detail();
    let rev = revision(&detail["folders"][0]);
    let (api, server) = mock(vec![
        json!({"focus":active}),
        detail.clone(),
        json!({"selected":[{"kind":"folder","id":"folder","revision":rev}]}),
        json!({"focus":active}),
        json!({"focus":active}),
        detail,
    ])
    .await;
    let mut client = client(&api);
    let out = client
        .active_project_context(CHAT, "Select context")
        .await
        .unwrap();
    assert_eq!(
        out["project_context_documents"][0]["document"],
        "Private folder document"
    );
    assert_eq!(out["project_context_documents"][0]["revision"], rev);
    assert_eq!(out["active_focus_id"], "focus");
    assert_eq!(client.credential_ack, 0);
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 6);
    assert!(requests[2].starts_with("POST "));
    let body: Value = serde_json::from_str(requests[2].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(body["candidates"].as_array().unwrap().len(), 1);
    assert_eq!(body["chat_id"], CHAT);
}

#[tokio::test]
async fn actual_document_read_keeps_project_wrapper_and_child_om_toon_semantics() {
    let content = json!({"markdown":"Private actual document Δ"});
    let data = json!({"embed_keys":[{"key_type":"project","encrypted_embed_key":crypto::encrypt_bytes(&[9;32],&[8;32]).unwrap()}],"embed":{"encrypted_content":crypto::encrypt_combined(&content.to_string(),&[9;32]).unwrap()}});
    let mut wrong = data.clone();
    wrong["embed_keys"][0]["key_type"] = json!("master");
    let (api, server) = mock(vec![data, wrong]).await;
    let mut client = client(&api);
    assert_eq!(
        client
            .read_project_document(PROJECT, SECOND, &[8; 32])
            .await
            .unwrap(),
        content
    );
    assert!(matches!(
        client
            .read_project_document(PROJECT, SECOND, &[8; 32])
            .await,
        Err(Error::Forbidden)
    ));
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 2);
    assert!(requests.iter().all(|r| r.starts_with(&format!(
        "GET /v1/embeds/{SECOND}/encrypted?project_id={PROJECT} "
    ))));
}

// Bounded inert transport fixture, no product server or automatic credentials.
fn client(api: &str) -> Client {
    Client::new(
        api,
        Some(Session {
            api_url: api.into(),
            session_id: "synthetic-context".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "synthetic-context".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}
async fn mock(responses: Vec<Value>) -> (String, tokio::task::JoinHandle<Vec<String>>) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let mut requests = vec![];
        for response in responses {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = vec![];
            loop {
                let mut chunk = [0; 4096];
                let count = socket.read(&mut chunk).await.unwrap();
                assert!(count > 0 && bytes.len() + count <= 65536);
                bytes.extend_from_slice(&chunk[..count]);
                if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&bytes[..end]).to_ascii_lowercase();
                    let length = headers
                        .lines()
                        .find_map(|line| {
                            line.strip_prefix("content-length:")
                                .map(|v| v.trim().parse::<usize>().unwrap())
                        })
                        .unwrap_or(0);
                    if bytes.len() >= end + 4 + length {
                        break;
                    }
                }
            }
            requests.push(String::from_utf8(bytes).unwrap());
            let body = response.to_string();
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        }
        requests
    });
    (api, server)
}

#[test]
fn revision_retain_preserves_order_and_kept_values_without_discarded_documents() {
    let mut values = ContextValues(vec![
        json!({"id":"first","document":"private first"}),
        json!({"id":"removed","document":"private removed"}),
        json!({"id":"last","document":"private last"}),
    ]);
    values.retain(|value| value["id"] != "removed");
    assert_eq!(values.len(), 2);
    assert_eq!(values[0]["id"], "first");
    assert_eq!(values[1]["id"], "last");
    assert!(values.iter().all(|value| value["id"] != "removed"));
}

fn memory_item(item: &str, path: &str, embed: &str) -> Value {
    json!({"item_type":"embed","project_item_id":item,"updated_at":1,"target_id_hash":"hash","deleted_target_state":null,
        "encrypted_metadata":crypto::encrypt_combined(&json!({"path":path}).to_string(),&[8;32]).unwrap(),
        "target_id_encrypted":crypto::encrypt_combined(embed,&[8;32]).unwrap()})
}
fn memory_embed(document: &str) -> Value {
    json!({"embed_keys":[{"key_type":"project","encrypted_embed_key":crypto::encrypt_bytes(&[9;32],&[8;32]).unwrap()}],
        "embed":{"encrypted_content":crypto::encrypt_combined(&json!({"content":document}).to_string(),&[9;32]).unwrap()}})
}
#[tokio::test]
async fn active_project_sends_every_current_project_memory_as_custom_memory_document() {
    let style = "---\ntitle: Press style\nload_mode: auto_include\n---\nExample Solar GmbH, about 3,000 customers.\n";
    let expired = "---\ntitle: Trip\nvalid_until: 2020-01-01\n---\nIn Rome.\n";
    let active = json!({"project_id":PROJECT,"focus_id":"focus","team_id":null});
    let detail = json!({"project":project_row(),"folders":[],"items":[
        memory_item("style", ".openmates/memories/press-style.md", "embed-style"),
        memory_item("trip", ".openmates/memories/old-trip.md", "embed-trip"),
    ]});
    let rev = revision(&detail["items"][0]);
    let (api, server) = mock(vec![
        json!({"focus":active}),
        detail.clone(),
        json!({"focus":active}),
        memory_embed(expired),
        memory_embed(style),
        json!({"focus":active}),
        detail,
    ])
    .await;
    let mut client = client(&api);
    let out = client.active_project_context(CHAT, "Write a press release").await.unwrap();
    let docs = out["custom_memory_documents"].as_array().unwrap();
    assert_eq!(docs.len(), 1);
    assert_eq!(docs[0]["id"], "style");
    assert_eq!(docs[0]["source"], "project");
    assert_eq!(docs[0]["project_id"], PROJECT);
    assert_eq!(docs[0]["document"], style);
    assert_eq!(docs[0]["item_revision"], rev);
    // Memories are sent whole, never offered to relevance selection.
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 7);
    assert!(requests.iter().all(|r| !r.contains("/context/select")));
}
#[tokio::test]
async fn project_memory_changed_during_send_is_dropped_by_the_revision_check() {
    let style = "---\ntitle: Press style\n---\nTone: plain.\n";
    let active = json!({"project_id":PROJECT,"focus_id":"focus","team_id":null});
    let detail = json!({"project":project_row(),"folders":[],"items":[memory_item("style", ".openmates/memories/press-style.md", "embed-style")]});
    let mut changed = detail.clone();
    changed["items"][0]["updated_at"] = json!(2);
    let (api, server) = mock(vec![
        json!({"focus":active}), detail, json!({"focus":active}), memory_embed(style), json!({"focus":active}), changed,
    ])
    .await;
    let mut client = client(&api);
    let out = client.active_project_context(CHAT, "Write").await.unwrap();
    assert!(out["custom_memory_documents"].as_array().unwrap().is_empty());
    assert_eq!(server.await.unwrap().len(), 6);
}
