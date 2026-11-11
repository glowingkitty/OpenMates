//! Batched chat decryption against the cross-client fixtures (web TS writer vectors in `ts_web_policy.json`, wrapper/content layouts in `encryption_compatibility/legacy_layouts.json`), per-item failures and off-caller execution.
use crate::chat_crypto::{
    POOL_THREAD_NAME, decrypt_chat_metadata_now, decrypt_messages_now, on_pool,
    unwrap_chat_keys_now,
};
use crate::*;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use serde_json::Value;

fn policy() -> Value {
    serde_json::from_str(include_str!(
        "../../openmates-rust/tests/crypto_fixtures/ts_web_policy.json"
    ))
    .unwrap()
}

fn layouts() -> Value {
    serde_json::from_str(include_str!(
        "../../openmates-rust/tests/crypto_fixtures/encryption_compatibility/legacy_layouts.json"
    ))
    .unwrap()
}

fn b64(value: &Value) -> Vec<u8> {
    STANDARD.decode(value.as_str().unwrap()).unwrap()
}

/// TS `MessageEncryptor` vector by label: (ciphertext, k1 key bytes).
fn vector(label: &str) -> (String, Vec<u8>) {
    let fixture = policy();
    let row = fixture["chat_content"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["label"] == label)
        .unwrap()
        .clone();
    (
        row["ciphertext"].as_str().unwrap().to_owned(),
        b64(&fixture["keys"]["k1_b64"]),
    )
}

fn decrypted(value: &str) -> Option<FieldDecryptOutcome> {
    Some(FieldDecryptOutcome::Decrypted {
        value: value.to_owned(),
    })
}

fn failed(reason: DecryptFailure) -> Option<FieldDecryptOutcome> {
    Some(FieldDecryptOutcome::Failed { reason })
}

#[test]
fn unwraps_the_cross_client_chat_key_wrapper_and_reports_bad_rows_per_item() {
    let fixture = layouts();
    let master = b64(&fixture["keys"]["wrapping_key_b64"]);
    let wrapper = fixture["chat"]["format_c"]["blob_b64"]
        .as_str()
        .unwrap()
        .to_owned();
    // A wrapper of 16 key bytes authenticates but is not an AES-256 chat key.
    let short =
        openmates_sdk::crypto::encrypt_bytes(&[7u8; 16], master.as_slice().try_into().unwrap())
            .unwrap();
    let results = unwrap_chat_keys_now(
        master,
        vec![
            WrappedChatKeyRecord {
                chat_id: "good".into(),
                encrypted_chat_key: wrapper.clone(),
            },
            WrappedChatKeyRecord {
                chat_id: "garbage".into(),
                encrypted_chat_key: "not base64 !".into(),
            },
            WrappedChatKeyRecord {
                chat_id: "short".into(),
                encrypted_chat_key: short,
            },
            WrappedChatKeyRecord {
                chat_id: "good-again".into(),
                encrypted_chat_key: wrapper,
            },
        ],
    )
    .unwrap();
    let ids: Vec<&str> = results.iter().map(|row| row.chat_id.as_str()).collect();
    assert_eq!(ids, ["good", "garbage", "short", "good-again"]);
    let expected = b64(&fixture["chat"]["format_c"]["plaintext_key_b64"]);
    for index in [0, 3] {
        match &results[index].outcome {
            ChatKeyUnwrapOutcome::Unwrapped { chat_key } => assert_eq!(chat_key, &expected),
            ChatKeyUnwrapOutcome::Failed { reason } => panic!("unexpected failure {reason:?}"),
        }
    }
    assert!(matches!(
        results[1].outcome,
        ChatKeyUnwrapOutcome::Failed {
            reason: DecryptFailure::Undecryptable
        }
    ));
    assert!(matches!(
        results[2].outcome,
        ChatKeyUnwrapOutcome::Failed {
            reason: DecryptFailure::InvalidKey
        }
    ));
}

#[test]
fn wrong_master_key_fails_every_row_but_not_the_batch_and_bad_length_is_invalid() {
    let fixture = layouts();
    let wrapper = fixture["chat"]["format_c"]["blob_b64"]
        .as_str()
        .unwrap()
        .to_owned();
    let results = unwrap_chat_keys_now(
        vec![9u8; 32],
        vec![WrappedChatKeyRecord {
            chat_id: "chat".into(),
            encrypted_chat_key: wrapper.clone(),
        }],
    )
    .unwrap();
    assert!(matches!(
        results[0].outcome,
        ChatKeyUnwrapOutcome::Failed {
            reason: DecryptFailure::Undecryptable
        }
    ));
    let error = unwrap_chat_keys_now(
        vec![9u8; 31],
        vec![WrappedChatKeyRecord {
            chat_id: "chat".into(),
            encrypted_chat_key: wrapper,
        }],
    )
    .err()
    .unwrap();
    assert!(matches!(error, CoreError::Invalid { .. }));
}

#[test]
fn chat_metadata_matches_web_vectors_with_typed_per_field_failures() {
    let (om, key) = vector("om-matching");
    let (legacy, _) = vector("legacy-iv");
    let (other_key, _) = vector("om-other-key");
    let (tampered, _) = vector("om-tampered");
    let (truncated, _) = vector("truncated");
    let results = decrypt_chat_metadata_now(vec![
        EncryptedChatMetadataRecord {
            chat_id: "a".into(),
            chat_key: key.clone(),
            encrypted_title: Some(om.clone()),
            encrypted_category: Some(legacy),
            encrypted_icon: Some(other_key),
            encrypted_chat_summary: Some(tampered),
            encrypted_active_focus_id: None,
        },
        EncryptedChatMetadataRecord {
            chat_id: "bad-key".into(),
            chat_key: vec![1u8; 5],
            encrypted_title: Some(om.clone()),
            encrypted_category: None,
            encrypted_icon: None,
            encrypted_chat_summary: None,
            encrypted_active_focus_id: None,
        },
        EncryptedChatMetadataRecord {
            chat_id: "c".into(),
            chat_key: key,
            encrypted_title: None,
            encrypted_category: None,
            encrypted_icon: None,
            encrypted_chat_summary: Some(truncated),
            encrypted_active_focus_id: Some(om),
        },
    ]);
    assert_eq!(
        results,
        vec![
            ChatMetadataRecord {
                chat_id: "a".into(),
                title: decrypted("policy ✓ text"),
                category: decrypted("policy ✓ text"),
                icon: failed(DecryptFailure::KeyMismatch),
                chat_summary: failed(DecryptFailure::Undecryptable),
                active_focus_id: None,
            },
            ChatMetadataRecord {
                chat_id: "bad-key".into(),
                title: failed(DecryptFailure::InvalidKey),
                category: None,
                icon: None,
                chat_summary: None,
                active_focus_id: None,
            },
            ChatMetadataRecord {
                chat_id: "c".into(),
                title: None,
                category: None,
                icon: None,
                chat_summary: failed(DecryptFailure::Undecryptable),
                active_focus_id: decrypted("policy ✓ text"),
            },
        ]
    );
}

#[test]
fn message_window_decrypts_every_field_and_reads_both_legacy_layouts() {
    let fixture = layouts();
    let content_key = b64(&fixture["keys"]["content_key_b64"]);
    let format_a = fixture["chat"]["format_a"]["blob_b64"]
        .as_str()
        .unwrap()
        .to_owned();
    let format_b = fixture["chat"]["format_b"]["blob_b64"]
        .as_str()
        .unwrap()
        .to_owned();
    let results = decrypt_messages_now(
        content_key,
        vec![
            EncryptedMessageRecord {
                message_id: "m1".into(),
                encrypted_content: Some(format_a.clone()),
                encrypted_pii_mappings: Some(format_b.clone()),
                encrypted_thinking_content: Some(format_a.clone()),
                encrypted_sender_name: Some(format_b.clone()),
                encrypted_category: Some(format_a),
                encrypted_model_name: Some("AAAA".into()),
            },
            EncryptedMessageRecord {
                message_id: "m2".into(),
                encrypted_content: Some(format_b),
                encrypted_pii_mappings: None,
                encrypted_thinking_content: None,
                encrypted_sender_name: None,
                encrypted_category: None,
                encrypted_model_name: None,
            },
        ],
    )
    .unwrap();
    assert_eq!(
        results,
        vec![
            MessageFieldsRecord {
                message_id: "m1".into(),
                content: decrypted("legacy-format-a"),
                pii_mappings: decrypted("legacy-format-b"),
                thinking_content: decrypted("legacy-format-a"),
                sender_name: decrypted("legacy-format-b"),
                category: decrypted("legacy-format-a"),
                model_name: failed(DecryptFailure::Undecryptable),
            },
            MessageFieldsRecord {
                message_id: "m2".into(),
                content: decrypted("legacy-format-b"),
                pii_mappings: None,
                thinking_content: None,
                sender_name: None,
                category: None,
                model_name: None,
            },
        ]
    );
    assert!(matches!(
        decrypt_messages_now(vec![0u8; 16], vec![]).err().unwrap(),
        CoreError::Invalid { .. }
    ));
}

#[test]
fn message_window_round_trips_core_writer_output_in_input_order() {
    let key = [5u8; 32];
    let messages: Vec<EncryptedMessageRecord> = (0..50)
        .map(|index| EncryptedMessageRecord {
            message_id: format!("m{index}"),
            encrypted_content: Some(
                openmates_sdk::crypto::chat_key_policy::encrypt_chat_content(
                    format!("message {index}").as_bytes(),
                    &key,
                )
                .unwrap(),
            ),
            encrypted_pii_mappings: None,
            encrypted_thinking_content: None,
            encrypted_sender_name: None,
            encrypted_category: None,
            encrypted_model_name: None,
        })
        .collect();
    let results = decrypt_messages_now(key.to_vec(), messages).unwrap();
    for (index, row) in results.iter().enumerate() {
        assert_eq!(row.message_id, format!("m{index}"));
        assert_eq!(row.content, decrypted(&format!("message {index}")));
    }
}

#[tokio::test]
async fn batches_run_on_the_decryption_pool_not_the_caller_thread() {
    let thread = on_pool(|| Ok(std::thread::current().name().map(str::to_owned)))
        .await
        .unwrap();
    assert_eq!(thread.as_deref(), Some(POOL_THREAD_NAME));
    let (om, key) = vector("om-matching");
    let results = batch_decrypt_chat_metadata(vec![EncryptedChatMetadataRecord {
        chat_id: "a".into(),
        chat_key: key,
        encrypted_title: Some(om),
        encrypted_category: None,
        encrypted_icon: None,
        encrypted_chat_summary: None,
        encrypted_active_focus_id: None,
    }])
    .await
    .unwrap();
    assert_eq!(results[0].title, decrypted("policy ✓ text"));
}

#[test]
fn exported_batches_complete_without_any_caller_runtime() {
    // UniFFI polls from Swift threads that have no tokio context.
    let fixture = layouts();
    let master = b64(&fixture["keys"]["wrapping_key_b64"]);
    let wrapper = fixture["chat"]["format_c"]["blob_b64"]
        .as_str()
        .unwrap()
        .to_owned();
    let results = block_on_without_runtime(batch_unwrap_chat_keys(
        master,
        vec![WrappedChatKeyRecord {
            chat_id: "good".into(),
            encrypted_chat_key: wrapper,
        }],
    ))
    .unwrap();
    assert!(matches!(
        results[0].outcome,
        ChatKeyUnwrapOutcome::Unwrapped { .. }
    ));
}

/// Minimal executor with no tokio context: parks the thread until woken.
fn block_on_without_runtime<F: std::future::Future>(future: F) -> F::Output {
    use std::sync::Arc;
    use std::task::{Context, Poll, Wake, Waker};
    struct Unpark(std::thread::Thread);
    impl Wake for Unpark {
        fn wake(self: Arc<Self>) {
            self.0.unpark();
        }
    }
    let waker = Waker::from(Arc::new(Unpark(std::thread::current())));
    let mut context = Context::from_waker(&waker);
    let mut future = std::pin::pin!(future);
    loop {
        if let Poll::Ready(value) = future.as_mut().poll(&mut context) {
            return value;
        }
        std::thread::park();
    }
}

/// Per-phase cost of the batched decrypts at the shapes of the Swift
/// `NativeEncryptedSyncPerformanceTests` (600 chats, 1000 messages of ~400
/// characters, half with 4 extra short fields). Run it ignored, in release
/// mode, with output capture off.
#[test]
#[ignore = "benchmark; prints timings"]
fn rust_cost_of_the_swift_perf_phases() {
    use openmates_sdk::crypto::encrypt_bytes;
    use std::time::Instant;

    let master = vec![7u8; 32];
    let mut master_arr = [0u8; 32];
    master_arr.copy_from_slice(&master);
    let enc = |text: &str, key: &[u8]| {
        let mut k = [0u8; 32];
        k.copy_from_slice(key);
        encrypt_bytes(text.as_bytes(), &k).unwrap()
    };

    let chat_keys: Vec<Vec<u8>> = (0..600u32).map(|i| vec![(i % 251) as u8 + 1; 32]).collect();
    // Format C wrapper: base64(IV || ciphertext || tag), no OM header.
    let wrappers: Vec<WrappedChatKeyRecord> = chat_keys
        .iter()
        .enumerate()
        .map(|(i, key)| {
            let framed = STANDARD
                .decode(encrypt_bytes(key, &master_arr).unwrap())
                .unwrap();
            WrappedChatKeyRecord {
                chat_id: format!("perf-chat-{i:04}"),
                encrypted_chat_key: STANDARD.encode(&framed[6..]),
            }
        })
        .collect();
    let metadata: Vec<(String, Vec<u8>, [Option<String>; 4])> = chat_keys
        .iter()
        .enumerate()
        .map(|(i, key)| {
            (
                format!("perf-chat-{i:04}"),
                key.clone(),
                [
                    Some(enc(&format!("Synthetic chat {i} title"), key)),
                    Some(enc("general_knowledge", key)),
                    Some(enc("message-circle", key)),
                    Some(enc(
                        &format!("Synthetic summary for chat {i}: a short deterministic description of the topic."),
                        key,
                    )),
                ],
            )
        })
        .collect();
    let key = chat_keys[0].clone();
    let messages: Vec<EncryptedMessageRecord> = (0..1000)
        .map(|i| {
            let user = i % 2 == 0;
            EncryptedMessageRecord {
                message_id: format!("perf-msg-{i:04}"),
                encrypted_content: Some(enc(
                    &format!("Synthetic message {i}. {}", "Lorem ipsum dolor sit amet. ".repeat(14)),
                    &key,
                )),
                encrypted_pii_mappings: user.then(|| {
                    enc(
                        &format!("[{{\"placeholder\":\"[EMAIL_1]\",\"original\":\"user{i}@example.org\",\"type\":\"EMAIL\"}}]"),
                        &key,
                    )
                }),
                encrypted_thinking_content: (!user)
                    .then(|| enc(&format!("Synthetic reasoning for message {i}."), &key)),
                encrypted_sender_name: (!user).then(|| enc("Synthetic Mate", &key)),
                encrypted_category: (!user).then(|| enc("general_knowledge", &key)),
                encrypted_model_name: (!user).then(|| enc("synthetic-model", &key)),
            }
        })
        .collect();

    fn median_ms(mut body: impl FnMut()) -> f64 {
        let mut runs: Vec<f64> = (0..9)
            .map(|_| {
                let start = Instant::now();
                body();
                start.elapsed().as_secs_f64() * 1000.0
            })
            .collect();
        runs.sort_by(|a, b| a.partial_cmp(b).unwrap());
        runs[4]
    }

    println!();
    println!(
        "rust key bulk load, 600 keys (sync): {:.3} ms",
        median_ms(|| {
            unwrap_chat_keys_now(master.clone(), wrappers.clone()).unwrap();
        })
    );
    println!(
        "rust key bulk load, 600 keys (pool hand-off): {:.3} ms",
        median_ms(|| {
            let (m, w) = (master.clone(), wrappers.clone());
            block_on_without_runtime(on_pool(move || unwrap_chat_keys_now(m, w))).unwrap();
        })
    );
    println!(
        "rust metadata, 600 chats x 4 fields (sync): {:.3} ms",
        median_ms(|| {
            let chats = metadata
                .iter()
                .map(|(id, k, f)| EncryptedChatMetadataRecord {
                    chat_id: id.clone(),
                    chat_key: k.clone(),
                    encrypted_title: f[0].clone(),
                    encrypted_category: f[1].clone(),
                    encrypted_icon: f[2].clone(),
                    encrypted_chat_summary: f[3].clone(),
                    encrypted_active_focus_id: None,
                })
                .collect();
            decrypt_chat_metadata_now(chats);
        })
    );
    println!(
        "rust messages, 1000 (sync): {:.3} ms",
        median_ms(|| {
            decrypt_messages_now(key.clone(), messages.clone()).unwrap();
        })
    );
    println!(
        "rust messages, 50-window (sync): {:.3} ms",
        median_ms(|| {
            decrypt_messages_now(key.clone(), messages[950..].to_vec()).unwrap();
        })
    );
}
