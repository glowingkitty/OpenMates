// contract-test: supporting surface=cli assertions=workflows.chat-delivery.claim-fenced,workflows.chat-delivery.client-encrypted,workflows.chat-delivery.pending-private
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio::net::TcpStream;
use tokio_tungstenite::{WebSocketStream, tungstenite::Message as WsMessage};
const DELIVERY: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const MESSAGE: &str = "33333333-3333-4333-8333-333333333333";
const WORKFLOW: &str = "44444444-4444-4444-8444-444444444444";
const RUN: &str = "55555555-5555-4555-8555-555555555555";
const EMBED: &str = "66666666-6666-4666-8666-666666666666";
fn client() -> Client {
    let mut client = Client::new(
        "https://api.example.org",
        Some(Session {
            api_url: "https://api.example.org".into(),
            session_id: "fixture".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "fixture".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap();
    client.user = json!({"id":"77777777-7777-4777-8777-777777777777"});
    client
}
fn row() -> Value {
    json!({"delivery_id":DELIVERY,"chat_id":CHAT,"message_id":MESSAGE,"status":"delivery_pending","workflow_id":WORKFLOW,"run_id":RUN})
}
fn deliveries() -> BTreeMap<String, WorkflowDelivery> {
    let mut rows = BTreeMap::new();
    capture(
        "workflow_chat_deliveries_available",
        &json!({"deliveries":[row()]}),
        &mut rows,
    )
    .unwrap();
    rows
}
fn claim() -> Value {
    let now = now_ms() / 1000;
    let mut value = row();
    value["status"] = json!("claimed");
    value["claim_token"] = json!("opaque-claim-token");
    value["claim_generation"] = json!(2);
    value["claim_issued_at"] = json!(now);
    value["claim_expires_at"] = json!(now + 60);
    value["client_persisted"] = json!(false);
    value["existing_chat"] = Value::Null;
    value["created_at"] = json!(now);
    value["title"] = json!("Private workflow title");
    value["message"] = json!("Private workflow message");
    value["embeds"] = json!([{"embed_id":EMBED,"content_type":"web-search","content":{"title":"Private result","url":"https://example.org/private"}}]);
    value
}
async fn sockets() -> (Socket, WebSocketStream<TcpStream>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let accepted = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        tokio_tungstenite::accept_async(stream).await.unwrap()
    });
    let (stream, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
        .await
        .unwrap();
    (transport::test_socket(stream), accepted.await.unwrap())
}
async fn receive(ws: &mut WebSocketStream<TcpStream>) -> Value {
    let value = ws.next().await.unwrap().unwrap();
    serde_json::from_str(value.to_text().unwrap()).unwrap()
}
async fn reply(
    ws: &mut WebSocketStream<TcpStream>,
    kind: &str,
    request: &Value,
    mut payload: Value,
) {
    payload["request_id"] = request["payload"]["request_id"].clone();
    ws.send(WsMessage::Text(
        json!({"type":kind,"payload":payload}).to_string().into(),
    ))
    .await
    .unwrap();
}
#[test]
fn private_ciphertext_has_fresh_chat_and_embed_keys_and_no_private_wire_fields() {
    let claim = claim();
    let (metadata, message) = encrypt_claim(&claim, &[7; 32]).unwrap();
    let key = key_from_bytes(
        &crypto::decrypt_bytes(metadata["encrypted_chat_key"].as_str().unwrap(), &[7; 32]).unwrap(),
    )
    .unwrap();
    assert_ne!(*key, [7; 32]);
    assert_eq!(
        crypto::decrypt_combined(message["encrypted_content"].as_str().unwrap(), &key).unwrap(),
        "Private workflow message"
    );
    assert!(!json!([metadata, message]).to_string().contains("Private"));
    let embed = &message["embeds"][0];
    let master = crypto::decrypt_bytes(
        embed["embed_keys"][0]["encrypted_embed_key"]
            .as_str()
            .unwrap(),
        &[7; 32],
    )
    .unwrap();
    let chat = crypto::decrypt_bytes(
        embed["embed_keys"][1]["encrypted_embed_key"]
            .as_str()
            .unwrap(),
        &key,
    )
    .unwrap();
    assert_eq!(*master, *chat);
    let embed_key = key_from_bytes(&master).unwrap();
    let content =
        crypto::decrypt_combined(embed["encrypted_content"].as_str().unwrap(), &embed_key).unwrap();
    assert_eq!(
        super::super::toon::decode(&content).unwrap()["title"],
        "Private result"
    );
    assert_eq!(
        message
            .as_object()
            .unwrap()
            .keys()
            .cloned()
            .collect::<Vec<_>>(),
        vec!["created_at", "embeds", "encrypted_content", "role"]
    );
}
#[test]
fn destination_keys_duplicates_and_claim_fences_fail_closed() {
    let original = claim();
    let delivery = WorkflowDelivery::parse(&row()).unwrap();
    for field in [
        "delivery_id",
        "chat_id",
        "message_id",
        "workflow_id",
        "run_id",
    ] {
        let mut wrong = original.clone();
        wrong[field] = json!(EMBED);
        assert!(matches!(
            validate_claim(&delivery, &wrong, now_ms() / 1000),
            Err(Error::Forbidden)
        ));
    }
    let mut expired = original.clone();
    expired["claim_expires_at"] = json!(now_ms() / 1000);
    assert!(validate_claim(&delivery, &expired, now_ms() / 1000).is_err());
    let mut missing = original.clone();
    missing.as_object_mut().unwrap().remove("existing_chat");
    assert!(encrypt_claim(&missing, &[7; 32]).is_err());
    let mut bad = original.clone();
    bad["existing_chat"] = json!({"encrypted_chat_key":"not-ciphertext"});
    assert!(encrypt_claim(&bad, &[7; 32]).is_err());
    let mut duplicate = original;
    let embed = duplicate["embeds"][0].clone();
    duplicate["embeds"].as_array_mut().unwrap().push(embed);
    assert!(encrypt_claim(&duplicate, &[7; 32]).is_err());
}
#[test]
fn partial_broadcasts_merge_known_identity_and_reject_conflicting_destinations() {
    let mut rows = deliveries();
    let mut partial = row();
    partial.as_object_mut().unwrap().remove("workflow_id");
    partial.as_object_mut().unwrap().remove("run_id");
    capture(
        "workflow_chat_deliveries_available",
        &json!({"deliveries":[partial]}),
        &mut rows,
    )
    .unwrap();
    assert_eq!(rows[DELIVERY].workflow.as_deref(), Some(WORKFLOW));
    let mut wrong = row();
    wrong["message_id"] = json!(EMBED);
    assert!(
        capture(
            "workflow_chat_deliveries_available",
            &json!({"deliveries":[wrong]}),
            &mut rows
        )
        .is_err()
    );
}
#[tokio::test]
async fn persistence_precedes_ack_and_cancellation_after_commit_still_acknowledges() {
    let (mut ws, mut server) = sockets().await;
    let parent = CancellationToken::new();
    let remote_cancel = parent.clone();
    let task = tokio::spawn(async move {
        let request = receive(&mut server).await;
        assert_eq!(request["type"], "workflow_chat_delivery_claim");
        let mut state = claim();
        let mut stale = request.clone();
        stale["payload"]["request_id"] = json!("old-request");
        reply(
            &mut server,
            "workflow_chat_delivery_claimed",
            &stale,
            state.clone(),
        )
        .await;
        reply(
            &mut server,
            "workflow_chat_delivery_claimed",
            &request,
            state.clone(),
        )
        .await;
        let persist = receive(&mut server).await;
        assert_eq!(persist["type"], "workflow_chat_delivery_persist");
        assert!(!persist.to_string().contains("Private"));
        assert_eq!(persist["payload"]["claim_generation"], 2);
        remote_cancel.cancel();
        state["client_persisted"] = json!(true);
        reply(
            &mut server,
            "workflow_chat_delivery_persisted",
            &persist,
            state.clone(),
        )
        .await;
        let ack = receive(&mut server).await;
        assert_eq!(ack["type"], "workflow_chat_delivery_ack");
        state["status"] = json!("acknowledged");
        reply(
            &mut server,
            "workflow_chat_delivery_acknowledged",
            &ack,
            state,
        )
        .await;
    });
    let mut client = client();
    client.set_operation_cancel(parent);
    assert_eq!(
        client
            .persist_workflow_deliveries(&mut ws, &deliveries())
            .await
            .unwrap(),
        1
    );
    task.await.unwrap();
}
#[tokio::test]
async fn existing_destination_key_and_metadata_are_never_replaced() {
    let (mut ws, mut server) = sockets().await;
    let original_wrapper = crypto::encrypt_bytes(&[9; 32], &[7; 32]).unwrap();
    let expected = original_wrapper.clone();
    let task = tokio::spawn(async move {
        let request = receive(&mut server).await;
        let mut state = claim();
        state["existing_chat"] = json!({"encrypted_chat_key":expected,"encrypted_title":crypto::encrypt_combined("Existing title",&[9;32]).unwrap(),"encrypted_category":crypto::encrypt_combined("existing",&[9;32]).unwrap(),"created_at":100,"messages_v":4,"title_v":3});
        reply(
            &mut server,
            "workflow_chat_delivery_claimed",
            &request,
            state.clone(),
        )
        .await;
        let persist = receive(&mut server).await;
        let metadata: Value = serde_json::from_str(
            persist["payload"]["encrypted_chat_metadata"]
                .as_str()
                .unwrap(),
        )
        .unwrap();
        assert_eq!(
            metadata["encrypted_chat_key"],
            state["existing_chat"]["encrypted_chat_key"]
        );
        assert_eq!(metadata["messages_v"], 5);
        assert_eq!(metadata["created_at"], 100);
        let message: Value =
            serde_json::from_str(persist["payload"]["encrypted_message"].as_str().unwrap())
                .unwrap();
        assert_eq!(
            crypto::decrypt_combined(message["encrypted_content"].as_str().unwrap(), &[9; 32])
                .unwrap(),
            "Private workflow message"
        );
        state["client_persisted"] = json!(true);
        reply(
            &mut server,
            "workflow_chat_delivery_persisted",
            &persist,
            state.clone(),
        )
        .await;
        let ack = receive(&mut server).await;
        state["status"] = json!("acknowledged");
        reply(
            &mut server,
            "workflow_chat_delivery_acknowledged",
            &ack,
            state,
        )
        .await;
    });
    assert_eq!(
        client()
            .persist_workflow_deliveries(&mut ws, &deliveries())
            .await
            .unwrap(),
        1
    );
    task.await.unwrap();
    assert!(!original_wrapper.is_empty());
}
#[tokio::test]
async fn persisted_claim_recovery_only_acknowledges_without_reencrypting() {
    let (mut ws, mut server) = sockets().await;
    let task = tokio::spawn(async move {
        let request = receive(&mut server).await;
        let mut state = claim();
        state["client_persisted"] = json!(true);
        for key in ["existing_chat", "embeds", "title", "message"] {
            state.as_object_mut().unwrap().remove(key);
        }
        reply(
            &mut server,
            "workflow_chat_delivery_claimed",
            &request,
            state.clone(),
        )
        .await;
        let ack = receive(&mut server).await;
        assert_eq!(ack["type"], "workflow_chat_delivery_ack");
        state["status"] = json!("acknowledged");
        reply(
            &mut server,
            "workflow_chat_delivery_acknowledged",
            &ack,
            state,
        )
        .await;
    });
    assert_eq!(
        client()
            .persist_workflow_deliveries(&mut ws, &deliveries())
            .await
            .unwrap(),
        1
    );
    task.await.unwrap();
}
#[tokio::test]
async fn active_foreign_lease_and_team_context_never_claim() {
    let (mut ws, mut server) = sockets().await;
    let mut active = row();
    active["status"] = json!("claimed");
    active["claim_expires_at"] = json!(now_ms() / 1000 + 60);
    let mut rows = deliveries();
    rows.insert(DELIVERY.into(), WorkflowDelivery::parse(&active).unwrap());
    let mut client = client();
    assert_eq!(
        client
            .persist_workflow_deliveries(&mut ws, &rows)
            .await
            .unwrap(),
        0
    );
    client.set_team(Some(WORKFLOW)).unwrap();
    assert_eq!(
        client
            .persist_workflow_deliveries(&mut ws, &deliveries())
            .await
            .unwrap(),
        0
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(20), server.next())
            .await
            .is_err()
    );
}
#[tokio::test]
async fn stale_generation_receipt_cannot_ack() {
    let (mut ws, mut server) = sockets().await;
    let task = tokio::spawn(async move {
        let request = receive(&mut server).await;
        let mut state = claim();
        reply(
            &mut server,
            "workflow_chat_delivery_claimed",
            &request,
            state.clone(),
        )
        .await;
        let persist = receive(&mut server).await;
        state["client_persisted"] = json!(true);
        state["claim_generation"] = json!(1);
        reply(
            &mut server,
            "workflow_chat_delivery_persisted",
            &persist,
            state,
        )
        .await;
        assert!(
            tokio::time::timeout(Duration::from_millis(30), server.next())
                .await
                .is_err()
        );
    });
    assert_eq!(
        client()
            .persist_workflow_deliveries(&mut ws, &deliveries())
            .await,
        Err(Error::Conflict)
    );
    task.await.unwrap();
}
#[tokio::test]
async fn correlated_claim_contention_is_deferred_but_other_delivery_error_is_rejected() {
    for wrong in [false, true] {
        let (mut ws, mut server) = sockets().await;
        let task = tokio::spawn(async move {
            let request = receive(&mut server).await;
            let rejected = json!({"code":"workflow_chat_delivery_rejected","reason":"WorkflowChatDeliveryStateError","delivery_id":if wrong{CHAT}else{DELIVERY}});
            reply(&mut server, "error", &request, rejected).await;
        });
        let result = client()
            .persist_workflow_deliveries(&mut ws, &deliveries())
            .await;
        if wrong {
            assert_eq!(result, Err(Error::Forbidden));
        } else {
            assert_eq!(result.unwrap(), 0);
        }
        task.await.unwrap();
    }
}

#[tokio::test]
async fn lost_persist_receipt_recovers_under_a_new_lease_without_duplicate_ciphertext() {
    let (mut first, mut first_server) = sockets().await;
    let saved = tokio::spawn(async move {
        let request = receive(&mut first_server).await;
        reply(
            &mut first_server,
            "workflow_chat_delivery_claimed",
            &request,
            claim(),
        )
        .await;
        let persisted = receive(&mut first_server).await;
        assert_eq!(persisted["type"], "workflow_chat_delivery_persist");
        first_server.close(None).await.unwrap();
        persisted
    });
    assert_eq!(
        client()
            .persist_workflow_deliveries(&mut first, &deliveries())
            .await,
        Err(Error::Offline)
    );
    let persisted = saved.await.unwrap();
    let metadata: Value = serde_json::from_str(
        persisted["payload"]["encrypted_chat_metadata"]
            .as_str()
            .unwrap(),
    )
    .unwrap();
    let original_key = key_from_bytes(
        &crypto::decrypt_bytes(metadata["encrypted_chat_key"].as_str().unwrap(), &[7; 32]).unwrap(),
    )
    .unwrap();
    let message: Value =
        serde_json::from_str(persisted["payload"]["encrypted_message"].as_str().unwrap()).unwrap();
    assert_eq!(
        crypto::decrypt_combined(
            message["encrypted_content"].as_str().unwrap(),
            &original_key
        )
        .unwrap(),
        "Private workflow message"
    );
    let (mut second, mut second_server) = sockets().await;
    let recovered = tokio::spawn(async move {
        let request = receive(&mut second_server).await;
        let mut state = claim();
        state["client_persisted"] = json!(true);
        state["claim_generation"] = json!(3);
        state["claim_token"] = json!("fresh-recovery-lease");
        reply(
            &mut second_server,
            "workflow_chat_delivery_claimed",
            &request,
            state.clone(),
        )
        .await;
        let ack = receive(&mut second_server).await;
        assert_eq!(ack["type"], "workflow_chat_delivery_ack");
        assert_eq!(ack["payload"]["claim_generation"], 3);
        assert_eq!(ack["payload"]["claim_token"], "fresh-recovery-lease");
        state["status"] = json!("acknowledged");
        reply(
            &mut second_server,
            "workflow_chat_delivery_acknowledged",
            &ack,
            state,
        )
        .await;
    });
    assert_eq!(
        client()
            .persist_workflow_deliveries(&mut second, &deliveries())
            .await
            .unwrap(),
        1
    );
    recovered.await.unwrap();
}
