//! Authored UNRUN actual full-read dispatch and final application save/release.
//! Reuses the existing isolated synthetic protocol peer; no account/inference.
// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,cli.surface.semantic-parity
use super::*;
use openmates_sdk::client::full_chat_read::FullChatReadAdmission;
use std::{
    io::{BufRead, BufReader},
    process::{Child, Command, Stdio},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
};
const SAVED_SLUG: &str = "Synthetic-Saved-Unique-Slug-final-boundary";
const AMBIENT: &str = "33333333-3333-4333-8333-333333333333";
struct Peer(Child);
impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
fn invocation(args: &[&str]) -> Invocation {
    cli::parse_from(args.iter().copied())
        .unwrap_or_else(|_| panic!("synthetic full-read command"))
        .invocation
        .unwrap()
}
fn secret() -> Option<Zeroizing<String>> {
    Some(Zeroizing::new("synthetic final full-read vault".into()))
}
async fn fixture() -> (
    Peer,
    Client,
    RuntimeStore,
    tempfile::TempDir,
    serde_json::Value,
) {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(std::path::Path::parent)
        .and_then(std::path::Path::parent)
        .unwrap();
    let suite: serde_json::Value = serde_json::from_slice(
        &std::fs::read(
            root.join("tests/sdk-conformance/fixtures/session-foreground-completion-recovery.json"),
        )
        .unwrap(),
    )
    .unwrap();
    let suite = suite["capabilities"]["session.foreground-completion-recovery.v1"].clone();
    let mut child =
        Command::new(
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into()),
        )
        .arg(root.join(
            "frontend/packages/openmates-tui-native/tests/support/saved_read_recovery_peer.py",
        ))
        .args([
            "--vector",
            "foreground-main-durable",
            "--full-chat-slug",
            SAVED_SLUG,
        ])
        .current_dir(root)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let stdout = child.stdout.take().unwrap();
    let peer = Peer(child);
    let (tx, rx) = std::sync::mpsc::sync_channel(1);
    std::thread::spawn(move || {
        let mut line = String::new();
        let result = BufReader::new(stdout).read_line(&mut line).map(|_| line);
        let _ = tx.send(result);
    });
    let ready: serde_json::Value =
        serde_json::from_str(&rx.recv_timeout(Duration::from_secs(3)).unwrap().unwrap()).unwrap();
    let endpoint = ready["endpoint"].as_str().unwrap();
    assert!(endpoint.starts_with("http://127.0.0.1:"));
    let session=serde_json::from_value(json!({"api_url":endpoint,"session_id":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]},"ws_token":null,"master_key":suite["account"]["master_key"],"hashed_email":"synthetic-native-owner","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})).unwrap();
    let mut client = Client::with_options(
        endpoint,
        Some(session),
        ClientOptions {
            identity: openmates_sdk::ClientIdentity::Cli,
            app_url: Some(suite["protocol"]["app_origin"].as_str().unwrap().into()),
            ..Default::default()
        },
    )
    .unwrap();
    client.validate_session().await.unwrap();
    let mut directory_builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        directory_builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    let directory = directory_builder.tempdir().unwrap();
    let store = RuntimeStore::new(Some(directory.path().into()), true)
        .await
        .unwrap();
    session_runtime::persist(&mut client, &store, secret())
        .await
        .unwrap();
    cli::execute_with_foreground_recovery(
        &invocation(&["openmates", "chats", "list", "--json"]),
        &mut client,
        CancellationToken::new(),
        cli::ApplicationRecoveryContext::new(&store, secret()),
    )
    .await
    .unwrap_or_else(|_| panic!("synthetic fixture settlement"));
    client.set_chat_cache_clock_provider(Some(Arc::new(|| {
        openmates_sdk::client::CacheClockEvidence::from_platform(
            "synthetic-final-full-read".into(),
            1_000,
            1_000,
        )
    })));
    (peer, client, store, directory, suite)
}
#[derive(Clone, Copy)]
enum Change {
    Permit,
    OriginalGate,
    Cancel,
    Privacy,
    Forget,
    SameOwnerReset,
    Successor,
}
async fn final_case(ambient_team: bool, full_history: bool, change: Change) {
    let (_peer, mut client, store, _directory, suite) = fixture().await;
    if ambient_team {
        client.set_team(Some(AMBIENT)).unwrap();
    }
    let cancel = CancellationToken::new();
    client.set_operation_cancel(cancel.clone());
    let original = Arc::new(AtomicBool::new(true));
    let gate = original.clone();
    client.set_private_operation_gate(Some(Arc::new(move || {
        if gate.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err(Error::Forbidden)
        }
    })));
    // The original ambient application scope is captured before override.
    let mut admission = SavedReadOutputAdmission::capture(&client, &store).unwrap();
    let id = suite["protocol"]["initial_chat_id"]
        .as_str()
        .unwrap()
        .to_owned();
    let mut args = vec!["openmates", "chats", "show", &id, "--json"];
    if ambient_team { args.push("--personal"); }
    if full_history { args.push("--all"); } else { args.push("--raw"); }
    let command = invocation(&args);
    let (output, full) = cli::execute_with_foreground_recovery_admitted(
        &command,
        &mut client,
        cancel.clone(),
        cli::ApplicationRecoveryContext::new(&store, secret()),
    )
    .await
    .unwrap_or_else(|_| panic!("actual synthetic full-read dispatch"));
    assert!(!output.stdout.is_empty());
    assert!(output.stderr.is_empty());
    let expected = output.stdout.clone();
    let bytes: serde_json::Value = serde_json::from_str(&expected).unwrap();
    assert_eq!(bytes["chat"]["id"], id);
    assert_eq!(bytes["chat"]["slug"], SAVED_SLUG);
    assert!(bytes["messages"].is_array());
    assert!(bytes["follow_up_suggestions"].is_array());
    assert!(bytes["chat"].get("messages").is_none());
    assert_eq!(bytes.get("has_more_before").is_none(), full_history);
    assert!(bytes.get("encrypted_slug").is_none());
    assert_eq!(
        client.session().unwrap().active_team_id.as_deref(),
        ambient_team.then_some(AMBIENT)
    );
    let Some(full) = full else {
        panic!("actual full read retains original admission")
    };
    admission.full_read = Some(full);
    admission.check(&client, &store).unwrap();
    client.set_private_operation_gate(Some(Arc::new(|| Ok(()))));
    // A remains private/wiping throughout the exact runtime final save helper.
    let wiped = Arc::new(AtomicBool::new(false));
    let mut pending = PendingOutput::new(output);
    pending.wiped_on_drop = Some(wiped.clone());
    let successor = CancellationToken::new();
    let successor_copy = successor.clone();
    let successor_admission = Arc::new(Mutex::new(None::<FullChatReadAdmission>));
    let successor_slot = successor_admission.clone();
    let id_copy = id.clone();
    let (_registration, barrier) =
        final_saved_read_persist_test_hook::install_action(&cancel, move |client| match change {
            Change::Privacy => {
                client.set_privacy_options(privacy::PrivacyOptions { enhanced: true })
            }
            Change::Forget => client.forget_session(),
            Change::SameOwnerReset => {
                let session = client.clone_session();
                let api = client.session().unwrap().api_url.clone();
                client.reset(&api, session).unwrap();
            }
            Change::Successor => {
                client.set_operation_cancel(successor_copy);
                let Ok(b) = client.full_chat_read_admission(&id_copy) else {
                    panic!("successor restrictive admission")
                };
                *successor_slot.lock().unwrap() = Some(b);
            }
            _ => {}
        });
    let result = {
        let release = finish_saved_read_output(
            pending,
            persist_saved_read_final(&admission, &mut client, &store, secret(), &cancel),
        );
        tokio::pin!(release);
        tokio::select! {biased;
            _=barrier.persisted.notified()=>{},
            _=&mut release=>panic!("final full-read save barrier escaped"),
        }
        if matches!(change, Change::OriginalGate) {
            original.store(false, Ordering::Release);
        }
        if matches!(change, Change::Cancel) {
            cancel.cancel();
        }
        barrier.resume.notify_one();
        release.await
    };
    if matches!(change, Change::Permit) {
        let output = result.unwrap_or_else(|_| panic!("permitted final full-read handoff"));
        assert_eq!(output.stdout, expected);
        assert!(output.stderr.is_empty());
        assert_eq!(output.exit_code, 0);
    } else {
        assert!(result.is_err());
        assert!(wiped.load(Ordering::Acquire));
    }
    if matches!(change, Change::Successor) {
        assert!(!successor.is_cancelled());
        assert!(
            successor_admission
                .lock()
                .unwrap()
                .as_ref()
                .unwrap()
                .check(&client)
                .is_ok()
        );
        drop(admission);
        assert!(!successor.is_cancelled());
        assert!(
            successor_admission
                .lock()
                .unwrap()
                .as_ref()
                .unwrap()
                .check(&client)
                .is_ok()
        );
    }
}
#[tokio::test(flavor = "current_thread")]
async fn actual_full_json_final_save_restores_ambient_context_and_preserves_original_policy() {
    tokio::time::timeout(Duration::from_secs(360), async {
        // No override and an actual Team -> Personal read -> Team restoration.
        for ambient_team in [false, true] {
            for full_history in [false, true] {
            for change in [
                Change::Permit,
                Change::OriginalGate,
                Change::Cancel,
                Change::Privacy,
                Change::Forget,
                Change::SameOwnerReset,
                Change::Successor,
            ] {
                final_case(ambient_team, full_history, change).await;
            }
            }
        }
    })
    .await
    .unwrap();
}
