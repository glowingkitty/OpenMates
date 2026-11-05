//! Actual shared-helper regressions, authored UNRUN. Synthetic opaque AES port;
//! no product HTTP, browser, WASM, IDB, native credentials or account acceptance.
// contract-test-file: tooling
use super::*;
use crate::crypto::master::{MasterCapability, MasterCrypto, MasterCryptoFuture};
use std::sync::Arc;
use tokio::sync::Notify;
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const MESSAGE: &str = "33333333-3333-4333-8333-333333333333";
struct Gate { entered: Notify, release: Notify }
struct Port { gate: Option<Arc<Gate>> }
impl MasterCrypto for Port {
    fn encrypt<'a>(&'a self, iv: &'a [u8;12], plain: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {crypto::encrypt_aead(plain,&[7;32],iv,&[]).map(zeroize::Zeroizing::new)})
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8;12], cipher: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            if let Some(gate)=&self.gate {gate.entered.notify_one();gate.release.notified().await;}
            crypto::decrypt_aead(cipher,&[7;32],iv,&[])
        })
    }
}
fn client(gate:Option<Arc<Gate>>) -> Client {
    let mut client=Client::new("http://127.0.0.1:9",None).unwrap();
    client.browser_transport=true;
    client.browser_local_read_only=true;
    client.browser_authority=Some(BrowserAuthority{principal:OWNER.into(),persistence:BrowserPersistence::MemoryOnly,owner_guards:false});
    client.user=json!({"id":OWNER});
    client.browser_credentials=Some(credentials::BrowserCredentials{
        api_url:"http://127.0.0.1:9".into(),session_id:OWNER.into(),cookies:BTreeMap::new(),ws_token:None,
        master:MasterCapability::opaque_for_test(Arc::new(Port{gate})),hashed_email:String::new(),user_email_salt:String::new(),
        email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None,
    });
    client
}
fn rows() -> String {
    use base64::Engine;
    let mut wrapper=vec![5;12];wrapper.extend(crypto::encrypt_aead(&[9;32],&[7;32],&[5;12],&[]).unwrap());
    json!({"chat_metadata":{"id":CHAT,"encrypted_chat_key":base64::engine::general_purpose::STANDARD.encode(wrapper),"encrypted_title":crypto::encrypt_combined("Local title",&[9;32]).unwrap()},
        "messages":[{"id":MESSAGE,"chat_id":CHAT,"created_at":1,"role":"user","encrypted_content":crypto::encrypt_combined("Local content",&[9;32]).unwrap()}],
        "wrappers":[],"boundary":null}).to_string()
}
#[tokio::test]
async fn actual_browser_json_helpers_keep_tagged_incomplete_offline_views_without_state_or_ack() {
    let client=client(None);let rows=rows();let snapshot=client.ciphertext_snapshot();
    let window=client.browser_local_message_window_json(OWNER,CHAT,message_window::MessageWindowOptions::default(),&rows).await.unwrap();
    let saved=client.browser_local_saved_chat_read_json(OWNER,CHAT,saved_chat_read::SavedChatReadOptions::default(),&rows).await.unwrap();
    for encoded in [&window,&saved] {
        let value:Value=serde_json::from_str(encoded).unwrap();
        assert_eq!(value["source"],"local_profile");assert_eq!(value["historyComplete"],false);assert_eq!(value["fresh"],false);
        assert_eq!(value["readOnly"],true);assert_eq!(value["chat"]["messages"][0]["content"],"Local content");
        assert_eq!(value["hasMoreBefore"],Value::Null);
    }
    let rich:Value=serde_json::from_str(&saved).unwrap();assert_eq!(rich["pagesRead"],0);assert_eq!(rich["contentMode"],"stored");
    assert!(client.session().is_none()&&client.credential_snapshot().is_none());
    assert_eq!(client.ciphertext_snapshot(),snapshot);assert_eq!(client.credential_ack,0);
}
#[tokio::test]
async fn json_helper_refuses_wrong_owner_known_denial_expiry_mode_and_unknown_fields() {
    for change in 0..6 {
        let mut client=client(None);let mut input=rows();let mut owner=OWNER;
        match change {
            0=>owner=CHAT,1=>client.browser_local_read_only=false,
            2=>client.task_watch_authority.deny_cached_chat(Some(CHAT)).unwrap(),
            3=>client.browser_credentials.as_mut().unwrap().paired_session_expires_at=Some(0),
            4=>client.user=json!({"id":CHAT}),
            _=>{let mut value:Value=serde_json::from_str(&input).unwrap();value["authenticated"]=json!(true);input=value.to_string();},
        }
        assert!(client.browser_local_message_window_json(owner,CHAT,message_window::MessageWindowOptions::default(),&input).await.is_err());
        assert!(client.history.is_empty());assert_eq!(client.credential_ack,0);
    }
}
#[tokio::test]
async fn actual_awaited_json_helper_refuses_revoked_owner_resource_operation_and_negative_ledger() {
    for change in 0..4 {
        let gate=Arc::new(Gate{entered:Notify::new(),release:Notify::new()});
        let client=client(Some(gate.clone()));let input=rows();let snapshot=client.ciphertext_snapshot();
        let mut future=Box::pin(client.browser_local_message_window_json(OWNER,CHAT,message_window::MessageWindowOptions::default(),&input));
        tokio::select!{biased; result=&mut future=>{let _=result;panic!("opaque AES must await actual gate");},_=gate.entered.notified()=>{}}
        match change {
            0=>client.operation_cancel.cancel(),1=>client.task_watch_authority.cancel.cancel(),
            2=>client.master_capability().unwrap().invalidate(),_=>client.task_watch_authority.deny_cached_chat(Some(CHAT)).unwrap(),
        }
        gate.release.notify_one();assert!(future.await.is_err());assert_eq!(client.ciphertext_snapshot(),snapshot);assert_eq!(client.credential_ack,0);
    }
}
#[tokio::test]
async fn dropped_actual_local_json_read_cannot_release_plaintext_or_late_state() {
    let gate=Arc::new(Gate{entered:Notify::new(),release:Notify::new()});
    let client=client(Some(gate.clone()));let input=rows();let snapshot=client.ciphertext_snapshot();
    let mut future=Box::pin(client.browser_local_message_window_json(OWNER,CHAT,message_window::MessageWindowOptions::default(),&input));
    tokio::select!{biased; result=&mut future=>{let _=result;panic!("opaque AES must await actual gate");},_=gate.entered.notified()=>{}}
    drop(future);gate.release.notify_one();assert_eq!(client.ciphertext_snapshot(),snapshot);assert_eq!(client.credential_ack,0);
}
#[test]
fn local_json_final_scope_rejects_owner_generation_key_and_mode_replacement() {
    for change in 0..5 {
        let mut client=client(None);let scope=client.browser_local_read_scope(OWNER,CHAT).unwrap();
        match change {
            0=>client.generation+=1,1=>client.user=json!({"id":CHAT}),
            2=>client.browser_credentials.as_mut().unwrap().master=MasterCapability::opaque_for_test(Arc::new(Port{gate:None})),
            3=>client.browser_authority.as_mut().unwrap().principal=CHAT.into(),_=>client.browser_local_read_only=false,
        }
        assert!(scope.check_chat(&client,CHAT).is_err()||client.browser_local_read_scope(OWNER,CHAT).is_err());
    }
}

#[tokio::test]
async fn public_local_json_entrypoints_reject_all_duplicate_addressing_before_crypto() {
    let valid=rows();let value:Value=serde_json::from_str(&valid).unwrap();
    let metadata=value["chat_metadata"].to_string();let row=value["messages"][0].to_string();
    let cases=[
        // Same values also remain ambiguous framing and must refuse.
        format!("{{\"chat_metadata\":{metadata},{}",&valid[1..]),
        valid.replacen(&metadata,&metadata.replacen("{",&format!("{{\"id\":\"{CHAT}\","),1),1),
        valid.replace("\"boundary\":null","\"boundary\":{\"has_more_before\":false,\"has_more_before\":true}"),
        valid.replacen(&row,&row.replacen("{",&format!("{{\"chat_id\":\"{OWNER}\","),1),1),
        {let mut serialized=value.clone();serialized["messages"]=json!([row.replacen("{",&format!("{{\"id\":\"{OWNER}\","),1)]);serialized.to_string()},
        // Escaped aliases decode to the same key in recursively nested objects.
        valid.replacen(&metadata,&metadata.replacen("{","{\"nested\":{\"id\":1,\"\\u0069d\":2},",1),1),
    ];
    for input in cases {
        let gate=Arc::new(Gate{entered:Notify::new(),release:Notify::new()});
        let client=client(Some(gate.clone()));let snapshot=client.ciphertext_snapshot();
        // Poll actual entrypoint once. Duplicate rejection must be immediately
        // ready, before the held opaque AES primitive can ever be awaited.
        use std::task::{Context,Poll,Wake,Waker};
        struct Noop;impl Wake for Noop {fn wake(self:Arc<Self>) {}}
        let waker=Waker::from(Arc::new(Noop));let mut context=Context::from_waker(&waker);
        let mut window=Box::pin(client.browser_local_message_window_json(OWNER,CHAT,message_window::MessageWindowOptions::default(),&input));
        assert!(matches!(std::future::Future::poll(window.as_mut(),&mut context),Poll::Ready(Err(Error::Protocol))));drop(window);
        let mut saved=Box::pin(client.browser_local_saved_chat_read_json(OWNER,CHAT,saved_chat_read::SavedChatReadOptions::default(),&input));
        assert!(matches!(std::future::Future::poll(saved.as_mut(),&mut context),Poll::Ready(Err(Error::Protocol))));drop(saved);
        assert_eq!(client.ciphertext_snapshot(),snapshot);assert_eq!(client.credential_ack,0);
    }
}
#[test]
fn strict_local_json_preserves_valid_serialized_rows_and_rejects_depth_nodes_and_trailing_data() {
    let mut value:Value=serde_json::from_str(&rows()).unwrap();
    value["messages"]=json!([value["messages"][0].to_string()]);
    assert!(local_json::validate(&value.to_string()).is_ok());
    assert!(local_json::validate(&format!("{}null",value)).is_err());
    assert!(local_json::validate(&format!("{}0{}","[".repeat(34),"]".repeat(34))).is_err());
    assert!(local_json::validate(&format!("[{}]",vec!["null";16384].join(","))).is_err());
}

fn maintained_idb_input() -> Value {
    serde_json::from_str::<Value>(include_str!("../../tests/fixtures/browser-idb-local-window.json")).unwrap()["input"].take()
}
#[tokio::test]
async fn maintained_raw_idb_packet_selects_twenty_in_rust_and_preserves_storage_aliases() {
    let client = client(None);
    let mut input = maintained_idb_input();
    input["compression_checkpoints"] = json!([]);
    // Unselected old ciphertext must not be decrypted to construct the window.
    input["messages"][0]["encrypted_content"] = json!("unselected-not-a-ciphertext");
    let before = client.ciphertext_snapshot();
    let output = client.browser_local_saved_chat_read_json(OWNER, CHAT,
        saved_chat_read::SavedChatReadOptions::default(), &input.to_string()).await.unwrap();
    let output: Value = serde_json::from_str(&output).unwrap();
    assert_eq!(output["chat"]["messages"].as_array().unwrap().len(), 20);
    assert_eq!(output["chat"]["messages"][0]["id"], input["messages"][12]["client_message_id"]);
    assert_eq!(output["messageMetadata"][0]["sourceMessageId"], input["messages"][12]["message_id"]);
    assert_eq!(output["messageMetadata"][0]["clientMessageId"], input["messages"][12]["client_message_id"]);
    assert_eq!(output["startCursor"]["messageId"], input["messages"][12]["message_id"]);
    assert_eq!(output["hasMoreBefore"], true);
    assert_eq!(output["historyComplete"], false);
    assert_eq!(output["fresh"], false);
    assert_eq!(output["pagesRead"], 0);
    assert_eq!(client.ciphertext_snapshot(), before);
    assert_eq!(client.credential_ack, 0);
}
#[tokio::test]
async fn raw_checkpoint_policy_uses_latest_created_and_excludes_timestamp_boundary_ties() {
    let client = client(None);
    let input = maintained_idb_input();
    let output = client.browser_local_message_window_json(OWNER, CHAT,
        message_window::MessageWindowOptions::default(), &input.to_string()).await.unwrap();
    let output: Value = serde_json::from_str(&output).unwrap();
    assert_eq!(output["chat"]["messages"].as_array().unwrap().len(), 10);
    assert_eq!(output["startCursor"]["createdAt"], 111);
    assert_eq!(output["chat"]["messages"][0]["content"], "Synthetic local row 23 Synthetic Person");
    assert_eq!(output["piiRestoration"], "page_local");
    assert_eq!(output["hasMoreBefore"], Value::Null);
    let mut options = message_window::MessageWindowOptions::default();
    options.respect_compression_boundary = false;
    let output = client.browser_local_message_window_json(OWNER, CHAT, options, &input.to_string()).await.unwrap();
    assert_eq!(serde_json::from_str::<Value>(&output).unwrap()["chat"]["messages"].as_array().unwrap().len(), 20);
}
#[tokio::test]
async fn local_storage_cursors_page_duplicate_timestamps_without_uuid_normalization() {
    let client = client(None);
    let mut input = maintained_idb_input(); input["compression_checkpoints"] = json!([]);
    let first = client.browser_local_message_window_json(OWNER, CHAT,
        message_window::MessageWindowOptions::default(), &input.to_string()).await.unwrap();
    let first: Value = serde_json::from_str(&first).unwrap();
    let cursor = serde_json::from_value(first["startCursor"].clone()).unwrap();
    let options = message_window::MessageWindowOptions {direction: message_window::MessageWindowDirection::Before,
        cursor: Some(cursor), ..Default::default()};
    let older = client.browser_local_message_window_json(OWNER, CHAT, options, &input.to_string()).await.unwrap();
    let older: Value = serde_json::from_str(&older).unwrap();
    assert_eq!(older["chat"]["messages"].as_array().unwrap().len(), 12);
    assert_eq!(older["endCursor"]["messageId"], input["messages"][11]["message_id"]);
    let options = message_window::MessageWindowOptions {direction: message_window::MessageWindowDirection::Around,
        anchor_message_id: Some(input["messages"][15]["message_id"].as_str().unwrap().into()), ..Default::default()};
    let around = client.browser_local_message_window_json(OWNER, CHAT, options, &input.to_string()).await.unwrap();
    assert_eq!(serde_json::from_str::<Value>(&around).unwrap()["anchorFound"], true);
}
#[tokio::test]
async fn raw_local_addressing_checkpoint_and_bounds_refuse_before_held_master_crypto() {
    for mutation in 0..10 {
        let mut input = maintained_idb_input();
        match mutation {
            0 => input["messages"][0]["chat_id"] = json!(OWNER),
            1 => input["messages"][1]["message_id"] = input["messages"][0]["message_id"].clone(),
            2 => input["messages"][1]["client_message_id"] = input["messages"][0]["client_message_id"].clone(),
            3 => input["messages"].as_array_mut().unwrap().swap(0,1),
            4 => input["compression_checkpoints"][0]["chat_id"] = json!(OWNER),
            5 => input["compression_checkpoints"][0]["compressed_up_to_timestamp"] = json!(-1),
            6 => input["compression_checkpoints"][1]["id"] = input["compression_checkpoints"][0]["id"].clone(),
            7 => input["boundary"] = json!({"compression_boundary_timestamp":109}),
            8 => input["messages"][0]["message_id"] = json!(""), // empty selector still refuses before crypto
            _ => input["extension"] = json!("x".repeat(256*1024)),
        }
        let gate = Arc::new(Gate{entered:Notify::new(),release:Notify::new()});
        let client = client(Some(gate));
        let encoded = input.to_string();
        let mut future = Box::pin(client.browser_local_message_window_json(OWNER, CHAT,
            message_window::MessageWindowOptions::default(), &encoded));
        use std::task::{Context,Poll,Wake,Waker};
        struct Noop; impl Wake for Noop {fn wake(self:Arc<Self>) {}}
        let waker = Waker::from(Arc::new(Noop)); let mut context = Context::from_waker(&waker);
        assert!(matches!(std::future::Future::poll(future.as_mut(),&mut context),Poll::Ready(Err(_))));
        drop(future); assert_eq!(client.credential_ack,0); assert!(client.history.is_empty());
    }
}
#[tokio::test]
async fn raw_checkpoint_nested_duplicates_and_serialized_rows_are_checked_by_public_entrypoint() {
    let client = client(None);
    let mut input = maintained_idb_input();
    for row in input["messages"].as_array_mut().unwrap() { *row = json!(row.to_string()); }
    let encoded = input.to_string();
    assert!(client.browser_local_message_window_json(OWNER,CHAT,message_window::MessageWindowOptions::default(),&encoded).await.is_ok());
    let malformed = encoded.replacen("\"compressed_message_count\":12", "\"compressed_message_count\":12,\"compressed_message_count\":12",1);
    assert_ne!(encoded,malformed);
    assert!(client.browser_local_message_window_json(OWNER,CHAT,message_window::MessageWindowOptions::default(),&malformed).await.is_err());
}
#[tokio::test]
async fn raw_idb_checkpoint_window_keeps_late_key_denial_and_cancel_fences() {
    for change in 0..3 {
        let gate = Arc::new(Gate{entered:Notify::new(),release:Notify::new()});
        let client = client(Some(gate.clone()));
        let encoded = maintained_idb_input().to_string();
        let snapshot = client.ciphertext_snapshot();
        let mut future = Box::pin(client.browser_local_saved_chat_read_json(OWNER,CHAT,
            saved_chat_read::SavedChatReadOptions::default(),&encoded));
        tokio::select! {biased; value = &mut future => {let _=value; panic!("must await opaque master");}, _=gate.entered.notified()=>{}}
        match change {0=>client.operation_cancel.cancel(),1=>client.master_capability().unwrap().invalidate(),
            _=>client.task_watch_authority.deny_cached_chat(Some(CHAT)).unwrap()}
        gate.release.notify_one(); assert!(future.await.is_err());
        assert_eq!(client.ciphertext_snapshot(),snapshot); assert_eq!(client.credential_ack,0);
    }
}

#[tokio::test]
async fn rich_plaintext_extensions_stay_guarded_for_actual_public_decode_success_and_error() {
    for invalid_cipher in [false,true] {
        let client = client(None);
        let mut input = maintained_idb_input();
        let snapshot = client.ciphertext_snapshot();
        let last = input["messages"].as_array().unwrap().len()-1;
        input["messages"][last]["content"] = json!("PRIVATE_CLEAR_SENTINEL");
        input["messages"][last]["summary"] = json!("PRIVATE_CLEAR_SENTINEL");
        input["messages"][last]["extension"] = json!({"nested":"PRIVATE_CLEAR_SENTINEL"});
        if invalid_cipher {input["messages"][last]["encrypted_content"] = json!("invalid-selected-ciphertext");}
        let encoded = zeroize::Zeroizing::new(input.to_string());
        let result = client.browser_local_saved_chat_read_json(OWNER,CHAT,
            saved_chat_read::SavedChatReadOptions::default(),&encoded).await;
        if invalid_cipher {assert!(result.is_err());}
        else {assert!(!result.unwrap().contains("PRIVATE_CLEAR_SENTINEL"));}
        assert_eq!(client.ciphertext_snapshot(),snapshot);assert_eq!(client.credential_ack,0);
    }
}

#[tokio::test]
async fn former_long_control_unicode_grammar_refusals_now_preserve_local_physical_ids(){
 for id in ["x".repeat(257),"physical \n雪😀e\u{301}".into()] {
  let client=client(None);let mut input=maintained_idb_input();let mut row=input["messages"][0].clone();let cipher=row["encrypted_content"].clone();row["message_id"]=json!(id);
  input["messages"]=json!([row]);input["compression_checkpoints"]=json!([]);input["boundary"]=Value::Null;
  let before=client.ciphertext_snapshot();let encoded=client.browser_local_message_window_json(OWNER,CHAT,message_window::MessageWindowOptions::default(),&input.to_string()).await.unwrap();
  let compact:Value=serde_json::from_str(&encoded).unwrap();assert_eq!(compact["startCursor"]["messageId"],id);
  // The compact window has no metadata DTO; exercise the actual rich entrypoint
  // for physical aliases while retaining compact cursor coverage above.
  let encoded=client.browser_local_saved_chat_read_json(OWNER,CHAT,saved_chat_read::SavedChatReadOptions::default(),&input.to_string()).await.unwrap();
  let out:Value=serde_json::from_str(&encoded).unwrap();assert_eq!(out["startCursor"]["messageId"],id);assert_eq!(out["messageMetadata"][0]["sourceMessageId"],id);assert_eq!(input["messages"][0]["encrypted_content"],cipher);
  assert_eq!(client.ciphertext_snapshot(),before);assert_eq!(client.credential_ack,0);assert!(client.history.is_empty());
 }
}
