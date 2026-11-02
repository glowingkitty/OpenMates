//! Synthetic full send-on-socket regressions for canonical discovery ordering.
//! The local peer never connects to a product backend or inference provider.
//! It independently seals a current-job completion and observes real claim and
//! persistence frames; no marker is treated as main-completion authority.
//! Negative cases retain current-turn, owner, chat, assistant, key and ACK fences.
//! Draft tests require actual SDK compilation/execution in isolated CI.
// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use aes_gcm::{
    Aes256Gcm, KeyInit, Nonce,
    aead::{Aead, Payload},
};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use futures_util::{SinkExt, StreamExt};
use sha2::{Digest, Sha256};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message as Frame;
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const TURN: &str = "33333333-3333-4333-8333-333333333333";
const JOB: &str = "44444444-4444-4444-8444-444444444444";
const ASSISTANT: &str = "55555555-5555-4555-8555-555555555555";
const USER: &str = "66666666-6666-4666-8666-666666666666";
const FOREIGN: &str = "77777777-7777-4777-8777-777777777777";
const ANSWER: &str = "Canonical sealed answer";
const KEY: [u8; 32] = [9; 32];
#[derive(Clone, Copy)]
enum Case {
    Before,
    After,
    NoFinal,
    WrongFinal,
    WrongFinalProtocol,
    WrongFinalAssistant,
    WrongClaimChat,
    WrongClaimTurn,
    WrongClaimAssistant,
    WrongClaimKey,
    WrongSealOwner,
    WrongSealJob,
    NoPersistAck,
    FailedMarker,
    FailedAfterFinal,
}
fn sealed(case: Case) -> Value {
    let identity = crypto::RecoveryIdentity {
        owner_id: if matches!(case, Case::WrongSealOwner) {
            FOREIGN
        } else {
            OWNER
        }
        .into(),
        chat_id: CHAT.into(),
        turn_id: TURN.into(),
        job_id: if matches!(case, Case::WrongSealJob) {
            FOREIGN
        } else {
            JOB
        }
        .into(),
        assistant_message_id: ASSISTANT.into(),
        key_version: 1,
    };
    let plain =
        json!({"assistant_message_id":ASSISTANT,"category":null,"chat_id":CHAT,"content":ANSWER,
        "job_id":identity.job_id,"key_version":1,"model_name":null,"turn_id":TURN})
        .to_string();
    let recipient = crypto::recovery_keypair(&KEY, CHAT, 1).unwrap();
    let public: [u8; 32] = crypto::decode_url(&recipient.public_key, 32)
        .unwrap()
        .as_slice()
        .try_into()
        .unwrap();
    let secret = x25519_dalek::StaticSecret::from([21; 32]);
    let ephemeral = x25519_dalek::PublicKey::from(&secret);
    let shared = secret.diffie_hellman(&x25519_dalek::PublicKey::from(public));
    let aad = crypto::recovery_associated_data(&identity).unwrap();
    let envelope_key = crypto::hkdf_sha256(
        shared.as_bytes(),
        &Sha256::digest(b"openmates:chat-recovery-envelope:v1"),
        &Sha256::digest(&aad),
    )
    .unwrap();
    let nonce = [8; 12];
    let ciphertext = Aes256Gcm::new_from_slice(envelope_key.as_ref())
        .unwrap()
        .encrypt(
            Nonce::from_slice(&nonce),
            Payload {
                msg: plain.as_bytes(),
                aad: &aad,
            },
        )
        .unwrap();
    json!({"v":1,"epk":URL_SAFE_NO_PAD.encode(ephemeral.as_bytes()),"nonce":URL_SAFE_NO_PAD.encode(nonce),"ciphertext":URL_SAFE_NO_PAD.encode(ciphertext)})
}
async fn next(ws: &mut tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>) -> Value {
    serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap()).unwrap()
}
async fn emit(
    ws: &mut tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>,
    kind: &str,
    payload: Value,
) {
    ws.send(Frame::Text(
        json!({"type":kind,"payload":payload}).to_string().into(),
    ))
    .await
    .unwrap();
}
async fn case(case: Case) -> Result<SendOutcome> {
    let http = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", http.local_addr().unwrap());
    let wrapped = crypto::encrypt_bytes(&KEY, &[7; 32]).unwrap();
    let metadata_wrapped = wrapped.clone();
    let metadata = tokio::spawn(async move {
        let (mut stream, _) = http.accept().await.unwrap();
        let mut bytes = vec![];
        let mut chunk = [0; 2048];
        loop {
            let n = stream.read(&mut chunk).await.unwrap();
            assert!(n > 0);
            bytes.extend_from_slice(&chunk[..n]);
            if let Some(end) = bytes.windows(4).position(|x| x == b"\r\n\r\n") {
                let headers = std::str::from_utf8(&bytes[..end]).unwrap();
                let length = headers
                    .lines()
                    .find_map(|line| {
                        line.to_ascii_lowercase()
                            .strip_prefix("content-length:")
                            .map(|n| n.trim().parse::<usize>().unwrap())
                    })
                    .unwrap_or(0);
                if bytes.len() >= end + 4 + length {
                    break;
                }
            }
        }
        assert!(bytes.starts_with(b"POST /v1/chats/metadata/batch HTTP/1.1\r\n"));
        let body =
            json!({"chats":[{"id":CHAT,"messages_v":1,"encrypted_chat_key":metadata_wrapped}]})
                .to_string();
        stream.write_all(format!("HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let peer = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        assert_eq!(next(&mut ws).await["type"], "set_active_chat");
        let context = next(&mut ws).await;
        assert_eq!(context["type"], "personal_send_context_snapshot");
        emit(&mut ws,"personal_send_context_snapshot_result",json!({"request_id":context["payload"]["request_id"],
            "success":true,"unchanged":false,"turn_id":TURN,"receipt_id":"synthetic-receipt","privacy_generation":1,
            "project_candidates":[],"personal_memories":{"memories":[]}})).await;
        let admitted = next(&mut ws).await;
        assert_eq!(admitted["type"], "chat_turn_admit");
        assert_eq!(admitted["payload"]["chat_id"], CHAT);
        assert_eq!(admitted["payload"]["turn_id"], TURN);
        emit(
            &mut ws,
            "chat_turn_preflight_ack",
            json!({"turn_id":TURN,"preflight_id":"synthetic-preflight","committed_messages_v":1}),
        )
        .await;
        emit(
            &mut ws,
            "chat_message_confirmed",
            json!({"chat_id":CHAT,"message_id":USER,"new_messages_v":1}),
        )
        .await;
        // An unrelated earlier global marker cannot itself cause a claim.
        emit(
            &mut ws,
            "recovery_outputs_discovery_complete",
            json!({"status":"completed"}),
        )
        .await;
        if matches!(case, Case::NoFinal | Case::WrongFinal) {
            if matches!(case, Case::WrongFinal) {
                emit(&mut ws,"ai_message_update",json!({"chat_id":CHAT,"user_message_id":USER,"recovery_turn_id":FOREIGN,
                    "message_id":ASSISTANT,"recovery_job_id":JOB,"recovery_protocol_version":1,"created_at":1,
                    "full_content_so_far":ANSWER,"is_final_chunk":true})).await;
            }
            assert!(matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)));
            return;
        }
        if matches!(case, Case::FailedMarker) {
            emit(
                &mut ws,
                "recovery_outputs_discovery_complete",
                json!({"status":"failed"}),
            )
            .await;
            assert!(matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)));
            return;
        }
        emit(&mut ws,"ai_message_update",json!({"chat_id":CHAT,"user_message_id":USER,"recovery_turn_id":TURN,
            "message_id":if matches!(case,Case::WrongFinalAssistant){FOREIGN}else{ASSISTANT},"recovery_job_id":JOB,"recovery_protocol_version":if matches!(case,Case::WrongFinalProtocol){2}else{1},"created_at":1,
            "full_content_so_far":ANSWER,"is_final_chunk":true})).await;
        if matches!(case, Case::WrongFinalProtocol) {
            assert!(matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)));
            return;
        }
        if matches!(case, Case::FailedAfterFinal) {
            emit(
                &mut ws,
                "recovery_outputs_discovery_complete",
                json!({"status":"failed"}),
            )
            .await;
            assert!(matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)));
            return;
        }
        if matches!(case, Case::After) {
            emit(
                &mut ws,
                "recovery_outputs_discovery_complete",
                json!({"status":"completed"}),
            )
            .await;
        }
        let claim = next(&mut ws).await;
        assert_eq!(claim["type"], "recovery_job_claim");
        assert_eq!(claim["payload"]["job_id"], JOB);
        let mut response = json!({"job_id":JOB,"chat_id":CHAT,"turn_id":TURN,"assistant_message_id":ASSISTANT,"chat_key_version":1,
            "state":"LEASED","lease_generation":1,"lease_token":"synthetic-token","sealed_payload":sealed(case).to_string()});
        match case {
            Case::WrongClaimChat => response["chat_id"] = json!(FOREIGN),
            Case::WrongClaimTurn => response["turn_id"] = json!(FOREIGN),
            Case::WrongClaimAssistant => response["assistant_message_id"] = json!(FOREIGN),
            Case::WrongClaimKey => response["chat_key_version"] = json!(2),
            _ => {}
        }
        emit(&mut ws, "recovery_job_claimed", response).await;
        if matches!(
            case,
            Case::WrongFinalAssistant
                | Case::WrongClaimChat
                | Case::WrongClaimTurn
                | Case::WrongClaimAssistant
                | Case::WrongClaimKey
                | Case::WrongSealOwner
                | Case::WrongSealJob
        ) {
            assert!(matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)));
            return;
        }
        let persist = next(&mut ws).await;
        assert_eq!(persist["type"], "recovery_job_persist");
        assert_eq!(persist["payload"]["job_id"], JOB);
        assert_eq!(persist["payload"]["expected_messages_v"], 1);
        let ciphertext = required(
            &persist["payload"]["encrypted_assistant_message"],
            "encrypted_content",
        )
        .unwrap();
        assert_eq!(crypto::decrypt_combined(ciphertext, &KEY).unwrap(), ANSWER);
        if matches!(case, Case::NoPersistAck) {
            ws.close(None).await.unwrap();
            return;
        }
        emit(
            &mut ws,
            "recovery_job_persisted",
            json!({"job_id":JOB,"state":"TERMINAL","committed_messages_v":2}),
        )
        .await;
        assert!(matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)));
    });
    let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
        .await
        .unwrap();
    let mut socket = transport::test_socket(inner);
    let session = crate::session::Session {
        api_url: api.clone(),
        session_id: USER.into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: String::new(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new(&api, Some(session)).unwrap();
    client.user = json!({"id":OWNER});
    let mut chat = Chat {
        id: CHAT.into(),
        ..Default::default()
    };
    let (updates, mut receiver) = mpsc::channel(64);
    let options = SendOptions {
        pii_detection: false,
        task_update_jobs: false,
        response_timeout_ms: Some(2_000),
        ..Default::default()
    };
    let generation = client.generation;
    let mut trace = SendTrace::new();
    let result = client
        .send_on_socket(
            &mut socket,
            CHAT,
            TURN,
            USER,
            "synthetic input",
            &KEY,
            &wrapped,
            0,
            true,
            &[],
            &mut chat,
            &updates,
            &CancellationToken::new(),
            generation,
            None,
            &options,
            &mut trace,
        )
        .await;
    if result.is_err() {
        while let Ok(update) = receiver.try_recv() {
            assert!(!matches!(update, StreamUpdate::Completed { .. }));
        }
    }
    let _ = socket.close(None).await;
    peer.await.unwrap();
    if matches!(case, Case::Before | Case::After | Case::NoPersistAck) {
        metadata.await.unwrap();
    } else {
        metadata.abort();
        let _ = metadata.await;
    }
    result
}
#[tokio::test]
async fn canonical_discovery_before_final_and_legacy_after_final_both_require_durable_ack() {
    for input in [Case::Before, Case::After] {
        tokio::time::timeout(Duration::from_secs(5), async {
            let result = case(input).await.unwrap();
            assert_eq!(result.assistant, ANSWER);
            assert!(matches!(result.status, SendStatus::Completed));
        })
        .await
        .unwrap();
    }
}
#[tokio::test]
async fn stale_global_discovery_or_wrong_turn_final_never_claims_or_publishes() {
    for input in [Case::NoFinal, Case::WrongFinal] {
        tokio::time::timeout(Duration::from_secs(5), async {
            assert!(matches!(case(input).await, Err(Error::Offline)));
        })
        .await
        .unwrap();
    }
}
#[tokio::test]
async fn discovery_does_not_replace_claim_identity_seal_binding_or_terminal_ack() {
    for input in [
        Case::WrongFinalProtocol,
        Case::WrongFinalAssistant,
        Case::WrongClaimChat,
        Case::WrongClaimTurn,
        Case::WrongClaimAssistant,
        Case::WrongClaimKey,
        Case::WrongSealOwner,
        Case::WrongSealJob,
        Case::NoPersistAck,
        Case::FailedMarker,
        Case::FailedAfterFinal,
    ] {
        tokio::time::timeout(Duration::from_secs(5), async {
            assert!(case(input).await.is_err());
        })
        .await
        .unwrap();
    }
}
