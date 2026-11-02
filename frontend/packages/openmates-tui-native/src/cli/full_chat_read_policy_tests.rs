//! Actual native read/serialization/final-persistence path. Synthetic loopback
//! fixture only, authored UNRUN; no policy or output bypass is used by the test.
use super::*;
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,cli.surface.semantic-parity
#[tokio::test]
async fn original_full_read_gate_replacement_cannot_release_after_durable_wait() -> R<()> {
    tokio::time::timeout(Duration::from_secs(40), async {
        for (revoked, all) in [(false, false), (true, false), (false, true), (true, true)] {
            let (_peer, mut client, store, _directory, suite) = settled_full_read_fixture().await?;
            let cancel = CancellationToken::new();
            client.set_operation_cancel(cancel.clone());
            let id = field(&suite["protocol"], "initial_chat_id")?;
            let context = ApplicationRecoveryContext::new(&store, secret());
            let (recovery, proof) = recover_saved_read(
                &mut client,
                &SavedReadRecovery::Selected(id.into()),
                &context,
                &cancel,
                true,
            )
            .await
            .map_err(|_| "full policy recovery")?;
            let allowed = Arc::new(AtomicBool::new(true));
            let captured = allowed.clone();
            client.set_private_operation_gate(Some(Arc::new(move || {
                if captured.load(Ordering::Acquire) {
                    Ok(())
                } else {
                    Err(Error::Forbidden)
                }
            })));
            let mut args = vec!["openmates", "chats", "show", id, "--json"];
            if all { args.push("--all"); }
            let (mut output, admission) = crate::cli::full_chat_read::execute_admitted(
                &command(&args),
                &mut client,
                &cancel,
                proof,
            )
            .await
            .map_err(|_| "full real dispatch")?;
            need(!output.stdout.is_empty())?;
            client.set_private_operation_gate(Some(Arc::new(|| Ok(()))));
            let (_registration, barrier) = final_read_journal_test_hook::install(&cancel);
            {
                let publication = persist_saved_read_output_with_full_read(
                    &mut output,
                    &mut client,
                    &context,
                    &recovery,
                    &cancel,
                    Some(&admission),
                );
                tokio::pin!(publication);
                tokio::select! {biased;
                    _=barrier.persisted.notified()=>{},
                    _=&mut publication=>return Err("full policy wait escaped"),
                }
                if revoked {
                    allowed.store(false, Ordering::Release);
                }
                barrier.resume.notify_one();
                if revoked {
                    need(publication.await.is_err())?;
                } else {
                    publication.await.map_err(|_| "permitted full release")?;
                }
            }
            if revoked {
                need(output.stdout.is_empty() && output.stderr.is_empty())?;
            } else {
                need(!output.stdout.is_empty())?;
            }
        }
        Ok(())
    })
    .await
    .map_err(|_| "full policy native deadline")?
}

// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,cli.surface.semantic-parity
#[tokio::test]
async fn actual_saved_json_preserves_all_rich_fields_and_default_work_for_personal_and_team() -> R<()> {
    // Authored UNRUN: real native parser/dispatch, independent encrypted65 peer,
    // selected HTTP metadata/windows/embeds, recovery and encrypted application
    // save. Pure fixture/schema tests do not stand in for this execution.
    tokio::time::timeout(Duration::from_secs(120), async {
        let contract: Value = serde_json::from_str(include_str!("../../tests/fixtures/chats-show-json.json"))
            .map_err(|_| "source-derived native JSON contract")?;
        let team_id = "33333333-3333-4333-8333-333333333333";
        for team in [false, true] {
            for (vector_id, all, raw, focus) in [
                ("default-request-30-single-window", false, false, 0),
                ("explicit-all-65", true, false, 0),
                ("json-raw-request-30-single-window", false, true, 0),
                ("active-focus-nonempty-default", false, false, 1),
                ("active-focus-whitespace-default", false, false, 2),
            ] {
                let (peer, mut client, store, _directory, suite) = settled_full_read_fixture().await?;
                peer.get(match (team, focus) {
                    (false, 1) => "/__test/control?action=structured-history-focus",
                    (true, 1) => "/__test/control?action=structured-history-focus-team",
                    (false, 2) => "/__test/control?action=structured-history-focus-space",
                    (true, 2) => "/__test/control?action=structured-history-focus-space-team",
                    (true, _) => "/__test/control?action=structured-history-team",
                    (false, _) => "/__test/control?action=structured-history",
                })?;
                let before = peer.get("/__test/status")?;
                let id = field(&suite["protocol"], "initial_chat_id")?;
                let mut args = vec!["openmates", "chats", "show", id, "--json"];
                if all { args.push("--all"); }
                if raw { args.push("--raw"); }
                if team { args.extend(["--team", team_id]); }
                let output = execute_with_foreground_recovery(
                    &command(&args), &mut client, CancellationToken::new(),
                    ApplicationRecoveryContext::new(&store, secret()),
                ).await.map_err(|error| error.code())?;
                need(output.exit_code == 0 && output.stderr.is_empty() && output.stdout.ends_with('\n'))?;
                let actual: Value = serde_json::from_str(&output.stdout).map_err(|_| "actual saved JSON")?;
                let vector = contract["vectors"].as_array().ok_or("native vectors")?.iter()
                    .find(|vector| vector["id"] == vector_id).ok_or("selected native vector")?;
                let mut expected = vector["expected"].clone();
                if team { expected["chat"]["chatVisibility"] = json!("team"); }
                // Exact whole-object equality includes optional/null fields,
                // sender/model/time/IDs, stored PII+maps, saved draft+slug,
                // embed associations and stripped follow-up suggestions.
                need(actual == expected)?;
                need(client.session().is_some_and(|session| session.active_team_id.is_none()))?;
                let after = peer.get("/__test/status")?;
                need(after["failure"].is_null())?;
                // Personal show runs the TypeScript-equivalent single global
                // inventory sync; Team keeps selected discovery only.
                if team {
                    need(after["phase2_inventory_syncs"] == before["phase2_inventory_syncs"])?;
                    need(after["inventory_syncs"] == before["inventory_syncs"])?;
                } else {
                    need(after["inventory_syncs"].as_u64() == before["inventory_syncs"].as_u64().map(|n| n + 1))?;
                }
                need(after["structured_detail_reads"].as_u64().unwrap_or(0) >= 1)?;
                need(after["structured_embed_reads"].as_u64().unwrap_or(0) >= 1)?;
                let reads = after["structured_window_reads"].as_array().ok_or("actual selected window work")?;
                need(reads.len() == if all { 4 } else { 1 })?;
                let served: u64 = reads.iter().map(|row| row["returned"].as_u64().unwrap_or(0)).sum();
                need(served == if all { 65 } else { 20 })?;
                if !all {
                    // Preserve the exact TypeScript request, not an assumed
                    // count: one limit30/compression=true window; the current
                    // server caps it at20 and may stop at compression too.
                    need(reads[0]["direction"] == "latest")?;
                    need(reads[0]["limit"] == 30)?;
                    need(reads[0]["respect_compression_boundary"] == true)?;
                } else {
                    need(reads.iter().all(|row| row["limit"] == 100
                        && row["respect_compression_boundary"] == false))?;
                }
                need(!serde_json::to_string(&client.ciphertext_snapshot()).map_err(|_| "private snapshot")?
                    .contains("Saved message 001"))?;
            }
        }
        Ok(())
    }).await.map_err(|_| "complete native saved JSON deadline")?
}

// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,cli.surface.semantic-parity
#[tokio::test]
async fn actual_human_saved_show_returns_one_server_capped_page_without_refilling_to_thirty() -> R<()> {
    // Authored UNRUN. Same actual native dispatch/recovery/encrypted store and
    // independent structured-history peer as the original JSON policy tests.
    tokio::time::timeout(Duration::from_secs(40), async {
        let (peer, mut client, store, _directory, suite) = settled_full_read_fixture().await?;
        peer.get("/__test/control?action=structured-history")?;
        let id = field(&suite["protocol"], "initial_chat_id")?;
        let output = execute_with_foreground_recovery(
            &command(&["openmates", "chats", "show", id, "--personal"]),
            &mut client, CancellationToken::new(),
            ApplicationRecoveryContext::new(&store, secret()),
        ).await.map_err(|error| error.code())?;
        need(output.exit_code == 0 && output.stderr.is_empty())?;
        need(output.stdout.contains("Showing 20 messages from a bounded window. Use --all to request full history."))?;
        need(!output.stdout.contains("Showing 30 messages from a bounded window."))?;
        let status = peer.get("/__test/status")?;
        need(status["failure"].is_null())?;
        let reads = status["structured_window_reads"].as_array().ok_or("actual human viewing work")?;
        need(reads.len() == 1 && reads[0]["direction"] == "latest")?;
        // The existing saved-read Core bounds each physical page at20. The
        // logical CLI request remains30; the shared multi-page default stays5.
        need(reads[0]["limit"] == 20 && reads[0]["returned"] == 20)?;
        need(reads[0]["respect_compression_boundary"] == true)?;
        let defaults = openmates_sdk::client::saved_chat_read::SavedChatReadOptions::default();
        need(defaults.limit == 30 && defaults.max_pages == 5)?;
        Ok(())
    }).await.map_err(|_| "human single-page policy deadline")?
}
