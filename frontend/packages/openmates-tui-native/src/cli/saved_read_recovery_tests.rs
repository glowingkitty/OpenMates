// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted,cli.output.actionable-readable
//! PRIVATE UNRUN actual native CLI read/recovery/store tests. Synthetic loopback only.
use super::*;
use crate::runtime_store::RuntimeStore;
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::{SocketAddr, TcpStream},
    path::Path,
    process::{Child, Command, Stdio},
    sync::mpsc as std_mpsc,
    time::{Duration, Instant},
};
type R<T> = std::result::Result<T, &'static str>;
#[track_caller]
fn need(value: bool) -> R<()> {
    assert!(value, "CLI recovery assertion");
    Ok(())
}
fn field<'a>(value: &'a Value, key: &str) -> R<&'a str> {
    value[key].as_str().ok_or("typed fixture field")
}
fn command(args: &[&str]) -> Invocation {
    parse_from(args.iter().copied())
        .unwrap_or_else(|error| panic!("{error}"))
        .invocation
        .unwrap()
}
fn secret() -> Option<zeroize::Zeroizing<String>> {
    Some(zeroize::Zeroizing::new(
        "synthetic private vault passphrase".into(),
    ))
}
fn fixture_directory() -> R<tempfile::TempDir> {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    builder.tempdir().map_err(|_| "owned fixture store")
}
struct Peer {
    process: Child,
    endpoint: String,
}
impl Peer {
    fn start(root: &Path) -> R<Self> {
        let mut process = Command::new(
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into()),
        )
        .arg(root.join(
            "frontend/packages/openmates-tui-native/tests/support/saved_read_recovery_peer.py",
        ))
        .args(["--vector", "foreground-main-durable"])
        .current_dir(root)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "loopback peer")?;
        let stdout = process.stdout.take().ok_or("peer output")?;
        let (tx, rx) = std_mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut line = String::new();
            let result = BufReader::new(stdout).read_line(&mut line).map(|_| line);
            let _ = tx.send(result);
        });
        let mut peer = Self {
            process,
            endpoint: String::new(),
        };
        let line = rx
            .recv_timeout(Duration::from_secs(3))
            .map_err(|_| "bounded peer readiness")?
            .map_err(|_| "peer readiness")?;
        let ready: Value = serde_json::from_str(&line).map_err(|_| "peer JSON")?;
        peer.endpoint = field(&ready, "endpoint")?.to_owned();
        need(peer.endpoint.starts_with("http://127.0.0.1:"))?;
        Ok(peer)
    }
    fn get(&self, route: &str) -> R<Value> {
        let address: SocketAddr = self
            .endpoint
            .strip_prefix("http://")
            .ok_or("loopback")?
            .parse()
            .map_err(|_| "address")?;
        let mut socket = TcpStream::connect_timeout(&address, Duration::from_secs(2))
            .map_err(|_| "peer connect")?;
        socket
            .set_read_timeout(Some(Duration::from_secs(2)))
            .map_err(|_| "peer timeout")?;
        socket
            .set_write_timeout(Some(Duration::from_secs(2)))
            .map_err(|_| "peer timeout")?;
        socket
            .write_all(
                format!("GET {route} HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n")
                    .as_bytes(),
            )
            .map_err(|_| "peer write")?;
        let mut bytes = String::new();
        socket
            .take(1024 * 1024)
            .read_to_string(&mut bytes)
            .map_err(|_| "peer read")?;
        serde_json::from_str(bytes.split_once("\r\n\r\n").ok_or("peer HTTP")?.1)
            .map_err(|_| "peer status")
    }
}
impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.process.kill();
        let deadline = Instant::now() + Duration::from_secs(2);
        while Instant::now() < deadline {
            if self.process.try_wait().ok().flatten().is_some() {
                break;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}

async fn fixture() -> R<(Peer, Client, RuntimeStore, tempfile::TempDir, Value)> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .and_then(Path::parent)
        .ok_or("repo root")?;
    let suite: Value = serde_json::from_slice(
        &std::fs::read(
            root.join("tests/sdk-conformance/fixtures/session-foreground-completion-recovery.json"),
        )
        .map_err(|_| "fixture read")?,
    )
    .map_err(|_| "fixture JSON")?;
    let suite = suite["capabilities"]["session.foreground-completion-recovery.v1"].clone();
    let peer = Peer::start(root)?;
    let session=serde_json::from_value(json!({"api_url":peer.endpoint,"session_id":suite["account"]["session_id"],"cookies":{"auth_refresh_token":suite["account"]["cookie"]},"ws_token":null,"master_key":suite["account"]["master_key"],"hashed_email":"synthetic-native-owner","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})).map_err(|_|"synthetic Session")?;
    let mut client = Client::with_options(
        &peer.endpoint,
        Some(session),
        openmates_sdk::ClientOptions {
            identity: openmates_sdk::ClientIdentity::Cli,
            app_url: Some(field(&suite["protocol"], "app_origin")?.into()),
            ..Default::default()
        },
    )
    .map_err(|_| "genuine CLI Client")?;
    client
        .validate_session()
        .await
        .map_err(|_| "explicit Cookie admission")?;
    let directory = fixture_directory()?;
    let store = RuntimeStore::new(Some(directory.path().into()), true)
        .await
        .map_err(|_| "encrypted RuntimeStore")?;
    // Match command_runtime's authenticated saved-session admission before
    // cache writes. No real profile/keyring is consulted.
    crate::session_runtime::persist(&mut client, &store, secret())
        .await
        .map_err(|_| "initial encrypted session durability")?;
    Ok((peer, client, store, directory, suite))
}
async fn saved_read(args: &[&str], restore_team: bool) -> R<()> {
    let (peer, mut client, store, _directory, suite) = fixture().await?;
    let original = "33333333-3333-4333-8333-333333333333";
    if restore_team {
        client
            .set_team(Some(original))
            .map_err(|_| "original Team")?;
    }
    let invocation = command(args);
    let output = execute_with_foreground_recovery(
        &invocation,
        &mut client,
        CancellationToken::new(),
        ApplicationRecoveryContext {
            list_stage_observer: None,
            store: &store,
            passphrase: secret(),
            after_recovery_persist: None,
        },
    )
    .await
    .map_err(|error| error.code())?;
    let status = peer.get("/__test/status")?;
    need(
        status["claims"] == 1
            && status["persists"] == 1
            && status["admissions"] == 0
            && status["failure"].is_null(),
    )?;
    need(serde_json::from_str::<Value>(&output.stdout).is_ok())?;
    if invocation.command_path() == "chats list" {
        // Discovery inventory cannot survive an actual recovery mutation.
        need(status["inventory_syncs"].as_u64().unwrap_or(0) >= 2)?;
    }
    if matches!(
        invocation.command_path().as_str(),
        "chats show" | "chats messages"
    ) {
        need(
            output
                .stdout
                .contains(field(&suite["protocol"], "sealed_content")?),
        )?;
    }
    need(
        !output
            .stdout
            .contains(field(&suite["protocol"], "transient_content")?),
    )?;
    need(
        client.session().and_then(|s| s.active_team_id.as_deref())
            == if restore_team { Some(original) } else { None },
    )?;
    let session = client.session().ok_or("retained session")?;
    let cache = store
        .read_cache(
            session.hashed_email.clone(),
            "sync-personal".into(),
            session.master_key.clone(),
        )
        .await
        .map_err(|_| "durable canonical cache")?
        .ok_or("published canonical cache")?;
    let encoded = serde_json::to_string(&cache).map_err(|_| "ciphertext JSON")?;
    need(
        encoded.contains(field(&suite["protocol"], "assistant_id")?)
            && !encoded.contains(field(&suite["protocol"], "sealed_content")?),
    )?;
    let pending = store
        .read_cache(
            session.hashed_email.clone(),
            "completion-pending-sync-personal".into(),
            session.master_key.clone(),
        )
        .await
        .map_err(|_| "Personal pending store")?
        .ok_or("Personal pending cache retained")?;
    need(pending.as_object().is_some_and(|items| items.is_empty()))?;
    // The application wrapper disables opt-in on completion. The public SDK
    // method must refuse even though this Client remains authenticated.
    need(matches!(
        client
            .completion_recovery_jobs(&CancellationToken::new())
            .await,
        Err(Error::Unavailable { .. })
    ))?;
    Ok(())
}
#[tokio::test]
async fn show_recovers_and_persists_personal_scope_before_restoring_original_team() -> R<()> {
    tokio::time::timeout(
        Duration::from_secs(10),
        saved_read(
            &[
                "openmates",
                "chats",
                "show",
                "22222222-2222-4222-8222-222222222222",
                "--personal",
                "--json",
            ],
            true,
        ),
    )
    .await
    .map_err(|_| "show deadline")?
}
#[tokio::test]
async fn messages_recovery_precedes_final_json() -> R<()> {
    tokio::time::timeout(
        Duration::from_secs(10),
        saved_read(
            &[
                "openmates",
                "chats",
                "messages",
                "22222222-2222-4222-8222-222222222222",
                "--json",
            ],
            false,
        ),
    )
    .await
    .map_err(|_| "messages deadline")?
}
#[tokio::test]
async fn list_recovery_precedes_final_json() -> R<()> {
    tokio::time::timeout(
        Duration::from_secs(10),
        saved_read(
            &["openmates", "chats", "list", "--limit", "1", "--json"],
            false,
        ),
    )
    .await
    .map_err(|_| "list deadline")?
}
#[tokio::test]
async fn search_recovery_precedes_final_json() -> R<()> {
    tokio::time::timeout(
        Duration::from_secs(10),
        saved_read(
            &["openmates", "chats", "search", "Synthetic", "--json"],
            false,
        ),
    )
    .await
    .map_err(|_| "search deadline")?
}
#[test]
fn recovery_selection_excludes_other_command_families_and_rejects_malformed_reads() {
    for args in [
        vec!["openmates", "whoami"],
        vec!["openmates", "chats", "send", "hello"],
        vec!["openmates", "tasks", "list"],
        vec!["openmates", "chats", "incognito", "hello"],
    ] {
        assert!(
            saved_read_recovery(&command(&args))
                .unwrap_or_else(|_| panic!("classification"))
                .is_none()
        );
    }
    for args in [
        vec!["openmates", "chats", "list", "--limit", "0"],
        vec!["openmates", "chats", "list", "--status", "unknown"],
        vec!["openmates", "chats", "show", "id", "--incognito"],
        vec!["openmates", "chats", "search", "needle", "--limit", "1"],
    ] {
        assert!(saved_read_recovery(&command(&args)).is_err());
    }
    let mut missing = command(&["openmates", "chats", "show", "id"]);
    missing.positionals.clear();
    assert!(saved_read_recovery(&missing).is_err());
}
#[tokio::test]
async fn old_execute_and_whoami_never_enable_foreground_takeover() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory, _suite) = fixture().await?;
        execute(
            &command(&["openmates", "chats", "list", "--json"]),
            &mut client,
            CancellationToken::new(),
        )
        .await
        .map_err(|error| error.code())?;
        execute_with_foreground_recovery(
            &command(&["openmates", "whoami", "--json"]),
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext {
                list_stage_observer: None,
                store: &store,
                passphrase: secret(),
                after_recovery_persist: None,
            },
        )
        .await
        .map_err(|error| error.code())?;
        let status = peer.get("/__test/status")?;
        need(status["claims"] == 0 && status["persists"] == 0 && status["admissions"] == 0)?;
        Ok(())
    })
    .await
    .map_err(|_| "default-off deadline")?
}
#[tokio::test]
async fn callback_owner_scope_store_generation_and_cancel_guards_refuse_persistence() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory, _suite) = fixture().await?;
        let cancel = CancellationToken::new();
        let admission = RecoveryReadAdmission::capture(&client, &store, &cancel)
            .map_err(|_| "scope capture")?;
        let context = ApplicationRecoveryContext {
            list_stage_observer: None,
            store: &store,
            passphrase: secret(),
            after_recovery_persist: None,
        };
        cancel.cancel();
        let mut persistence = CanonicalReadPersistence {
            context: &context,
            admission: &admission,
            after_persist: None,
        };
        use crate::completion_recovery_adapter::CanonicalRecoveryPersistence;
        need(matches!(
            persistence
                .persist_reconciled_canonical(
                    &mut client,
                    "22222222-2222-4222-8222-222222222222",
                    &cancel
                )
                .await,
            Err(Error::Cancelled)
        ))?;
        let fresh = CancellationToken::new();
        store.revoke().await.map_err(|_| "owned store revoke")?;
        need(matches!(
            admission.check(&client, &store, &fresh),
            Err(Error::Cancelled)
        ))?;
        need(
            store
                .load(secret())
                .await
                .map_err(|_| "no session resurrection")?
                .is_none(),
        )?;
        let admission =
            RecoveryReadAdmission::capture(&client, &store, &fresh).map_err(|_| "fresh scope")?;
        client
            .set_team(Some("33333333-3333-4333-8333-333333333333"))
            .map_err(|_| "scope replacement")?;
        need(matches!(
            admission.check(&client, &store, &fresh),
            Err(Error::Cancelled)
        ))?;
        let status = peer.get("/__test/status")?;
        need(status["claims"] == 0 && status["persists"] == 0 && status["admissions"] == 0)?;
        Ok(())
    })
    .await
    .map_err(|_| "guard deadline")?
}

#[tokio::test]
async fn callback_cancel_after_real_durable_write_refuses_publication_without_rollback() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (_peer, mut client, store, _directory, _suite) = fixture().await?;
        let cancel = CancellationToken::new();
        let admission =
            RecoveryReadAdmission::capture(&client, &store, &cancel).map_err(|_| "admission")?;
        let context = ApplicationRecoveryContext {
            list_stage_observer: None,
            store: &store,
            passphrase: secret(),
            after_recovery_persist: None,
        };
        let barrier = std::sync::Arc::new(CanonicalPersistenceBarrier::default());
        let mut persistence = CanonicalReadPersistence {
            context: &context,
            admission: &admission,
            after_persist: Some(barrier.clone()),
        };
        use crate::completion_recovery_adapter::CanonicalRecoveryPersistence;
        let invalidation = async {
            barrier.persisted.notified().await;
            cancel.cancel();
            barrier.resume.notify_one();
        };
        let (result, ()) = tokio::join!(
            persistence.persist_reconciled_canonical(
                &mut client,
                "22222222-2222-4222-8222-222222222222",
                &cancel
            ),
            invalidation
        );
        need(matches!(result, Err(Error::Cancelled)))?;
        // A completed durable write is not rolled back by a late cancellation.
        need(
            store
                .load(secret())
                .await
                .map_err(|_| "saved credentials")?
                .is_some(),
        )?;
        let session = client.session().ok_or("current session")?;
        need(
            store
                .read_cache(
                    session.hashed_email.clone(),
                    crate::session_runtime::cache_key(session),
                    session.master_key.clone(),
                )
                .await
                .map_err(|_| "saved ciphertext")?
                .is_some(),
        )?;
        Ok(())
    })
    .await
    .map_err(|_| "postwrite cancel deadline")?
}
#[tokio::test]
async fn app_entrypoint_validates_saved_read_before_authentication_or_storage() -> R<()> {
    tokio::time::timeout(Duration::from_secs(3), async {
        let directory = fixture_directory()?;
        let store = RuntimeStore::new(Some(directory.path().into()), true)
            .await
            .map_err(|error| super::super::client_error_code(&error))?;
        for args in [
            vec!["openmates", "chats", "show", "not-a-uuid"],
            vec![
                "openmates",
                "chats",
                "messages",
                "22222222222242228222222222222222",
            ],
            vec!["openmates", "chats", "list", "--limit", "0"],
            vec!["openmates", "chats", "search", "needle", "--limit", "1"],
        ] {
            let mut client =
                Client::new("http://127.0.0.1:1", None).map_err(|_| "unauthenticated Client")?;
            let result = execute_with_foreground_recovery(
                &command(&args),
                &mut client,
                CancellationToken::new(),
                ApplicationRecoveryContext {
                    list_stage_observer: None,
                    store: &store,
                    passphrase: secret(),
                    after_recovery_persist: None,
                },
            )
            .await;
            need(matches!(
                result,
                Err(CliError::Invalid(_) | CliError::Unsupported { .. })
            ))?;
            need(client.session().is_none())?;
            need(
                store
                    .storage_mode()
                    .await
                    .map_err(|_| "storage untouched")?
                    .is_none(),
            )?;
        }
        Ok(())
    })
    .await
    .map_err(|_| "prevalidation deadline")?
}

#[tokio::test]
async fn selected_team_denial_is_scoped_and_restores_personal_without_claim_or_output() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory, _suite) = fixture().await?;
        let team = "33333333-3333-4333-8333-333333333333";
        let result = execute_with_foreground_recovery(
            &command(&["openmates", "chats", "list", "--team", team, "--json"]),
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext {
                list_stage_observer: None,
                store: &store,
                passphrase: secret(),
                after_recovery_persist: None,
            },
        )
        .await;
        need(matches!(result, Err(CliError::Client(Error::Forbidden))))?;
        need(client.session().is_some_and(|s| s.active_team_id.is_none()))?;
        let status = peer.get("/__test/status")?;
        need(
            status["denied_team"] == team
                && status["claims"] == 0
                && status["persists"] == 0
                && status["admissions"] == 0,
        )?;
        need(matches!(
            client
                .completion_recovery_jobs(&CancellationToken::new())
                .await,
            Err(Error::Unavailable { .. })
        ))?;
        Ok(())
    })
    .await
    .map_err(|_| "selected Team deadline")?
}

#[tokio::test]
async fn forced_drop_during_actual_durable_recovery_callback_restores_scope_disables_mode_and_retains_ciphertext()
-> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory, _suite) = fixture().await?;
        let original = "33333333-3333-4333-8333-333333333333";
        client
            .set_team(Some(original))
            .map_err(|_| "original Team")?;
        let session = client.session().ok_or("original session")?.clone();
        let cancel = CancellationToken::new();
        let barrier = std::sync::Arc::new(CanonicalPersistenceBarrier::default());
        let invocation = command(&[
            "openmates",
            "chats",
            "show",
            "22222222-2222-4222-8222-222222222222",
            "--personal",
            "--json",
        ]);
        let context = ApplicationRecoveryContext {
            list_stage_observer: None,
            store: &store,
            passphrase: secret(),
            after_recovery_persist: Some(barrier.clone()),
        };
        let before = {
            let mut operation = Box::pin(execute_with_foreground_recovery(
                &invocation,
                &mut client,
                cancel.clone(),
                context,
            ));
            tokio::select! {
                _=barrier.persisted.notified()=>{},
                result=&mut operation=>return Err(match result {
                    Err(error) => error.code(),
                    Ok(_) => "operation finished before gated storage callback",
                }),
            }
            let status = peer.get("/__test/status")?;
            need(status["claims"] == 1 && status["persists"] == 1)?;
            // The callback has performed the real encrypted Store save but
            // remains blocked before returning success/clearing the checkpoint.
            let disk = store
                .load(secret())
                .await
                .map_err(|_| "selected-scope saved session")?
                .ok_or("durable session")?;
            need(disk.active_team_id.is_none())?;
            let before = store
                .read_cache(
                    session.hashed_email.clone(),
                    "completion-pending-sync-personal".into(),
                    session.master_key.clone(),
                )
                .await
                .map_err(|_| "durable uncertain checkpoint")?
                .ok_or("retained checkpoint")?;
            need(before.as_object().is_some_and(|items| items.len() == 1))?;
            cancel.cancel();
            // Mirrors cancellable's grace expiry: callback intentionally does
            // not resume, so the caller is forced to DROP the operation future.
            need(
                tokio::time::timeout(Duration::from_millis(20), operation.as_mut())
                    .await
                    .is_err(),
            )?;
            drop(operation);
            before
        };
        need(client.session().and_then(|s| s.active_team_id.as_deref()) == Some(original))?;
        need(matches!(
            client
                .completion_recovery_jobs(&CancellationToken::new())
                .await,
            Err(Error::Unavailable { .. })
        ))?;
        let after = store
            .read_cache(
                session.hashed_email.clone(),
                "completion-pending-sync-personal".into(),
                session.master_key.clone(),
            )
            .await
            .map_err(|_| "uncertain candidate survives drop")?
            .ok_or("unchanged candidate")?;
        need(before == after)?;
        // This is the application's final profile write after its forced drop.
        // It must save the ORIGINAL scope, not the temporary Personal context.
        crate::session_runtime::persist(&mut client, &store, secret())
            .await
            .map_err(|_| "final original-profile persist")?;
        let saved = store
            .load(secret())
            .await
            .map_err(|_| "original profile load")?
            .ok_or("saved original session")?;
        need(saved.active_team_id.as_deref() == Some(original))?;
        let retained = store
            .read_cache(
                session.hashed_email.clone(),
                "completion-pending-sync-personal".into(),
                session.master_key.clone(),
            )
            .await
            .map_err(|_| "pending after final write")?
            .ok_or("pending retained")?;
        need(retained == before)?;
        let status = peer.get("/__test/status")?;
        need(status["persists"] == 1 && status["admissions"] == 0 && status["failure"].is_null())?;
        Ok(())
    })
    .await
    .map_err(|_| "forced storage-drop deadline")?
}
#[tokio::test]
async fn recovery_scope_drop_never_revives_cleared_authentication() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (_peer, mut client, store, _directory, _suite) = fixture().await?;
        let context = ApplicationRecoveryContext {
            list_stage_observer: None,
            store: &store,
            passphrase: secret(),
            after_recovery_persist: None,
        };
        let scoped =
            ScopedRecoveryClient::capture(&mut client, &context, &CancellationToken::new())
                .map_err(|_| "scope capture")?;
        scoped
            .client
            .set_foreground_completion_recovery(true)
            .map_err(|_| "explicit mode")?;
        scoped.client.forget_session();
        drop(scoped);
        need(client.session().is_none())?;
        crate::session_runtime::persist(&mut client, &store, secret())
            .await
            .map_err(|_| "durable auth denial")?;
        need(
            store
                .load(secret())
                .await
                .map_err(|_| "no credential revival")?
                .is_none(),
        )?;
        Ok(())
    })
    .await
    .map_err(|_| "auth denial drop deadline")?
}

#[tokio::test]
async fn idle_list_reuses_one_complete_discovery_and_persists_before_return() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory, _suite) = fixture().await?;
        peer.get("/__test/control?action=no-recovery")?;
        let output = execute_with_foreground_recovery(
            &command(&["openmates", "chats", "list", "--json"]),
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext {
                list_stage_observer: None,
                store: &store,
                passphrase: secret(),
                after_recovery_persist: None,
            },
        )
        .await
        .map_err(|error| error.code())?;
        let status = peer.get("/__test/status")?;
        need(
            status["auth_checks"] == 2
                && status["inventory_syncs"] == 1
                && status["inventory_discovery"] == 1
                && status["metadata_discovery"] == 1
                && status["task_inventory_discovery"] == 1
                && status["claims"] == 0
                && status["persists"] == 0
                && status["failure"].is_null(),
        )?;
        need(serde_json::from_str::<Value>(&output.stdout).is_ok())?;
        let session = client.session().ok_or("current session")?;
        need(
            store
                .read_cache(
                    session.hashed_email.clone(),
                    "sync-personal".into(),
                    session.master_key.clone(),
                )
                .await
                .map_err(|_| "final durable inventory")?
                .is_some(),
        )?;
        let saved = store
            .load(secret())
            .await
            .map_err(|_| "final durable credentials")?
            .ok_or("saved session")?;
        need(saved.ws_token == session.ws_token)?;
        Ok(())
    })
    .await
    .map_err(|_| "idle inventory deadline")?
}

#[tokio::test]
async fn idle_inventory_output_is_wiped_when_store_admission_becomes_stale() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory, _suite) = fixture().await?;
        peer.get("/__test/control?action=no-recovery")?;
        let cancel = CancellationToken::new();
        let context = ApplicationRecoveryContext {
            list_stage_observer: None,
            store: &store,
            passphrase: secret(),
            after_recovery_persist: None,
        };
        let (admission, proof) = recover_saved_read(
            &mut client,
            &SavedReadRecovery::Inventory,
            &context,
            &cancel,
            true,
        )
        .await
        .map_err(|_| "complete discovery")?;
        need(proof.is_some())?;
        let mut output = execute_context_with_inventory(
            &command(&["openmates", "chats", "list", "--json"]),
            &mut client,
            cancel.clone(),
            Some(&store),
            proof,
        )
        .await
        .map_err(|error| error.code())?;
        need(!output.stdout.is_empty())?;
        store.revoke().await.map_err(|_| "invalidate owned store")?;
        need(matches!(
            persist_saved_read_output(&mut output, &mut client, &context, &admission, &cancel)
                .await,
            Err(Error::Cancelled)
        ))?;
        need(output.stdout.is_empty() && output.stderr.is_empty())?;
        need(
            store
                .load(secret())
                .await
                .map_err(|_| "no session resurrection")?
                .is_none(),
        )?;
        need(peer.get("/__test/status")?["inventory_syncs"] == 1)?;
        need(peer.get("/__test/status")?["phase2_inventory_syncs"] == 1)?;
        Ok(())
    })
    .await
    .map_err(|_| "stale inventory output deadline")?
}

#[tokio::test]
async fn idle_inventory_final_durable_save_failure_wipes_output() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, directory, _suite) = fixture().await?;
        peer.get("/__test/control?action=no-recovery")?;
        let cancel = CancellationToken::new();
        let context = ApplicationRecoveryContext {
            list_stage_observer: None,
            store: &store,
            passphrase: secret(),
            after_recovery_persist: None,
        };
        let (admission, proof) = recover_saved_read(
            &mut client,
            &SavedReadRecovery::Inventory,
            &context,
            &cancel,
            true,
        )
        .await
        .map_err(|_| "complete discovery")?;
        need(proof.is_some())?;
        let mut output = execute_context_with_inventory(
            &command(&["openmates", "chats", "list", "--json"]),
            &mut client,
            cancel.clone(),
            Some(&store),
            proof,
        )
        .await
        .map_err(|error| error.code())?;
        need(!output.stdout.is_empty())?;
        // Fail the real atomic credential publication in this owned temporary
        // store; this does not rely on a mocked successful persistence receipt.
        let credential_path = directory.path().join("session.json");
        std::fs::remove_file(&credential_path).map_err(|_| "remove owned fixture credential")?;
        std::fs::create_dir(&credential_path).map_err(|_| "owned publication obstruction")?;
        need(
            persist_saved_read_output(&mut output, &mut client, &context, &admission, &cancel)
                .await
                .is_err(),
        )?;
        need(output.stdout.is_empty() && output.stderr.is_empty())?;
        need(peer.get("/__test/status")?["inventory_syncs"] == 1)?;
        need(peer.get("/__test/status")?["phase2_inventory_syncs"] == 1)?;
        Ok(())
    })
    .await
    .map_err(|_| "failed inventory publication deadline")?
}

// PRIVATE UNRUN: exercises the actual handler, durable ciphertext roundtrip,
// independent fresh session admission, and synthetic peer request counts.
async fn same_boot_warm_list_restores_receipt_and_skips_only_sync(
    explicit_personal: bool,
) -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory, _suite) = fixture().await?;
        peer.get("/__test/control?action=no-recovery")?;
        let ticks = std::sync::Arc::new(std::sync::atomic::AtomicU64::new(1_000));
        let sample = {
            let ticks = ticks.clone();
            std::sync::Arc::new(move || {
                let tick = ticks.load(std::sync::atomic::Ordering::SeqCst);
                crate::client::CacheClockEvidence::from_platform(
                    "synthetic-native-boot".into(),
                    tick,
                    tick,
                )
            })
        };
        client.set_chat_cache_clock_provider(Some(sample.clone()));
        let invocation = if explicit_personal {
            command(&["openmates", "chats", "list", "--limit", "100", "--json"])
        } else {
            command(&["openmates", "chats", "list", "--json"])
        };
        let first = execute_with_foreground_recovery(
            &invocation,
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        let original_status = peer.get("/__test/status")?;
        need(original_status["inventory_syncs"] == 1)?;
        let saved = store
            .load(secret())
            .await
            .map_err(|_| "saved session")?
            .ok_or("saved credentials")?;
        let mut restarted = Client::with_options(
            &peer.endpoint,
            Some(saved),
            openmates_sdk::ClientOptions {
                identity: openmates_sdk::ClientIdentity::Cli,
                app_url: Some(client.application_url()),
                ..Default::default()
            },
        )
        .map_err(|_| "explicit restarted Client")?;
        restarted.set_chat_cache_clock_provider(Some(sample));
        ticks.store(2_000, std::sync::atomic::Ordering::SeqCst);
        let cancel = CancellationToken::new();
        crate::session_runtime::restore_protected_cache(&mut restarted, &store, secret(), &cancel)
            .await
            .map_err(|_| "protected receipt restore")?;
        let read = if explicit_personal {
            command(&[
                "openmates",
                "chats",
                "list",
                "--personal",
                "--limit",
                "100",
                "--json",
            ])
        } else {
            command(&["openmates", "chats", "list", "--json"])
        };
        let admission_command = if explicit_personal {
            command(&[
                "openmates",
                "chats",
                "list",
                "--personal",
                "--limit",
                "100",
                "--json",
            ])
        } else {
            command(&["openmates", "whoami", "--json"])
        };
        crate::session_runtime::prepare_command_cache_admission(&mut restarted, &admission_command);
        let admitted = crate::session_runtime::FreshSessionAdmission::admit(
            &mut restarted,
            &store,
            secret(),
            &cancel,
        )
        .await
        .map_err(|_| "fresh live admission")?;
        drop(admitted);
        let second = execute_with_foreground_recovery(
            &read,
            &mut restarted,
            cancel.clone(),
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        need(first.stdout == second.stdout)?;
        let warm_status = peer.get("/__test/status")?;
        need(warm_status["inventory_syncs"] == 1)?;
        need(
            warm_status["auth_checks"].as_u64()
                == original_status["auth_checks"].as_u64().map(|v| v + 1),
        )?;
        let durable_session = store
            .load(secret())
            .await
            .map_err(|_| "durable warm credentials")?
            .ok_or("warm credentials retained")?;
        let current = restarted.session().ok_or("current warm session")?;
        need(durable_session.active_team_id.is_none() && current.active_team_id.is_none())?;
        need(durable_session.ws_token == current.ws_token)?;
        let durable = store
            .read_cache(
                current.hashed_email.clone(),
                "sync-personal".into(),
                current.master_key.clone(),
            )
            .await
            .map_err(|_| "durable warm output cache")?
            .ok_or("warm snapshot published")?;
        need(durable == restarted.ciphertext_snapshot())?;
        // The required fresh admission and durable saves do not renew 1000+TTL.
        ticks.store(301_000, std::sync::atomic::Ordering::SeqCst);
        execute_with_foreground_recovery(
            &read,
            &mut restarted,
            cancel,
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        need(peer.get("/__test/status")?["inventory_syncs"] == 2)?;
        Ok(())
    })
    .await
    .map_err(|_| "warm list deadline")?
}

#[tokio::test]
async fn same_boot_warm_default_list_restores_receipt_and_skips_only_sync() -> R<()> {
    same_boot_warm_list_restores_receipt_and_skips_only_sync(false).await
}

#[tokio::test]
async fn default_mint_restored_explicit_personal_reuses_after_fresh_auth_and_durable_save() -> R<()>
{
    same_boot_warm_list_restores_receipt_and_skips_only_sync(true).await
}

#[tokio::test]
async fn uncertain_local_recovery_blocks_warm_output_and_keeps_foreground_path() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory, _suite) = fixture().await?;
        peer.get("/__test/control?action=no-recovery")?;
        client.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| {
            crate::client::CacheClockEvidence::from_platform(
                "synthetic-native-boot".into(),
                1_000,
                1_000,
            )
        })));
        let invocation = command(&["openmates", "chats", "list", "--json"]);
        execute_with_foreground_recovery(
            &invocation,
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        let session = client.session().ok_or("session")?;
        // Authenticated but malformed checkpoint shape is uncertainty, not an
        // empty journal. Existing recovery must handle/report it without output.
        store
            .write_cache(
                session.hashed_email.clone(),
                "completion-pending-sync-personal".into(),
                session.master_key.clone(),
                json!(["synthetic-invalid-checkpoint"]),
            )
            .await
            .map_err(|_| "protected uncertain journal")?;
        let result = execute_with_foreground_recovery(
            &invocation,
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await;
        need(result.is_err())?;
        need(peer.get("/__test/status")?["inventory_syncs"] == 2)?;
        Ok(())
    })
    .await
    .map_err(|_| "uncertain warm fallback deadline")?
}

#[tokio::test]
async fn uncertain_command_initial_save_revokes_receipt_across_crash_before_checkpoint() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory, _suite) = fixture().await?;
        peer.get("/__test/control?action=no-recovery")?;
        let clock = std::sync::Arc::new(|| {
            crate::client::CacheClockEvidence::from_platform(
                "synthetic-native-boot".into(),
                1_000,
                1_000,
            )
        });
        client.set_chat_cache_clock_provider(Some(clock.clone()));
        let list = command(&["openmates", "chats", "list", "--json"]);
        execute_with_foreground_recovery(
            &list,
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        need(
            client
                .try_cached_default_chat_list(false)
                .map_err(|_| "fresh seed")?
                .is_some(),
        )?;
        // Execute the real command-runtime preparation + initial durable save.
        // There is deliberately no checkpoint or final operation save after
        // this fence, modeling termination after an uncertain remote effect.
        let uncertain = Invocation {
            path: vec!["chats".into(), "send".into()],
            positionals: Vec::new(),
            flags: Default::default(),
        };
        crate::session_runtime::prepare_command_cache_admission(&mut client, &uncertain);
        let cancel = CancellationToken::new();
        let admission = crate::session_runtime::FreshSessionAdmission::admit(
            &mut client,
            &store,
            secret(),
            &cancel,
        )
        .await
        .map_err(|_| "durable dispatch revocation")?;
        drop(admission);
        need(
            crate::completion_recovery_adapter::load_pending(&client, &store)
                .await
                .map_err(|_| "empty pre-checkpoint journal")?
                .is_empty(),
        )?;
        let session = store
            .load(secret())
            .await
            .map_err(|_| "saved dispatch credentials")?
            .ok_or("saved dispatch session")?;
        let application_url = client.application_url();
        drop(client); // No final persist and no checkpoint.
        let mut restarted = Client::with_options(
            &peer.endpoint,
            Some(session),
            openmates_sdk::ClientOptions {
                identity: openmates_sdk::ClientIdentity::Cli,
                app_url: Some(application_url),
                ..Default::default()
            },
        )
        .map_err(|_| "explicit restart")?;
        restarted.set_chat_cache_clock_provider(Some(clock));
        crate::session_runtime::restore_protected_cache(&mut restarted, &store, secret(), &cancel)
            .await
            .map_err(|_| "protected restart restore")?;
        let admission = crate::session_runtime::FreshSessionAdmission::admit(
            &mut restarted,
            &store,
            secret(),
            &cancel,
        )
        .await
        .map_err(|_| "fresh restart admission")?;
        drop(admission);
        need(
            restarted
                .try_cached_default_chat_list(false)
                .map_err(|_| "restart cache check")?
                .is_none(),
        )?;
        execute_with_foreground_recovery(
            &list,
            &mut restarted,
            cancel,
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        need(peer.get("/__test/status")?["inventory_syncs"] == 2)?;
        Ok(())
    })
    .await
    .map_err(|_| "uncertain dispatch restart deadline")?
}

#[tokio::test]
async fn failed_durable_revocation_refuses_foreground_dispatch() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, directory, _suite) = fixture().await?;
        peer.get("/__test/control?action=no-recovery")?;
        client.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| {
            crate::client::CacheClockEvidence::from_platform(
                "synthetic-native-boot".into(),
                1_000,
                1_000,
            )
        })));
        execute_with_foreground_recovery(
            &command(&["openmates", "chats", "list", "--json"]),
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        let credential = directory.path().join("session.json");
        std::fs::remove_file(&credential).map_err(|_| "owned credential obstruction")?;
        std::fs::create_dir(&credential).map_err(|_| "owned obstruction directory")?;
        // A foreground saved-read can discover/claim recovery jobs, so it must
        // cross the real durable revocation fence before opening any socket.
        let result = execute_with_foreground_recovery(
            &command(&["openmates", "chats", "search", "synthetic"]),
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await;
        need(result.is_err())?;
        let status = peer.get("/__test/status")?;
        need(status["inventory_syncs"] == 1 && status["claims"] == 0 && status["persists"] == 0)?;
        Ok(())
    })
    .await
    .map_err(|_| "failed dispatch revocation deadline")?
}

// PRIVATE UNRUN: native scope-equivalent explicit Personal warm-list fences.
async fn warm_personal_fixture() -> R<(Peer, Client, RuntimeStore, tempfile::TempDir)> {
    let (peer, mut client, store, directory, _suite) = fixture().await?;
    peer.get("/__test/control?action=no-recovery")?;
    client.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| {
        crate::client::CacheClockEvidence::from_platform(
            "synthetic-native-boot".into(),
            1_000,
            1_000,
        )
    })));
    execute_with_foreground_recovery(
        &command(&["openmates", "chats", "list", "--json"]),
        &mut client,
        CancellationToken::new(),
        ApplicationRecoveryContext::new(&store, secret()),
    )
    .await
    .map_err(|error| error.code())?;
    need(peer.get("/__test/status")?["inventory_syncs"] == 1)?;
    need(
        client
            .try_cached_default_chat_list(false)
            .map_err(|_| "warm fixture receipt")?
            .is_some(),
    )?;
    Ok((peer, client, store, directory))
}

#[tokio::test]
async fn explicit_personal_from_team_keeps_foreground_sync_and_restores_original_scope() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory) = warm_personal_fixture().await?;
        let original = "33333333-3333-4333-8333-333333333333";
        client
            .set_team(Some(original))
            .map_err(|_| "original Team")?;
        let invocation = command(&["openmates", "chats", "list", "--personal", "--json"]);
        crate::session_runtime::prepare_command_cache_admission(&mut client, &invocation);
        need(!crate::session_runtime::same_personal_chat_list_scope(
            &client,
            &invocation,
        ))?;
        need(
            try_warm_default_list(
                &invocation,
                &mut client,
                &ApplicationRecoveryContext::new(&store, secret()),
                &CancellationToken::new(),
            )
            .await
            .map_err(|error| error.code())?
            .is_none(),
        )?;
        let output = execute_with_foreground_recovery(
            &invocation,
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        need(serde_json::from_str::<Value>(&output.stdout).is_ok())?;
        need(peer.get("/__test/status")?["inventory_syncs"] == 2)?;
        need(client.session().and_then(|s| s.active_team_id.as_deref()) == Some(original))?;
        // The Personal read is durable before the unchanged outer Team restore.
        let saved = store
            .load(secret())
            .await
            .map_err(|_| "durable scoped credentials")?
            .ok_or("saved scoped session")?;
        need(saved.active_team_id.is_none())?;
        need(
            store
                .read_cache(
                    saved.hashed_email.clone(),
                    "sync-personal".into(),
                    saved.master_key.clone(),
                )
                .await
                .map_err(|_| "durable scoped inventory")?
                .is_some(),
        )?;
        Ok(())
    })
    .await
    .map_err(|_| "Personal transition deadline")?
}

#[tokio::test]
async fn team_and_contradictory_flags_cannot_publish_personal_warm_cache() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory) = warm_personal_fixture().await?;
        let team = "33333333-3333-4333-8333-333333333333";
        let explicit_team = command(&["openmates", "chats", "list", "--team", team, "--json"]);
        need(!crate::session_runtime::same_personal_chat_list_scope(
            &client,
            &explicit_team,
        ))?;
        need(
            try_warm_default_list(
                &explicit_team,
                &mut client,
                &ApplicationRecoveryContext::new(&store, secret()),
                &CancellationToken::new(),
            )
            .await
            .map_err(|error| error.code())?
            .is_none(),
        )?;
        // Construct the contradictory invocation directly: parser validation may
        // reject earlier, but the actual handler must also refuse before output.
        let mut contradictory = command(&["openmates", "chats", "list", "--personal", "--json"]);
        contradictory.flags.insert("team".into(), json!(team));
        need(!crate::session_runtime::same_personal_chat_list_scope(
            &client,
            &contradictory,
        ))?;
        need(
            execute_with_foreground_recovery(
                &contradictory,
                &mut client,
                CancellationToken::new(),
                ApplicationRecoveryContext::new(&store, secret()),
            )
            .await
            .is_err(),
        )?;
        need(peer.get("/__test/status")?["inventory_syncs"] == 1)?;
        crate::session_runtime::prepare_command_cache_admission(&mut client, &contradictory);
        need(
            client
                .try_cached_default_chat_list(false)
                .map_err(|_| "contradictory revocation")?
                .is_none(),
        )?;
        Ok(())
    })
    .await
    .map_err(|_| "scope refusal deadline")?
}

#[tokio::test]
async fn direct_rows_keep_explicit_personal_off_the_warm_output_path() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory) = warm_personal_fixture().await?;
        let mut snapshot = client.ciphertext_snapshot();
        let row = snapshot["chats"]
            .as_object_mut()
            .and_then(|rows| rows.values_mut().next())
            .ok_or("synthetic chat row")?;
        row["chat_visibility"] = json!("direct");
        client
            .restore_authenticated_ciphertext_snapshot(&snapshot)
            .map_err(|_| "Direct snapshot")?;
        let invocation = command(&["openmates", "chats", "list", "--personal", "--json"]);
        need(!client.supports_cached_default_chat_list())?;
        need(!crate::session_runtime::same_personal_chat_list_scope(
            &client,
            &invocation,
        ))?;
        crate::session_runtime::prepare_command_cache_admission(&mut client, &invocation);
        need(
            try_warm_default_list(
                &invocation,
                &mut client,
                &ApplicationRecoveryContext::new(&store, secret()),
                &CancellationToken::new(),
            )
            .await
            .map_err(|error| error.code())?
            .is_none(),
        )?;
        need(peer.get("/__test/status")?["inventory_syncs"] == 1)?;
        Ok(())
    })
    .await
    .map_err(|_| "Direct refusal deadline")?
}

#[tokio::test]
async fn pending_or_uncertain_checkpoint_blocks_explicit_personal_warm_output() -> R<()> {
    tokio::time::timeout(Duration::from_secs(15), async {
        let (peer, mut client, store, _directory) = warm_personal_fixture().await?;
        let invocation = command(&["openmates", "chats", "list", "--personal", "--json"]);
        let job = "44444444-4444-4444-8444-444444444444";
        let checkpoint = json!({"protocol_version":1,"api_url":peer.endpoint,
            "owner_id":client.user()["id"],"team_id":null,
            "job":{"kind":"main","job_id":job,"chat_id":"22222222-2222-4222-8222-222222222222",
                "turn_id":"33333333-3333-4333-8333-333333333333",
                "assistant_message_id":"55555555-5555-4555-8555-555555555555",
                "task_id":null,"stage":null,"chat_key_version":1},
            "encrypted_candidate":{},"wrapped_chat_key":null,"canonical_ciphertext":false});
        for uncertain in [false, true] {
            let pending = if uncertain {
                json!(["synthetic-malformed-journal"])
            } else {
                json!({(job):checkpoint})
            };
            let session = client.session().ok_or("pending session")?;
            store
                .write_cache(
                    session.hashed_email.clone(),
                    "completion-pending-sync-personal".into(),
                    session.master_key.clone(),
                    pending,
                )
                .await
                .map_err(|_| "protected pending checkpoint")?;
            if !uncertain {
                need(
                    crate::completion_recovery_adapter::load_pending(&client, &store)
                        .await
                        .map_err(|_| "valid owned pending journal")?
                        .len()
                        == 1,
                )?;
            }
            // This receipt would be readable if the native pending guard were
            // removed: neither malformed nor real owned pending means empty.
            need(
                client
                    .try_cached_default_chat_list(false)
                    .map_err(|_| "otherwise warm")?
                    .is_some(),
            )?;
            need(
                try_warm_default_list(
                    &invocation,
                    &mut client,
                    &ApplicationRecoveryContext::new(&store, secret()),
                    &CancellationToken::new(),
                )
                .await
                .map_err(|error| error.code())?
                .is_none(),
            )?;
        }
        need(peer.get("/__test/status")?["inventory_syncs"] == 1)?;
        Ok(())
    })
    .await
    .map_err(|_| "pending Personal refusal deadline")?
}

#[tokio::test]
async fn cancelled_explicit_personal_and_failed_warm_save_publish_no_output() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let invocation = command(&["openmates", "chats", "list", "--personal", "--json"]);
        {
            let (peer, mut client, store, _directory) = warm_personal_fixture().await?;
            let cancel = CancellationToken::new();
            cancel.cancel();
            need(matches!(
                execute_with_foreground_recovery(
                    &invocation,
                    &mut client,
                    cancel,
                    ApplicationRecoveryContext::new(&store, secret())
                )
                .await,
                Err(CliError::Client(Error::Cancelled))
            ))?;
            let status = peer.get("/__test/status")?;
            need(
                status["inventory_syncs"] == 1 && status["claims"] == 0 && status["persists"] == 0,
            )?;
        }
        // Cancellation revokes freshness. Use an independently admitted warm
        // fixture so the durability branch actually reaches its attempted save.
        let (peer, mut client, store, directory) = warm_personal_fixture().await?;
        need(
            client
                .try_cached_default_chat_list(false)
                .map_err(|_| "warm save precondition")?
                .is_some(),
        )?;
        // Obstruct only final sync-cache publication. A broken session envelope
        // also blocks pending-checkpoint inspection and correctly selects the
        // foreground fallback before a warm output can be prepared.
        use sha2::{Digest, Sha256};
        let owner = &client.session().ok_or("warm cache owner")?.hashed_email;
        let cache = directory.path().join(format!(
            "cache-{:x}-{:x}.json",
            Sha256::digest(owner.as_bytes()),
            Sha256::digest(b"sync-personal")
        ));
        need(cache.is_file())?;
        std::fs::remove_file(&cache).map_err(|_| "owned warm cache obstruction")?;
        std::fs::create_dir(&cache).map_err(|_| "owned warm cache obstruction directory")?;
        need(
            crate::completion_recovery_adapter::load_pending(&client, &store)
                .await
                .map_err(|_| "unobstructed pending-checkpoint precondition")?
                .is_empty(),
        )?;
        need(
            try_warm_default_list(
                &invocation,
                &mut client,
                &ApplicationRecoveryContext::new(&store, secret()),
                &CancellationToken::new(),
            )
            .await
            .is_err(),
        )?;
        let status = peer.get("/__test/status")?;
        need(status["inventory_syncs"] == 1 && status["claims"] == 0 && status["persists"] == 0)?;
        Ok(())
    })
    .await
    .map_err(|_| "warm cancellation and durability deadline")?
}

async fn handoff_idle_list_scope(personal: bool) -> R<()> {
    tokio::time::timeout(Duration::from_secs(15), async {
        let (peer, mut client, store, _directory, _suite) = fixture().await?;
        peer.get("/__test/control?action=no-recovery")?;
        let cancel = CancellationToken::new();
        client.set_operation_cancel(cancel.clone());
        let invocation = if personal {
            command(&["openmates", "chats", "list", "--personal", "--json"])
        } else {
            command(&["openmates", "chats", "list", "--json"])
        };
        crate::session_runtime::prepare_command_cache_admission(&mut client, &invocation);
        let before = peer.get("/__test/status")?["auth_checks"]
            .as_u64()
            .ok_or("auth counter")?;
        let admission = crate::session_runtime::FreshSessionAdmission::admit(
            &mut client,
            &store,
            secret(),
            &cancel,
        )
        .await
        .map_err(|_| "actual fresh durable admission")?;
        need(!admission.user().map_err(|_| "admitted owner")?["id"].is_null())?;
        admission
            .prepare_recovery()
            .map_err(|_| "same operation handoff")?;
        let output = execute_with_foreground_recovery(
            &invocation,
            &mut client,
            cancel,
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        need(serde_json::from_str::<Value>(&output.stdout).is_ok())?;
        let status = peer.get("/__test/status")?;
        need(status["auth_checks"].as_u64() == Some(before + 1))?;
        need(status["inventory_syncs"] == 1 && status["claims"] == 0 && status["persists"] == 0)?;
        // A new explicit command operation must authenticate freshly, including
        // when the previous command's credentials and sync cache were saved.
        let next = CancellationToken::new();
        client.set_operation_cancel(next.clone());
        let second = crate::session_runtime::FreshSessionAdmission::admit(
            &mut client,
            &store,
            secret(),
            &next,
        )
        .await
        .map_err(|_| "next fresh admission")?;
        drop(second);
        need(peer.get("/__test/status")?["auth_checks"].as_u64() == Some(before + 2))?;
        Ok(())
    })
    .await
    .map_err(|_| "fresh auth handoff deadline")?
}

#[tokio::test]
async fn durable_live_admission_hands_off_one_auth_to_first_idle_recovery_sync() -> R<()> {
    handoff_idle_list_scope(false).await
}

#[tokio::test]
async fn explicit_personal_durable_live_admission_hands_off_one_auth_to_first_idle_recovery_sync()
-> R<()> {
    handoff_idle_list_scope(true).await
}

#[tokio::test]
async fn failed_initial_handoff_save_refuses_all_recovery_transport() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, directory, _suite) = fixture().await?;
        peer.get("/__test/control?action=no-recovery")?;
        let cancel = CancellationToken::new();
        client.set_operation_cancel(cancel.clone());
        let session = directory.path().join("session.json");
        std::fs::remove_file(&session).map_err(|_| "owned credential obstruction")?;
        std::fs::create_dir(&session).map_err(|_| "owned obstruction directory")?;
        need(
            crate::session_runtime::FreshSessionAdmission::admit(
                &mut client,
                &store,
                secret(),
                &cancel,
            )
            .await
            .is_err(),
        )?;
        let status = peer.get("/__test/status")?;
        need(status["connections"] == 0)?;
        need(status["inventory_syncs"] == 0 && status["claims"] == 0 && status["persists"] == 0)?;
        Ok(())
    })
    .await
    .map_err(|_| "failed admission no-dispatch deadline")?
}

async fn handoff_settled_show_scope(personal: bool) -> R<()> {
    tokio::time::timeout(Duration::from_secs(20), async {
        let (peer, mut client, store, _directory, suite) = fixture().await?;
        // Bootstrap through the existing genuine recovery flow, so the peer has
        // real committed ciphertext instead of fabricating selected history.
        execute_with_foreground_recovery(
            &command(&["openmates", "chats", "list", "--json"]),
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        client.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| {
            crate::client::CacheClockEvidence::from_platform(
                "synthetic-handoff-boot".into(),
                1_000,
                1_000,
            )
        })));
        let before = peer.get("/__test/status")?;
        let cancel = CancellationToken::new();
        client.set_operation_cancel(cancel.clone());
        let id = field(&suite["protocol"], "initial_chat_id")?;
        let invocation = if personal {
            command(&["openmates", "chats", "show", id, "--personal", "--json"])
        } else {
            command(&["openmates", "chats", "show", id, "--json"])
        };
        crate::session_runtime::prepare_command_cache_admission(&mut client, &invocation);
        let admission = crate::session_runtime::FreshSessionAdmission::admit(
            &mut client,
            &store,
            secret(),
            &cancel,
        )
        .await
        .map_err(|_| "settled show fresh admission")?;
        need(
            admission.user().map_err(|_| "fresh owner")?["id"].as_str()
                == Some(field(&suite["account"], "owner_id")?),
        )?;
        admission.prepare_recovery().map_err(|_| "show handoff")?;
        let output = execute_with_foreground_recovery(
            &invocation,
            &mut client,
            cancel,
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        need(
            output
                .stdout
                .contains(field(&suite["protocol"], "sealed_content")?),
        )?;
        let after = peer.get("/__test/status")?;
        need(after["auth_checks"].as_u64() == before["auth_checks"].as_u64().map(|n| n + 1))?;
        // Like TypeScript, show runs one correlated global inventory sync on
        // its single recovery socket (no separate selected discovery socket).
        need(
            after["inventory_syncs"].as_u64() == before["inventory_syncs"].as_u64().map(|n| n + 1),
        )?;
        need(after["claims"] == before["claims"] && after["persists"] == before["persists"])?;
        // The complete empty batch plus a list-neutral selected read rebinds
        // the inventory's receipt, so the next list needs no network sync.
        need(
            client
                .try_cached_default_chat_list(false)
                .map_err(|_| "settled show receipt")?
                .is_some(),
        )?;
        let saved = store
            .load(secret())
            .await
            .map_err(|_| "final full read session")?
            .ok_or("saved session")?;
        let mut restarted = Client::with_options(
            &peer.endpoint,
            Some(saved),
            openmates_sdk::ClientOptions {
                identity: openmates_sdk::ClientIdentity::Cli,
                app_url: Some(client.application_url()),
                ..Default::default()
            },
        )
        .map_err(|_| "next command Client")?;
        restarted.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| {
            crate::client::CacheClockEvidence::from_platform(
                "synthetic-handoff-boot".into(),
                1_000,
                1_000,
            )
        })));
        let next = CancellationToken::new();
        restarted.set_operation_cancel(next.clone());
        crate::session_runtime::restore_protected_cache(&mut restarted, &store, secret(), &next)
            .await
            .map_err(|_| "full read protected restart")?;
        // Preserve the benchmark's independent untimed whoami admission.
        let whoami = command(&["openmates", "whoami", "--json"]);
        crate::session_runtime::prepare_command_cache_admission(&mut restarted, &whoami);
        let who = crate::session_runtime::FreshSessionAdmission::admit(
            &mut restarted,
            &store,
            secret(),
            &next,
        )
        .await
        .map_err(|_| "untimed whoami admission")?;
        let who_output = who.whoami_output(&whoami).map_err(|error| error.code())?;
        need(serde_json::from_str::<Value>(&who_output.stdout).is_ok())?;
        let after_who = peer.get("/__test/status")?;
        need(after_who["auth_checks"].as_u64() == after["auth_checks"].as_u64().map(|n| n + 1))?;
        need(after_who["inventory_syncs"] == after["inventory_syncs"])?;
        let next = CancellationToken::new();
        restarted.set_operation_cancel(next.clone());
        let list = if personal {
            command(&[
                "openmates",
                "chats",
                "list",
                "--personal",
                "--limit",
                "100",
                "--json",
            ])
        } else {
            command(&["openmates", "chats", "list", "--limit", "100", "--json"])
        };
        crate::session_runtime::prepare_command_cache_admission(&mut restarted, &list);
        let fresh = crate::session_runtime::FreshSessionAdmission::admit(
            &mut restarted,
            &store,
            secret(),
            &next,
        )
        .await
        .map_err(|_| "next list fresh admission")?;
        // Match command_runtime's real saved-read dispatch. The handoff stays
        // unused because the warm receipt serves this list without a socket.
        fresh.prepare_recovery().map_err(|_| "next list durable auth handoff")?;
        let listed = execute_with_foreground_recovery(
            &list,
            &mut restarted,
            next,
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        need(serde_json::from_str::<Value>(&listed.stdout).is_ok())?;
        let listed_status = peer.get("/__test/status")?;
        need(
            listed_status["auth_checks"].as_u64()
                == after_who["auth_checks"].as_u64().map(|n| n + 1),
        )?;
        need(listed_status["inventory_syncs"] == after["inventory_syncs"])?;
        need(
            listed_status["claims"] == after["claims"]
                && listed_status["persists"] == after["persists"],
        )?;
        Ok(())
    })
    .await
    .map_err(|_| "settled show auth count deadline")?
}

#[tokio::test]
async fn settled_show_uses_one_fresh_command_auth_and_one_sync_then_warm_list() -> R<()> {
    handoff_settled_show_scope(false).await
}

#[tokio::test]
async fn explicit_personal_settled_show_uses_one_fresh_command_auth_and_one_sync_then_warm_list() -> R<()>
{
    handoff_settled_show_scope(true).await
}

async fn settled_full_read_fixture() -> R<(Peer, Client, RuntimeStore, tempfile::TempDir, Value)> {
    let (peer, mut client, store, directory, suite) = fixture().await?;
    execute_with_foreground_recovery(
        &command(&["openmates", "chats", "list", "--json"]),
        &mut client,
        CancellationToken::new(),
        ApplicationRecoveryContext::new(&store, secret()),
    )
    .await
    .map_err(|error| error.code())?;
    client.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| {
        crate::client::CacheClockEvidence::from_platform("synthetic-full-read".into(), 1_000, 1_000)
    })));
    Ok((peer, client, store, directory, suite))
}
#[tokio::test]
async fn show_observing_a_changed_row_keeps_the_next_list_on_its_sync_path() -> R<()> {
    tokio::time::timeout(Duration::from_secs(20), async {
        let (peer, mut client, store, _directory, suite) = settled_full_read_fixture().await?;
        // The selected metadata row now renders differently (canonical numeric
        // read_details clocks) from the row the inventory sync just stored.
        peer.get("/__test/control?action=structured-history")?;
        let before = peer.get("/__test/status")?;
        let id = field(&suite["protocol"], "initial_chat_id")?;
        let output = execute_with_foreground_recovery(
            &command(&["openmates", "chats", "show", id, "--personal", "--json"]),
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        need(output.exit_code == 0 && serde_json::from_str::<Value>(&output.stdout).is_ok())?;
        let after = peer.get("/__test/status")?;
        need(
            after["inventory_syncs"].as_u64() == before["inventory_syncs"].as_u64().map(|n| n + 1),
        )?;
        need(
            client
                .try_cached_default_chat_list(false)
                .map_err(|_| "changed row receipt")?
                .is_none(),
        )?;
        execute_with_foreground_recovery(
            &command(&["openmates", "chats", "list", "--personal", "--json"]),
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        let listed = peer.get("/__test/status")?;
        need(
            listed["inventory_syncs"].as_u64() == after["inventory_syncs"].as_u64().map(|n| n + 1),
        )?;
        Ok(())
    })
    .await
    .map_err(|_| "changed show deadline")?
}
#[tokio::test]
async fn other_chat_pending_checkpoint_disqualifies_selected_read_global_receipt() -> R<()> {
    tokio::time::timeout(Duration::from_secs(15), async {
        let (peer, mut client, store, _directory, suite) = settled_full_read_fixture().await?;
        let job = "44444444-4444-4444-8444-444444444444";
        let other = "77777777-7777-4777-8777-777777777777";
        let checkpoint = json!({"protocol_version":1,"api_url":peer.endpoint,
            "owner_id":client.user()["id"],"team_id":null,
            "job":{"kind":"main","job_id":job,"chat_id":other,
                "turn_id":"33333333-3333-4333-8333-333333333333",
                "assistant_message_id":"55555555-5555-4555-8555-555555555555",
                "task_id":null,"stage":null,"chat_key_version":1},
            "encrypted_candidate":{},"wrapped_chat_key":null,"canonical_ciphertext":false});
        let session = client.session().ok_or("pending owner")?;
        store
            .write_cache(
                session.hashed_email.clone(),
                "completion-pending-sync-personal".into(),
                session.master_key.clone(),
                json!({(job):checkpoint}),
            )
            .await
            .map_err(|_| "other pending journal")?;
        need(
            crate::completion_recovery_adapter::load_pending(&client, &store)
                .await
                .map_err(|_| "valid other checkpoint")?
                .len()
                == 1,
        )?;
        let before = peer.get("/__test/status")?;
        let id = field(&suite["protocol"], "initial_chat_id")?;
        let output = execute_with_foreground_recovery(
            &command(&["openmates", "chats", "messages", id, "--personal", "--json"]),
            &mut client,
            CancellationToken::new(),
            ApplicationRecoveryContext::new(&store, secret()),
        )
        .await
        .map_err(|error| error.code())?;
        need(
            output
                .stdout
                .contains(field(&suite["protocol"], "sealed_content")?),
        )?;
        need(
            client
                .try_cached_default_chat_list(false)
                .map_err(|_| "no global receipt")?
                .is_none(),
        )?;
        need(
            crate::completion_recovery_adapter::load_pending(&client, &store)
                .await
                .map_err(|_| "other checkpoint retained")?
                .len()
                == 1,
        )?;
        let after = peer.get("/__test/status")?;
        need(after["claims"] == before["claims"] && after["persists"] == before["persists"])?;
        Ok(())
    })
    .await
    .map_err(|_| "other pending full read deadline")?
}
#[tokio::test]
async fn complete_history_final_save_failure_wipes_output_and_keeps_disk_revoked() -> R<()> {
    tokio::time::timeout(Duration::from_secs(15), async {
        let (peer, mut client, store, directory, suite) = settled_full_read_fixture().await?;
        let cancel = CancellationToken::new();
        client.set_operation_cancel(cancel.clone());
        crate::session_runtime::revoke_chat_cache_before_dispatch(
            &mut client,
            &store,
            secret(),
            &cancel,
        )
        .await
        .map_err(|_| "actual durable prerevoke")?;
        let id = field(&suite["protocol"], "initial_chat_id")?;
        let context = ApplicationRecoveryContext::new(&store, secret());
        // This test exercises failed publication AFTER a real global proof was
        // minted. Selected-only discovery intentionally cannot supply that proof.
        let inventory_before = peer.get("/__test/status")?["phase2_inventory_syncs"]
            .as_u64().ok_or("global inventory counter")?;
        let (admission, proof) = recover_saved_read(
            &mut client,
            &SavedReadRecovery::Inventory,
            &context,
            &cancel,
            true,
        )
        .await
        .map_err(|_| "complete no effects discovery")?;
        need(proof.is_some())?;
        need(peer.get("/__test/status")?["phase2_inventory_syncs"].as_u64()
            == Some(inventory_before + 1))?;
        let mut output = execute_context_with_inventory(
            &command(&["openmates", "chats", "show", id, "--json", "--all"]),
            &mut client,
            cancel.clone(),
            Some(&store),
            proof,
        )
        .await
        .map_err(|error| error.code())?;
        need(!output.stdout.is_empty())?;
        need(
            client
                .try_cached_default_chat_list(false)
                .map_err(|_| "complete full read receipt")?
                .is_some(),
        )?;
        let session = client.session().ok_or("current ciphertext owner")?;
        let durable = store
            .read_cache(
                session.hashed_email.clone(),
                "sync-personal".into(),
                session.master_key.clone(),
            )
            .await
            .map_err(|_| "prerevoked disk ciphertext")?
            .ok_or("existing disk snapshot")?;
        need(durable.get("chat_list_freshness").is_none())?;
        use sha2::{Digest, Sha256};
        let owner = &client.session().ok_or("final cache owner")?.hashed_email;
        let cache = directory.path().join(format!(
            "cache-{:x}-{:x}.json",
            Sha256::digest(owner.as_bytes()),
            Sha256::digest(b"sync-personal")
        ));
        need(cache.is_file())?;
        std::fs::remove_file(&cache).map_err(|_| "owned final cache file")?;
        std::fs::create_dir(&cache).map_err(|_| "owned final cache obstruction")?;
        need(
            crate::completion_recovery_adapter::load_pending(&client, &store)
                .await
                .map_err(|_| "pending unaffected")?
                .is_empty(),
        )?;
        need(
            persist_saved_read_output(&mut output, &mut client, &context, &admission, &cancel)
                .await
                .is_err(),
        )?;
        need(output.stdout.is_empty() && output.stderr.is_empty())?;
        // The failed cache publication cannot turn the pre-effect disk state
        // into a readable receipt, even though credential publication succeeded.
        let saved = store
            .load(secret())
            .await
            .map_err(|_| "saved credential")?
            .ok_or("credential retained")?;
        let mut restarted =
            Client::new(&peer.endpoint, Some(saved)).map_err(|_| "restart after final failure")?;
        need(
            crate::session_runtime::restore_protected_cache(
                &mut restarted,
                &store,
                secret(),
                &CancellationToken::new(),
            )
            .await
            .is_err(),
        )?;
        need(
            restarted
                .try_cached_default_chat_list(false)
                .map_err(|_| "no receipt after failure")?
                .is_none(),
        )?;
        need(peer.get("/__test/status")?["failure"].is_null())?;
        Ok(())
    })
    .await
    .map_err(|_| "full read failed durability deadline")?
}

#[tokio::test]
async fn post_mint_journal_error_cancel_and_future_drop_revoke_before_real_error_cleanup_save()
-> R<()> {
    tokio::time::timeout(Duration::from_secs(30),async {
        for failure in 0..3 {
            let (peer,mut client,store,_directory,suite)=settled_full_read_fixture().await?;
            let cancel=CancellationToken::new();client.set_operation_cancel(cancel.clone());
            crate::session_runtime::revoke_chat_cache_before_dispatch(&mut client,&store,secret(),&cancel).await.map_err(|_|"pre-effect durable revoke")?;
            let id=field(&suite["protocol"],"initial_chat_id")?;
            let context=ApplicationRecoveryContext::new(&store,secret());
            // Preserve the post-mint error/cancel/drop oracle using a genuine
            // global inventory setup, never a selected-only absence substitute.
            let inventory_before=peer.get("/__test/status")?["phase2_inventory_syncs"].as_u64().ok_or("global inventory counter")?;
            let (admission,proof)=recover_saved_read(&mut client,&SavedReadRecovery::Inventory,&context,&cancel,true).await.map_err(|_|"post-mint discovery")?;
            need(proof.is_some())?;
            need(peer.get("/__test/status")?["phase2_inventory_syncs"].as_u64()==Some(inventory_before+1))?;
            let mut output=execute_context_with_inventory(&command(&["openmates","chats","show",id,"--json","--all"]),&mut client,cancel.clone(),Some(&store),proof).await.map_err(|error|error.code())?;
            need(client.try_cached_default_chat_list(false).map_err(|_|"minted receipt precondition")?.is_some())?;
            let session=client.session().ok_or("journal fixture owner")?.clone();
            let (_registration,gate)=final_read_journal_test_hook::install(&cancel);
            {
                let publication=persist_saved_read_output(&mut output,&mut client,&context,&admission,&cancel);
                tokio::pin!(publication);
                tokio::select! {
                    biased;
                    _=gate.persisted.notified()=>{},
                    result=&mut publication=>{need(result.is_err())?;return Err("publication escaped post-mint barrier");},
                }
                match failure {
                    0=>{
                        store.write_cache(session.hashed_email.clone(),"completion-pending-sync-personal".into(),session.master_key.clone(),json!(["malformed-after-read"])).await.map_err(|_|"new malformed global journal")?;
                        gate.resume.notify_one();need(publication.await.is_err())?;
                    }
                    1=>{cancel.cancel();gate.resume.notify_one();need(publication.await.is_err())?;}
                    _=>{} // Drop the actual in-flight final-publication future.
                }
            }
            need(output.stdout.is_empty()&&output.stderr.is_empty())?;
            need(client.ciphertext_snapshot().get("chat_list_freshness").is_none())?;
            // Exact command_runtime generic-error cleanup boundary: it saves the
            // mutated Client even after the original read returned an error.
            crate::session_runtime::persist(&mut client,&store,secret()).await.map_err(|_|"real generic error cleanup save")?;
            let saved=store.load(secret()).await.map_err(|_|"cleanup saved credentials")?.ok_or("cleanup session")?;
            let mut restarted=Client::new(&peer.endpoint,Some(saved)).map_err(|_|"cleanup restart")?;
            crate::session_runtime::restore_protected_cache(&mut restarted,&store,secret(),&CancellationToken::new()).await.map_err(|_|"cleanup protected snapshot restore")?;
            need(restarted.ciphertext_snapshot().get("chat_list_freshness").is_none())?;
            need(restarted.try_cached_default_chat_list(false).map_err(|_|"cleanup cannot restore warm receipt")?.is_none())?;
        }
        Ok(())
    }).await.map_err(|_|"post-mint cleanup guard deadline")?
}

// The actual TUI adapter uses one existing authenticated empty discovery only;
// these synthetic peers exercise the real SDK socket and encrypted Store path.
struct TuiBatchPersistence<'a> {
    inner: CanonicalReadPersistence<'a>,
    mode: &'static str,
    calls: usize,
}
impl crate::completion_recovery_adapter::CanonicalRecoveryPersistence for TuiBatchPersistence<'_> {
    fn persist_reconciled_canonical<'a>(
        &'a mut self,
        client: &'a mut Client,
        chat_id: &'a str,
        cancel: &'a CancellationToken,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<(), Error>> + Send + 'a>> {
        use crate::completion_recovery_adapter::CanonicalRecoveryPersistence;
        Box::pin(async move {
            self.inner.persist_reconciled_canonical(client, chat_id, cancel).await?;
            self.calls += 1;
            match self.mode {
                "io-after-durable-save" => Err(Error::Io),
                "cancel-after-durable-save" => { cancel.cancel(); Err(Error::Cancelled) },
                "owner-cleared-after-durable-save" => { client.forget_session(); Err(Error::Cancelled) },
                _ => Ok(()),
            }
        })
    }
}
async fn tui_batch_case(selected: bool, empty: bool, mode: &'static str) -> R<()> {
    let (peer, mut client, store, _directory, suite) = fixture().await?;
    if empty { peer.get("/__test/control?action=no-recovery")?; }
    let cancel = CancellationToken::new();
    client.set_operation_cancel(cancel.clone());
    client.set_foreground_completion_recovery(true).map_err(|_| "explicit TUI foreground")?;
    let admission = RecoveryReadAdmission::capture(&client, &store, &cancel).map_err(|_| "TUI owner scope")?;
    let context = ApplicationRecoveryContext::new(&store, secret());
    let mut canonical = TuiBatchPersistence {
        inner: CanonicalReadPersistence { context: &context, admission: &admission, after_persist: None },
        mode,
        calls: 0,
    };
    let id = if selected { "22222222-2222-4222-8222-222222222222" } else { "66666666-6666-4666-8666-666666666666" };
    let result = crate::completion_recovery_adapter::pump_selected_and_global_completion_recovery(
        &mut client, &store, id.into(), &cancel, &mut canonical,
    ).await;
    let status = peer.get("/__test/status")?;
    need(status["failure"].is_null() && status["admissions"] == 0)?;
    if matches!(mode, "cancel-after-durable-save" | "owner-cleared-after-durable-save") {
        need(matches!(result, Err(Error::Cancelled)))?;
        need(status["inventory_syncs"] == 1 && status["claims"] == 1 && status["persists"] == 1)?;
        need(canonical.calls == 1)?;
        if mode == "cancel-after-durable-save" {
            need(crate::completion_recovery_adapter::load_pending(&client, &store).await.map_err(|_| "cancelled accepted checkpoint preserved")?.len() == 1)?;
        } else {
            need(client.session().is_none())?;
            crate::session_runtime::persist(&mut client, &store, secret()).await.map_err(|_| "cleared owner durable revocation")?;
            need(store.load(secret()).await.map_err(|_| "owner cannot resurrect")?.is_none())?;
        }
        return Ok(());
    }
    let outcome = result.map_err(|_| "TUI selected/global batch")?;
    // Empty evidence is consumed locally, never returned for cache promotion.
    need(outcome.fresh_inventory.is_none())?;
    if empty {
        need(outcome.attempted == 0 && outcome.completed == 0 && outcome.deferred == 0 && !outcome.canonical_changed)?;
        need(canonical.calls == 0)?;
        need(status["auth_checks"] == 2 && status["inventory_syncs"] == 1
            && status["inventory_discovery"] == 1 && status["metadata_discovery"] == 1
            && status["task_inventory_discovery"] == 1 && status["claims"] == 0 && status["persists"] == 0)?;
        need(client.try_cached_default_chat_list(false).map_err(|_| "no cache authority from empty reuse")?.is_none())?;
    } else if mode == "io-after-durable-save" {
        // Resume still needs its fresh authoritative TERMINAL claim. There is
        // one accepted persistence effect, not one claim request in total.
        need(status["inventory_syncs"] == 2 && status["claims"] == 2 && status["persists"] == 1)?;
        need(outcome.completed == 0 && outcome.deferred == 2 && outcome.attempted == 2)?;
        need(canonical.calls == 2)?;
        need(crate::completion_recovery_adapter::load_pending(&client, &store).await.map_err(|_| "ambiguous durable checkpoint retained")?.len() == 1)?;
    } else {
        need(status["inventory_syncs"] == 2 && status["claims"] == 1 && status["persists"] == 1)?;
        need(outcome.completed == 1 && outcome.attempted == 1 && outcome.deferred == 0 && outcome.canonical_changed)?;
        need(canonical.calls == 1)?;
        need(crate::completion_recovery_adapter::load_pending(&client, &store).await.map_err(|_| "completed checkpoint cleared")?.is_empty())?;
    }
    client.set_foreground_completion_recovery(false).map_err(|_| "end TUI foreground")?;
    let chat = client.open_chat("22222222-2222-4222-8222-222222222222").await.map_err(|_| "unchanged selected canonical read")?;
    if empty {
        need(chat.messages.is_empty())?;
    } else {
        let expected = field(&suite["protocol"], "sealed_content")?;
        need(chat.messages.iter().any(|message| message.content.contains(expected)))?;
    }
    let after = peer.get("/__test/status")?;
    need(after["inventory_syncs"] == status["inventory_syncs"] && after["claims"] == status["claims"] && after["persists"] == status["persists"])?;
    Ok(())
}
// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted,auth.session.authoritative-enforcement
#[tokio::test]
async fn tui_empty_batch_uses_one_real_correlated_discovery_without_cache_promotion() -> R<()> {
    tokio::time::timeout(Duration::from_secs(15), tui_batch_case(true, true, "normal")).await.map_err(|_| "one-discovery TUI deadline")?
}
#[tokio::test]
async fn tui_selected_recovery_retains_global_pump_and_exactly_one_accepted_effect() -> R<()> {
    tokio::time::timeout(Duration::from_secs(15), tui_batch_case(true, false, "normal")).await.map_err(|_| "selected/global TUI deadline")?
}
#[tokio::test]
async fn tui_other_chat_recovery_is_not_hidden_by_empty_selected_work() -> R<()> {
    tokio::time::timeout(Duration::from_secs(15), tui_batch_case(false, false, "normal")).await.map_err(|_| "global fairness TUI deadline")?
}
#[tokio::test]
async fn tui_ambiguous_durability_keeps_checkpoint_and_both_recovery_passes() -> R<()> {
    tokio::time::timeout(Duration::from_secs(15), tui_batch_case(true, false, "io-after-durable-save")).await.map_err(|_| "durability TUI deadline")?
}
#[tokio::test]
async fn tui_cancel_after_accepted_durable_effect_cannot_admit_global_work() -> R<()> {
    tokio::time::timeout(Duration::from_secs(15), tui_batch_case(true, false, "cancel-after-durable-save")).await.map_err(|_| "cancel TUI deadline")?
}
#[tokio::test]
async fn tui_owner_clear_after_accepted_durable_effect_cannot_admit_global_work() -> R<()> {
    tokio::time::timeout(Duration::from_secs(15), tui_batch_case(true, false, "owner-cleared-after-durable-save")).await.map_err(|_| "owner clear TUI deadline")?
}
#[tokio::test]
async fn tui_precancelled_batch_does_not_open_a_discovery_socket() -> R<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        let (peer, mut client, store, _directory, _suite) = fixture().await?;
        let cancel = CancellationToken::new();
        client.set_foreground_completion_recovery(true).map_err(|_| "foreground")?;
        let admission = RecoveryReadAdmission::capture(&client, &store, &cancel).map_err(|_| "admission")?;
        let context = ApplicationRecoveryContext::new(&store, secret());
        let mut canonical = CanonicalReadPersistence { context: &context, admission: &admission, after_persist: None };
        cancel.cancel();
        need(matches!(crate::completion_recovery_adapter::pump_selected_and_global_completion_recovery(&mut client, &store,
            "22222222-2222-4222-8222-222222222222".into(), &cancel, &mut canonical).await, Err(Error::Cancelled)))?;
        let status = peer.get("/__test/status")?;
        need(status["inventory_syncs"] == 0 && status["claims"] == 0 && status["persists"] == 0)?;
        Ok(())
    }).await.map_err(|_| "pre-cancel TUI deadline")?
}
#[tokio::test]
async fn tui_malformed_pending_record_cannot_be_covered_by_empty_network_discovery() -> R<()> {
    tokio::time::timeout(Duration::from_secs(15), async {
        let (peer, mut client, store, _directory, _suite) = fixture().await?;
        peer.get("/__test/control?action=no-recovery")?;
        client.set_foreground_completion_recovery(true).map_err(|_| "foreground")?;
        let cancel = CancellationToken::new();
        let session = client.session().ok_or("session")?;
        let owner = session.hashed_email.clone();
        let master = session.master_key.clone();
        let key = format!("completion-pending-{}", crate::session_runtime::cache_key(session));
        let bad = json!({"not-a-checkpoint":"preserve"});
        store.write_cache(owner.clone(), key.clone(), master.clone(), bad.clone()).await.map_err(|_| "synthetic malformed encrypted pending record")?;
        let admission = RecoveryReadAdmission::capture(&client, &store, &cancel).map_err(|_| "admission")?;
        let context = ApplicationRecoveryContext::new(&store, secret());
        let mut canonical = CanonicalReadPersistence { context: &context, admission: &admission, after_persist: None };
        need(matches!(crate::completion_recovery_adapter::pump_selected_and_global_completion_recovery(&mut client, &store,
            "22222222-2222-4222-8222-222222222222".into(), &cancel, &mut canonical).await,
            Err(Error::Unavailable {code:"completion_recovery_checkpoint_invalid", ..})))?;
        need(store.read_cache(owner, key, master).await.map_err(|_| "preserved pending read")? == Some(bad))?;
        let status = peer.get("/__test/status")?;
        need(status["inventory_syncs"] == 1 && status["claims"] == 0 && status["persists"] == 0)?;
        Ok(())
    }).await.map_err(|_| "malformed pending TUI deadline")?
}

// Original full-read policy across the actual native durable output boundary.
#[path="full_chat_read_policy_tests.rs"]
mod full_chat_read_policy;


#[test]
fn list_stage_observer_default_none_cannot_run_a_callback() {
    notify_list_stage(None, ListReadDiagnosticStage::ForegroundStarted);
}

#[test]
fn list_stage_observer_panic_does_not_escape_or_replace_the_original_result() {
    let callback = |_: ListReadDiagnosticStage| panic!("synthetic diagnostic observer refusal");
    let original: Result<&str, &str> = Err("original-operation-error");
    notify_list_stage(Some(&callback), ListReadDiagnosticStage::ForegroundStarted);
    assert_eq!(original, Err("original-operation-error"));
}

#[test]
fn list_stage_observer_drop_panicking_payload_cannot_replace_original_result() {
    struct DropPanic;
    impl Drop for DropPanic { fn drop(&mut self) { panic!("synthetic payload drop refusal"); } }
    let callback = |_: ListReadDiagnosticStage| std::panic::panic_any(DropPanic);
    let original: Result<&str, &str> = Err("original-operation-error");
    notify_list_stage(Some(&callback), ListReadDiagnosticStage::ForegroundStarted);
    assert_eq!(original, Err("original-operation-error"));
}
