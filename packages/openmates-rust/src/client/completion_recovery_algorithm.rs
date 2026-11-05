//! One existing stage/resume/commit policy algorithm, shared by borrowed and
//! owned runtimes. IO/Apply ownership belongs to the typed runtime, not Client.
use super::*;
use super::phase_runtime::RecoveryPhases;
pub(super) async fn stage<P:RecoveryPhases>(phases:&mut P,job:&CompletionRecoveryJob,
    saved:Option<CompletionRecoveryCheckpoint>,cancel:&CancellationToken,
)->Result<OriginalForegroundRecoveryAdmission>{
        let mut fence = phases.fence(cancel).await?;
        validate_job(job)?;
        fence.run(phases.validate(&fence)).await?;
        phases.check_fence(&fence).await?;
        let scope = phases.begin_scope().await?;
        phases.scope_chat(&scope, &job.chat_id).await?;
        canonical_uuid(&job.job_id)?;
        canonical_uuid(&job.chat_id)?;
        if job.chat_key_version != 1 {
            return Ok(OriginalForegroundRecoveryAdmission::Deferred);
        }
        if job.kind == CompletionRecoveryKind::Metadata && phases.team().await?.is_some() {
            return Ok(OriginalForegroundRecoveryAdmission::Deferred);
        }
        // Owned physical restore DATA is admitted only after actual initial
        // auth bookkeeping/full original checks, before key/reconcile/claim.
        // Borrowed compatibility returns the original input without IO.
        let saved=phases.saved_checkpoint(job,saved,&fence).await?;
        if let Some(saved) = &saved {
            phases.check_owner(saved, &fence).await?;
            if !same_checkpoint_job(&saved.job, job) {
                return Err(Error::Protocol);
            }
        }
        let (row, key) = match phases.current_key(&job.chat_id, &fence).await {
            Err(Error::Conflict) => return Ok(OriginalForegroundRecoveryAdmission::Deferred),
            result => result?,
        };
        // Reconcile exact canonical assistant before claim, but only a later
        // authoritative TERMINAL claim can declare this job already finished.
        let canonical = if job.kind == CompletionRecoveryKind::Main {
            phases.reconcile(job, &key, &fence).await?
        } else {
            None
        };
        if let Some(saved) = &saved {
            if saved.canonical_ciphertext
                && phases.canonical(job).await?.as_ref() != Some(&saved.encrypted_candidate)
            {
                return Ok(OriginalForegroundRecoveryAdmission::Deferred);
            }
            validate_checkpoint_candidate(saved, &key, None)?;
        }
        phases.scope_chat(&scope, &job.chat_id).await?;
        let mut ws = phases.foreground_socket(&fence).await?;
        phases.scope_chat(&scope, &job.chat_id).await?;
        let (claim_kind, claim_reply) = if job.kind == CompletionRecoveryKind::Main {
            ("recovery_job_claim", "recovery_job_claimed")
        } else {
            ("metadata_job_claim", "metadata_job_claimed")
        };
        let claim = match phases
            .exchange(
                &mut ws,
                claim_kind,
                json!({}),
                claim_reply,
                &job.job_id,
                &fence,
            )
            .await
        {
            Err(Error::Conflict) => return Ok(OriginalForegroundRecoveryAdmission::DeferredWithSocket(ws)),
            result => result?,
        };
        phases.scope_chat(&scope, &job.chat_id).await?;
        same_job(job, &claim)?;
        if matches!(claim["state"].as_str(), Some("TERMINAL" | "SUPERSEDED")) {
            if job.kind == CompletionRecoveryKind::Main {
                let receipt = match canonical {
                    Some(receipt) => receipt,
                    None => phases
                        .reconcile(job, &key, &fence)
                        .await?
                        .ok_or(Error::Protocol)?,
                };
                phases.scope_chat(&scope, &job.chat_id).await?;
                phases.check_fence(&fence).await?;
                return Ok(OriginalForegroundRecoveryAdmission::Canonical(OriginalForegroundRecoveryResult{owned_transition:None,owned_artifacts:None,owned_socket:Some(ws),receipt,job:job.clone(),fence}));
            }
            let (current, _) = phases.current_key(&job.chat_id, &fence).await?;
            phases.scope_chat(&scope, &job.chat_id).await?;
            phases.check_fence(&fence).await?;
            return Ok(OriginalForegroundRecoveryAdmission::Canonical(OriginalForegroundRecoveryResult{owned_transition:None,owned_artifacts:None,owned_socket:Some(ws),
                receipt:metadata_receipt(job,&claim,&current)?,job:job.clone(),fence,
            }));
        }
        let encrypted_candidate;
        let wrapped_chat_key;
        let (lease_token, lease_generation) = if job.kind == CompletionRecoveryKind::Main {
            if claim["state"] != "LEASED" {
                return Err(Error::Protocol);
            }
            let token = required(&claim, "lease_token")?;
            if token.len() > 128 || token.chars().any(char::is_control) {
                return Err(Error::Protocol);
            }
            let generation = claim["lease_generation"]
                .as_u64()
                .filter(|v| *v > 0)
                .ok_or(Error::Protocol)?;
            fence.lease_expires_at = Some(iso_timestamp_ms(required(&claim, "lease_expires_at")?)?);
            phases.check_fence(&fence).await?;
            let identity = main_identity(&phases.owner().await?, job)?;
            let envelope: Value = serde_json::from_str(required(&claim, "sealed_payload")?)?;
            let recovered = Plain::new(decode_main_completion(&envelope, &key, &identity)?);
            phases.check_fence(&fence).await?;
            encrypted_candidate = if canonical.is_some() {
                let candidate = match phases.canonical(job).await? {
                    Some(candidate) => candidate,
                    None => return Ok(OriginalForegroundRecoveryAdmission::DeferredWithSocket(ws)),
                };
                let probe = CompletionRecoveryCheckpoint {
                    protocol_version: 1,
                    api_url: phases.api_url().await?,
                    owner_id: phases.owner().await?,
                    team_id: phases.team().await?,
                    job: job.clone(),
                    encrypted_candidate: candidate.clone(),
                    wrapped_chat_key: None,
                    canonical_ciphertext: true,
                };
                if validate_checkpoint_candidate(&probe, &key, Some(&recovered)).is_err() {
                    return Ok(OriginalForegroundRecoveryAdmission::DeferredWithSocket(ws));
                }
                if let Some(saved) = &saved {
                    validate_checkpoint_candidate(saved, &key, Some(&recovered))?;
                    if saved.encrypted_candidate != candidate {
                        return Err(Error::Conflict);
                    }
                }
                candidate
            } else if let Some(saved) = &saved {
                validate_checkpoint_candidate(saved, &key, Some(&recovered))?;
                saved.encrypted_candidate.clone()
            } else {
                let created_at = phases.observed_created_at(job).await?
                    .or_else(|| claim["created_at"].as_u64().filter(|at| *at > 0 && *at <= 9_007_199_254_740_991))
                    .unwrap_or_else(|| now_ms() / 1000);
                phases.scope_chat(&scope, &job.chat_id).await?;
                phases.check_fence(&fence).await?;
                encrypt_main_assistant(&recovered, &identity, created_at, None, &key)?
            };
            wrapped_chat_key = None;
            (
                Some(zeroize::Zeroizing::new(token.into())),
                Some(generation),
            )
        } else {
            if claim["state"] != "AVAILABLE" {
                return Err(Error::Protocol);
            }
            let recovered = Plain::new(decode_metadata_completion(
                &claim,
                &phases.owner().await?,
                job,
                &key,
            )?);
            phases.check_fence(&fence).await?;
            encrypted_candidate = if let Some(saved) = &saved {
                validate_checkpoint_candidate(saved, &key, Some(&recovered))?;
                saved.encrypted_candidate.clone()
            } else {
                encrypt_metadata_fields(&recovered, &key)?
            };
            wrapped_chat_key = Some(required(&row, "encrypted_chat_key")?.to_owned());
            if saved
                .as_ref()
                .is_some_and(|saved| saved.wrapped_chat_key != wrapped_chat_key)
            {
                return Err(Error::Crypto);
            }
            (None, None)
        };
        let checkpoint = CompletionRecoveryCheckpoint {
            protocol_version: 1,
            api_url: phases.api_url().await?,
            owner_id: phases.owner().await?,
            team_id: phases.team().await?,
            // A restored checkpoint keeps its original canonical metadata bytes.
            // The current handoff remains the authority checked above; optional
            // timestamp enrichment must not change an existing durable digest.
            job: saved.as_ref().map_or_else(|| job.clone(), |saved| saved.job.clone()),
            encrypted_candidate,
            wrapped_chat_key,
            canonical_ciphertext: saved
                .as_ref()
                .map_or(canonical.is_some(), |saved| saved.canonical_ciphertext),
        };
        phases.scope_chat(&scope, &job.chat_id).await?;
        phases.check_owner(&checkpoint, &fence).await?;
        // Stage continuation survives routine per-call child replacement.
        // Retain the explicit caller/mode/owner lifetime, while each awaited
        // operation used and commit will use its own current Client child.
        phases.retain_stage(&mut fence, cancel).await?;
        Ok(OriginalForegroundRecoveryAdmission::Ready(Box::new(
            CompletionRecoveryStage {
                socket: ws,
                checkpoint,
                key,
                fence,
                lease_token,
                lease_generation,
                canonical_settlement: canonical.is_some(),
            },
        )))
    }
pub(super) async fn commit<P:RecoveryPhases>(phases:&mut P,mut stage:CompletionRecoveryStage,
    durable:CompletionRecoveryDurableReceipt,cancel:&CancellationToken,
)->Result<OriginalForegroundRecoveryResult>{
        phases.check_owner(&stage.checkpoint, &stage.fence).await?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if durable.checkpoint_sha256 != stage.checkpoint.digest()? {
            return Err(Error::Conflict);
        }
        let fresh = phases.fence(cancel).await?;
        fresh.run(phases.validate(&fresh)).await?;
        phases.check_fence(&fresh).await?;
        let scope = phases.begin_scope().await?;
        phases.scope_chat(&scope, &stage.checkpoint.job.chat_id).await?;
        phases.check_owner(&stage.checkpoint, &stage.fence).await?;
        let job = stage.checkpoint.job.clone();
        let (row, key) = fresh
            .run(phases.current_key(&job.chat_id, &stage.fence))
            .await?;
        if key.as_ref() != stage.key.as_ref() {
            return Err(Error::Crypto);
        }
        validate_checkpoint_candidate(&stage.checkpoint, &key, None)?;
        if job.kind == CompletionRecoveryKind::Main {
            // Reconcile before any re-persist, including a concurrent winner or
            // the caller's resume after an ambiguous previous ACK.
            let existing = fresh
                .run(phases.reconcile(&job, &key, &stage.fence))
                .await?;
            if stage.canonical_settlement
                || (existing.is_some()
                    && phases.canonical(&job).await?.as_ref()
                        == Some(&stage.checkpoint.encrypted_candidate))
            {
                if existing.is_none()
                    || phases.canonical(&job).await?.as_ref()
                        != Some(&stage.checkpoint.encrypted_candidate)
                {
                    return Err(Error::Conflict);
                }
            } else if let Some(receipt) = existing {
                let state = fresh
                    .run(phases.exchange(
                        &mut stage.socket,
                        "recovery_job_claim",
                        json!({}),
                        "recovery_job_claimed",
                        &job.job_id,
                        &stage.fence,
                    ))
                    .await?;
                same_job(&job, &state)?;
                if state["state"] != "TERMINAL" {
                    return Err(Error::Conflict);
                }
                phases.scope_chat(&scope, &job.chat_id).await?;
                phases.check_fence(&stage.fence).await?;
                return Ok(OriginalForegroundRecoveryResult{owned_transition:None,owned_artifacts:None,owned_socket:Some(stage.socket),receipt,job:job.clone(),fence:stage.fence.clone()});
            }
            let mut expected_version = row["messages_v"].as_u64().ok_or(Error::Protocol)?;
            // Retry ONLY the matched version CAS, at most three times. The
            // original socket, lease, key and exact durable ciphertext remain.
            let mut attempt = 0;
            let receipt = loop {
                phases.scope_chat(&scope, &job.chat_id).await?;
                phases.check_owner(&stage.checkpoint, &stage.fence).await?;
                phases.check_fence(&fresh).await?;
                let payload = json!({"lease_token":stage.lease_token.as_ref().ok_or(Error::Protocol)?.as_str(),"lease_generation":stage.lease_generation.ok_or(Error::Protocol)?,"expected_messages_v":expected_version,"encrypted_assistant_message":stage.checkpoint.encrypted_candidate});
                match fresh.run(phases.persist_main(&mut stage.socket,payload,&job.job_id,&stage.fence)).await? {
                    phase_runtime::MainPersistAttempt::Persisted(receipt) => break receipt,
                    phase_runtime::MainPersistAttempt::VersionConflict if attempt < 3 => {
                        attempt += 1;
                        let (current, current_key) = fresh.run(phases.current_key(&job.chat_id,&stage.fence)).await?;
                        phases.scope_chat(&scope, &job.chat_id).await?;
                        phases.check_owner(&stage.checkpoint, &stage.fence).await?;
                        phases.check_fence(&fresh).await?;
                        if current_key.as_ref() != stage.key.as_ref() { return Err(Error::Crypto); }
                        // Only the authoritative version is refreshed. No row,
                        // owner, scope, key or ciphertext replaces the capture.
                        expected_version = current["messages_v"].as_u64().ok_or(Error::Protocol)?;
                    },
                    phase_runtime::MainPersistAttempt::VersionConflict => return Err(Error::Conflict),
                }
            };
            if receipt["state"] != "TERMINAL" {
                return Err(Error::Protocol);
            }
            let result = fresh
                .run(phases.reconcile(&job, &key, &stage.fence))
                .await?
                .ok_or(Error::Protocol)?;
            phases.scope_chat(&scope, &job.chat_id).await?;
            phases.check_fence(&stage.fence).await?;
            return Ok(OriginalForegroundRecoveryResult{owned_transition:None,owned_artifacts:None,owned_socket:Some(stage.socket),receipt:result,job:job.clone(),fence:stage.fence.clone()});
        }
        if phases.team().await?.is_some()
            || Some(required(&row, "encrypted_chat_key")?)
                != stage.checkpoint.wrapped_chat_key.as_deref()
        {
            return Err(Error::Forbidden);
        }
        let payload = json!({"chat_key_version":1,"wrapped_chat_key":stage.checkpoint.wrapped_chat_key,"encrypted_metadata":stage.checkpoint.encrypted_candidate});
        let receipt = fresh
            .run(phases.exchange(
                &mut stage.socket,
                "metadata_job_persist",
                payload,
                "metadata_job_persisted",
                &job.job_id,
                &stage.fence,
            ))
            .await?;
        same_job(&job, &receipt)?;
        if !matches!(receipt["state"].as_str(), Some("TERMINAL" | "SUPERSEDED")) {
            return Err(Error::Protocol);
        }
        let (current, _) = fresh
            .run(phases.current_key(&job.chat_id, &stage.fence))
            .await?;
        let updated = merge_metadata_receipt(&receipt, &current)?;
        let result = metadata_receipt(&job, &receipt, &updated)?;
        phases.scope_chat(&scope, &job.chat_id).await?;
        phases.check_fence(&stage.fence).await?;
        phases.insert_row(job.chat_id.clone(), updated).await?;
        Ok(OriginalForegroundRecoveryResult{owned_transition:None,owned_artifacts:None,owned_socket:Some(stage.socket),receipt:result,job:job.clone(),fence:stage.fence})
    }
