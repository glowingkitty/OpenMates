//! Genuine Rust bridge saved-send lifecycle. No test hooks or fabricated receipt.
use super::*;
async fn wait(peer: &Peer, predicate: impl Fn(&Value) -> bool) -> Check<Value> {
    for _ in 0..500 {
        let report = peer.status()?;
        require!(report["failure"].is_null(), "saved peer protocol");
        if predicate(&report) {
            return Ok(report);
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    Err("saved protocol barrier")
}
async fn event(bridge: &SessionBridge, id: &str) -> Check<Value> {
    decoded(bridge.next_event(id.into()).await)
}
async fn terminal(bridge: &SessionBridge, id: &str, cancelled: bool) -> Check<Value> {
    loop {
        match bridge.next_event(id.into()).await {
            Err(error) if cancelled && error.code == "cancelled" => return Ok(Value::Null),
            result => {
                let value = decoded(result)?;
                if value["type"] == "error" {
                    require!(
                        cancelled && value["error"]["code"] == "cancelled",
                        "saved terminal error"
                    );
                    return Ok(Value::Null);
                }
                if value["type"] == "completed" {
                    require!(!cancelled, "cancelled turn cannot publish Chat");
                    return Ok(value);
                }
            }
        }
    }
}
async fn admitted(bridge: &SessionBridge, id: &str) -> Check<()> {
    loop {
        let value = event(bridge, id).await?;
        require!(value["type"] == "update", "saved admission update");
        if value["update"].get("Admitted").is_some() {
            return Ok(());
        }
    }
}
fn assert_b(peer: &Peer, value: &Value, text: &str) -> Check<()> {
    let report = peer.status()?;
    require!(
        value["chat"]["id"].as_str()
            == report["admitted_chats"]
                .as_array()
                .and_then(|chats| chats.last())
                .and_then(Value::as_str),
        "B result exact admitted chat id"
    );
    let expected = report["admitted_messages"]
        .as_array()
        .and_then(|messages| messages.last())
        .ok_or("missing B admission identity")?;
    require!(
        value["chat"]["messages"]
            .as_array()
            .is_some_and(|messages| messages
                .iter()
                .any(|message| message.get("id") == Some(expected)
                    && message["role"] == "user"
                    && message["content"] == text)),
        "B result must contain actual original B admission"
    );
    Ok(())
}
fn release(endpoint: &str, path: &str) -> Check<()> {
    let address = endpoint
        .strip_prefix("http://")
        .ok_or("saved fixture address")?;
    let mut stream = TcpStream::connect(address).map_err(|_| "saved release connect")?;
    stream
        .set_read_timeout(Some(Duration::from_secs(3)))
        .map_err(|_| "saved release timeout")?;
    stream
        .write_all(
            format!("GET {path} HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n")
                .as_bytes(),
        )
        .map_err(|_| "saved release request")?;
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|_| "saved release response")?;
    require!(response.starts_with("HTTP/1.1 200"), "saved release status");
    Ok(())
}
pub(super) async fn run(
    root: &Path,
    fixture: &Path,
    suite: &Value,
    vector: &Value,
) -> Check<Value> {
    let peer = Peer::start(
        root,
        fixture,
        vector["id"].as_str().ok_or("saved vector id")?,
    )?;
    let spec = &suite["saved_stream"];
    let account = &spec["account"];
    let protocol = &spec["protocol"];
    let bridge=SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":protocol["app_origin"],"enhanced_privacy":false,"allow_private_operations":true}).to_string()).map_err(|_|"saved construct")?;
    let session=json!({"api_url":peer.endpoint,"session_id":account["session_id"],"cookies":{"auth_refresh_token":account["cookie"]},"ws_token":null,"master_key":account["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string();
    bridge
        .import_session(session.clone())
        .await
        .map_err(|_| "saved import")?;
    let chat = if vector["chat_selector"] == "new" {
        None
    } else {
        Some(
            protocol["initial_chat_id"]
                .as_str()
                .ok_or("saved chat id")?
                .to_owned(),
        )
    };
    let text = protocol["input"].as_str().ok_or("saved input")?;
    let mode = vector["mode"].as_str().ok_or("saved mode")?;
    if mode.starts_with("saved_owned_apps_") {
        let a=bridge.start_send(text.into(),chat.clone()).await.map_err(|_|"owned A start")?;
        admitted(&bridge,&a).await?;wait(&peer,|s|s["admissions"]==1).await?;
        require!(peer.status()?["closed_sockets"]==0,"A closed before B");
        let inventory=|rows:&Value|->Check<()>{require!(rows.as_array().is_some_and(|rows|rows.len()==1),"Apps row count");require!(rows[0]["id"]=="fixture-app"&&rows[0]["fields"]["id"]=="fixture-app"&&rows[0]["title"]=="Fixture inventory"&&rows[0]["category"]=="Apps","shared Apps Item");Ok(())};
        if mode=="saved_owned_apps_pre_cancel" {
            // Rust futures are lazy: discarding this exact unpolled B cannot
            // issue HTTP or cancel the independently running original A.
            let b=bridge.list("apps".into());drop(b);
            require!(peer.status()?["inventory_requests"]==0,"pre-dispatch B made HTTP");
        }else if mode=="saved_owned_apps_success" {
            let rows=decoded(tokio::time::timeout(Duration::from_secs(10),bridge.list("apps".into())).await.map_err(|_|"B list deadline")?)?;inventory(&rows)?;
            require!(peer.status()?["inventory_requests"]==1,"Apps request count");
        }else if mode=="saved_owned_apps_cancel_headers" {
            release(&peer.endpoint,"/__test/inventory-hold-next")?;
            let original=bridge.clone();let b=tokio::spawn(async move{original.list("apps".into()).await});
            wait(&peer,|s|s["inventory_headers"]==1).await?;
            // Success of this genuine authenticated read proves first B's
            // header rotation was applied before cancelling that original B.
            let rows=decoded(tokio::time::timeout(Duration::from_secs(10),bridge.list("apps".into())).await.map_err(|_|"header witness deadline")?)?;inventory(&rows)?;
            b.abort();let cancelled=b.await.map_err(|error|if error.is_cancelled(){"cancelled"}else{"B caller panic"});require!(matches!(cancelled,Err("cancelled")),"own B caller not cancelled");
            release(&peer.endpoint,"/__test/inventory-release-body")?;
            require!(peer.status()?["inventory_requests"]==2,"cancel B request count");
        }else{return Err("unknown saved owned Apps mode")}
        require!(peer.status()?["closed_sockets"]==0,"B cancellation closed A");
        release(&peer.endpoint,"/__test/release-owned-a")?;
        let value=terminal(&bridge,&a,false).await?;assert_b(&peer,&value,text)?;
        let after=decoded(bridge.export_session(true).await)?;
        if mode!="saved_owned_apps_pre_cancel" {let expected=if mode=="saved_owned_apps_success"{"synthetic-inventory-rotation-1"}else{"synthetic-inventory-rotation-2"};require!(after["session"]["cookies"]["auth_refresh_token"]==expected,"actual rotated credential retained after A");}
    } else if mode == "saved_auth_denial" {
        for _ in 0..2 {
            let id = bridge
                .start_send(text.into(), chat.clone())
                .await
                .map_err(|_| "saved denied admission handle")?;
            loop {
                match bridge.next_event(id.clone()).await {
                    Err(error) => {
                        require!(
                            ["expired", "authentication", "forbidden"].contains(&error.code),
                            "saved auth refusal"
                        );
                        break;
                    }
                    Ok(raw) => {
                        let value: Value =
                            serde_json::from_str(&raw).map_err(|_| "saved auth JSON")?;
                        if value["type"] == "error" {
                            let code = value["error"]["code"].as_str().ok_or("saved auth code")?;
                            require!(
                                ["expired", "authentication", "forbidden"].contains(&code),
                                "saved auth refusal"
                            );
                            break;
                        }
                        require!(value["type"] != "completed", "auth denial published Chat");
                    }
                }
            }
        }
    } else if mode == "saved_queued_import_revoke"
        || mode == "saved_queued_close_revoke"
        || mode == "saved_queued_malformed_revoke"
    {
        // Public Rust retirement boundary. The same genuine native lane is
        // additionally exercised with held private opaque outputs in unit tests.
        let a = bridge
            .start_send(text.into(), chat.clone())
            .await
            .map_err(|_| "retired A")?;
        admitted(&bridge, &a).await?;
        wait(&peer, |s| s["admissions"] == 1).await?;
        if mode == "saved_queued_import_revoke" {
            bridge
                .import_session(session.clone())
                .await
                .map_err(|_| "explicit reimport")?;
        } else if mode == "saved_queued_close_revoke" {
            bridge.close().await.map_err(|_| "queued close")?;
        } else {
            error_code(bridge.import_session("{}".into()).await, "invalid_argument")?;
        }
        terminal(&bridge, &a, true).await?;
        if mode == "saved_queued_malformed_revoke" {
            let unchanged = decoded(bridge.export_session(true).await)?;
            require!(
                unchanged["session"]["session_id"] == account["session_id"]
                    && unchanged["session"]["master_key"] == account["master_key"],
                "failed replacement did not change credentials"
            );
        }
        if mode == "saved_queued_import_revoke" {
            let b = bridge
                .start_send(text.into(), None)
                .await
                .map_err(|_| "reimported B")?;
            let value = terminal(&bridge, &b, false).await?;
            assert_b(&peer, &value, text)?;
        }
    } else if mode == "saved_queued_successor_terminal" {
        let a = bridge
            .start_send(text.into(), chat.clone())
            .await
            .map_err(|_| "terminal A")?;
        terminal(&bridge, &a, false).await?;
        wait(&peer, |s| s["closed_sockets"] == 1).await?;
        let b = bridge
            .start_send(text.into(), chat.clone())
            .await
            .map_err(|_| "terminal B")?;
        admitted(&bridge, &b).await?;
        error_code(bridge.cancel_stream(a.clone()), "conflict")?;
        error_code(bridge.next_event(a).await, "conflict")?;
        require!(peer.status()?["closed_sockets"] == 1, "stale A changed B");
        release(&peer.endpoint, "/__test/release-b")?;
        let value = terminal(&bridge, &b, false).await?;
        assert_b(&peer, &value, text)?;
    } else if mode == "saved_pre_effect_abort" {
        let a = bridge
            .start_send(text.into(), chat.clone())
            .await
            .map_err(|_| "pre-effect A")?;
        wait(&peer, |s| s["snapshot_waiting"] == true).await?;
        bridge
            .cancel_stream(a.clone())
            .map_err(|_| "pre-effect exact cancel")?;
        terminal(&bridge, &a, true).await?;
        wait(&peer, |s| s["closed_sockets"] == 1).await?;
        let b = bridge
            .start_send(text.into(), chat.clone())
            .await
            .map_err(|_| "pre-effect B")?;
        let value = terminal(&bridge, &b, false).await?;
        assert_b(&peer, &value, text)?;
        require!(
            value["chat"]["messages"]
                .as_array()
                .is_some_and(|messages| messages
                    .iter()
                    .any(|message| message["role"] == "user" && message["content"] == text)),
            "pre-effect B actual Chat"
        );
    } else if mode == "saved_stale_terminal" {
        let a = bridge
            .start_send(text.into(), chat.clone())
            .await
            .map_err(|_| "saved A")?;
        terminal(&bridge, &a, false).await?;
        wait(&peer, |s| s["closed_sockets"] == 1).await?;
        let b = bridge
            .start_send(text.into(), chat.clone())
            .await
            .map_err(|_| "saved B")?;
        admitted(&bridge, &b).await?;
        wait(&peer, |s| s["admissions"] == 2).await?;
        error_code(bridge.cancel_stream(a), "conflict")?;
        require!(
            peer.status()?["closed_sockets"] == 1,
            "stale A closed B socket"
        );
        release(&peer.endpoint, "/__test/release-b")?;
        let value = terminal(&bridge, &b, false).await?;
        assert_b(&peer, &value, text)?;
    } else {
        let a = bridge
            .start_send(text.into(), chat.clone())
            .await
            .map_err(|_| "saved A")?;
        admitted(&bridge, &a).await?;
        wait(&peer, |s| s["admissions"] == 1).await?;
        if mode == "saved_active_task_cancel" {
            loop {
                let value = event(&bridge, &a).await?;
                require!(value["type"] == "update", "active A update");
                if let Some(content) = value["update"].get("Content") {
                    require!(
                        content["content"] == "Synthetic live fragment",
                        "actual live fragment"
                    );
                    break;
                }
            }
        }
        if mode == "saved_close_no_rearm" {
            bridge.close().await.map_err(|_| "saved close")?;
            terminal(&bridge, &a, true).await?;
            error_code(
                bridge.start_send(text.into(), chat.clone()).await,
                "cancelled",
            )?;
        } else {
            if mode == "saved_global_cancel" {
                bridge.cancel().map_err(|_| "saved global cancel")?;
            } else if mode == "saved_host_abort" {
                let task = {
                    let bridge = bridge.clone();
                    let a = a.clone();
                    tokio::spawn(async move { bridge.next_event(a).await })
                };
                tokio::task::yield_now().await;
                task.abort();
                let _ = task.await;
                bridge
                    .cancel_stream(a.clone())
                    .map_err(|_| "saved exact cancel")?;
            } else {
                require!(
                    mode == "saved_consumer_close"
                        || mode == "saved_same_chat_after_uncertain"
                        || mode == "saved_active_task_cancel",
                    "unknown saved mode"
                );
                bridge
                    .cancel_stream(a.clone())
                    .map_err(|_| "saved exact cancel")?;
            }
            terminal(&bridge, &a, true).await?;
            wait(&peer, |s| {
                s["closed_sockets"].as_u64().is_some_and(|n| n >= 1)
            })
            .await?;
            {
                // A stays uncertain; B owns a genuinely new explicit operation.
                let successor = if vector["successor_chat_selector"] == "same" {
                    chat.clone()
                } else {
                    None
                };
                let b = bridge
                    .start_send(text.into(), successor)
                    .await
                    .map_err(|_| "saved independent B")?;
                let value = terminal(&bridge, &b, false).await?;
                assert_b(&peer, &value, text)?;
                require!(
                    value["chat"]["messages"]
                        .as_array()
                        .is_some_and(|messages| {
                            messages.iter().any(|message| {
                                message["role"] == "user" && message["content"] == text
                            })
                        }),
                    "independent B actual Chat"
                );
            }
        }
    }
    let report = wait(&peer, |s| s["admissions"] == vector["expected_admissions"]).await?;
    let count = vector["expected_admissions"]
        .as_u64()
        .ok_or("saved expected admissions")? as usize;
    require!(
        report["turns"].as_array().is_some_and(|v| v.len() == count)
            && report["message_ids"]
                .as_array()
                .is_some_and(|v| v.len() == count),
        "saved identities repeated"
    );
    if mode == "saved_active_task_cancel" {
        require!(
            report["task_cancel_requests"] == 1,
            "exact original A task cancel request"
        );
    }
    if mode == "saved_auth_denial" {
        require!(
            report["auth_denials"].as_u64().is_some_and(|n| n >= 1),
            "missing actual auth denial"
        );
    } else {
        for name in [
            "actual-encrypted-saved-admission",
            "no-replay-of-turn-or-message-identities",
            "no-model-provider-override",
        ] {
            require!(
                report["checks"]
                    .as_array()
                    .is_some_and(|v| v.contains(&json!(name))),
                "saved protocol check"
            );
        }
    }
    bridge.close().await.map_err(|_| "saved final close")?;
    Ok(json!({"id":vector["id"],"status":"passed"}))
}
