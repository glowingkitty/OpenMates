//! Terminal binding for the core's vault-backed read-only Personal cache.
//! Offline navigation never dispatches ordinary actor operations.
use super::*;
use openmates_sdk::client::NativePersonalOfflineReceipt;

pub(super) struct OfflinePersonal {
    reader: NativeCachedChatViews,
    receipt: NativePersonalOfflineReceipt,
}

impl Actor {
    pub(super) async fn authorized_admission(
        &mut self,
        replies: &mpsc::Sender<Reply>,
        epoch: Stamp,
    ) -> Result<()> {
        // This can start monitors and foreground recovery. Remove any restored
        // receipt durably before those effects, including a crash before a
        // recovery checkpoint/final save. Failure refuses their dispatch.
        if self
            .offline_expected
            .as_ref()
            .is_some_and(|receipt| !receipt.belongs_to_profile(self.core.client()))
        {
            self.offline_expected = None;
        }
        if self.offline_expected.is_some() {
            // Only this passive monitor may run before the durable fence.
            // Following positive admission it persists the invalidation
            // before exposing any online work. A genuine disconnect writes nothing.
            self.core.client_mut().invalidate_chat_list_freshness();
        } else {
            self.core
                .revoke_list_freshness_before_dispatch(&self.live_cancel)
                .await?;
        }
        let generation = self.store.generation_guard();
        let request = self.live_cancel.clone();
        // Reuse the already-required first monitor's authenticated session read
        // and exact persistence BEFORE the initial greeting. No extra request.
        let admission = self.monitor_admission(replies, epoch).await?;
        if let MonitorAdmission::Denied(error) = admission {
            return Err(error);
        }
        if matches!(
            admission,
            MonitorAdmission::Offline(Error::VerificationRequired)
        ) {
            return Err(Error::VerificationRequired);
        }
        let storage = match self.store.storage_mode().await? {
            Some(openmates::storage::StorageMode::OsKeyring) => {
                "Signed in · credentials protected by OS keyring"
            }
            Some(openmates::storage::StorageMode::RestrictedLocalFile) => {
                "Signed in · credentials protected by owner-only local files"
            }
            Some(openmates::storage::StorageMode::EncryptedVault) => {
                "Signed in · credentials protected by passphrase vault"
            }
            None => "Signed in · credentials not stored",
        };
        // A newly admitted monitor has already staged this exact owner once.
        // Reuse it instead of decoding another cache projection.
        let staged = self.cached_views.borrow().clone();
        if staged.as_ref().is_none_or(|current| {
            current.security != epoch.security
                || !current.store_generation.is_current()
                || !current.views.is_owner_current()
        }) {
            self.stage_cached_views(epoch);
        }
        let owner = self.cached_views.borrow().clone().ok_or(match admission {
            MonitorAdmission::Offline(error) => error,
            _ => Error::Offline,
        })?;
        if !generation.is_current() || request.is_cancelled() || !owner.views.is_owner_current() {
            return Err(Error::Cancelled);
        }
        let session = self.core.client().session().ok_or(Error::Authentication)?;
        // The SDK stage above requires the principal established by actual
        // authentication. A raw restored Session cannot issue this greeting.
        let username = ["username", "display_name"]
            .into_iter()
            .filter_map(|key| self.core.client().user()[key].as_str())
            .find(|name| !name.is_empty())
            .unwrap_or("OpenMates")
            .to_owned();
        let publication = NativeAuthPublication {
            owner,
            request,
            username,
            expires_at: session.paired_session_expires_at,
        };
        if matches!(admission, MonitorAdmission::Ready) {
            self.remember_personal_offline().await;
        }
        Self::emit(replies, epoch, View::AdmittedAuth(publication)).await?;
        let status = if matches!(admission, MonitorAdmission::Offline(_)) {
            "Offline · reconnecting…"
        } else {
            storage
        };
        Self::emit(replies, epoch, View::Status(status)).await
    }
    pub(super) async fn boot(&mut self, replies: &mpsc::Sender<Reply>, epoch: Stamp) -> Result<()> {
        let session = match self.store.load(self.passphrase.get()).await {
            Ok(value) => value,
            Err(Error::Locked)
                if self.store.storage_mode().await?
                    == Some(openmates::storage::StorageMode::EncryptedVault) =>
            {
                Self::emit(replies, epoch, View::Unlock).await?;
                return Ok(());
            }
            Err(Error::Expired) => {
                self.core.clear_credentials().await?;
                None
            }
            Err(error) => return Err(error),
        };
        if let Some(session) = session {
            // Core Start: credentials, trusted account, cached index and list
            // before any other network request, then admission. Global
            // recovery and the list refresh follow as a preemptible BootSync.
            let cancel = self.live_cancel.clone();
            let sink = core_host::TerminalSink::new(
                replies,
                epoch,
                self.store.generation_guard(),
                &cancel,
            );
            self.offline_expected = self.read_personal_offline_receipt(&session).await?;
            let admitted = core_view::handle(
                self,
                ViewCommand::Start {
                    credentials: Box::new(session.clone()),
                },
                &sink,
                &cancel,
            )
            .await;
            let receipt = self.offline_expected.take();
            match admitted {
                Err(Error::Offline)
                    if self
                        .core
                        .client()
                        .session()
                        .is_some_and(|restored| restored.matches_stored_session(&session)) =>
                {
                    return self
                        .restore_personal_offline(receipt, replies, epoch, &cancel)
                        .await;
                }
                Err(error) => return Err(error),
                Ok(()) => {}
            }
            self.core.begin_client_operation(&cancel);
            let sink = sink.owned_by(&self.core, None);
            let request =
                RequestId(SEND_REQUEST_IDS.fetch_add(1, std::sync::atomic::Ordering::Relaxed));
            core_view::paint_startup_chat(self, request, &sink, &cancel).await?;
        } else {
            Self::emit(replies, epoch, View::SignedOut).await?;
        }
        Ok(())
    }
    /// Background half of boot (core `boot_sync`): global recovery with
    /// inventory, then the list, persisted before it is published.
    pub(super) async fn boot_sync(
        &mut self,
        replies: &mpsc::Sender<Reply>,
        epoch: Stamp,
    ) -> Result<()> {
        let cancel = self.live_cancel.clone();
        let sink =
            core_host::TerminalSink::new(replies, epoch, self.store.generation_guard(), &cancel);
        core_view::boot_sync(self, &sink, &cancel).await
    }
    pub(super) async fn remember_personal_offline(&self) {
        if self.trusted_path.is_some() {
            return;
        }
        let (Some(session), Some(monitor)) =
            (self.core.client().clone_session(), self.core.chat_monitor())
        else {
            return;
        };
        let Ok(receipt) = self
            .core
            .client()
            .issue_native_personal_offline_receipt(monitor)
        else {
            return;
        };
        // Failure leaves online admission intact and issues no offline grant.
        let _ = self
            .store
            .seal_personal_offline_receipt(session, self.passphrase.get(), receipt)
            .await;
    }

    async fn read_personal_offline_receipt(
        &self,
        session: &Session,
    ) -> Result<Option<NativePersonalOfflineReceipt>> {
        if self.trusted_path.is_some() || session.active_team_id.is_some() {
            return Ok(None);
        }
        self.store
            .read_personal_offline_receipt(session.clone(), self.passphrase.get())
            .await
    }

    async fn restore_personal_offline(
        &mut self,
        receipt: Option<NativePersonalOfflineReceipt>,
        replies: &mpsc::Sender<Reply>,
        epoch: Stamp,
        cancel: &CancellationToken,
    ) -> Result<()> {
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let receipt = receipt.ok_or(Error::Offline)?;
        let (views, items, initial) = self.core.client().stage_native_personal_offline_cache(
            &receipt,
            self.store.shell().cache().clone(),
            CancellationToken::new(),
        )?;
        let owner = NativeCachedChatViews {
            views: std::sync::Arc::new(views),
            store_generation: self.store.generation_guard(),
            security: epoch.security,
        };
        let auth = NativeAuthPublication {
            owner: owner.clone(),
            request: cancel.clone(),
            username: "Personal".into(),
            expires_at: Some(receipt.expires_at()),
        };
        self.offline_personal = Some(OfflinePersonal {
            reader: owner,
            receipt,
        });
        let total = self.core.client().chat_total_count();
        Self::emit(replies, epoch, View::OfflineAuth(auth, items, total)).await?;
        if let Some(chat) = initial
            && let Ok(Some(view)) = self.offline_window(&chat, epoch, cancel).await
        {
            Self::emit(replies, epoch, view).await?;
        }
        Ok(())
    }

    async fn offline_window(
        &self,
        id: &str,
        epoch: Stamp,
        cancel: &CancellationToken,
    ) -> Result<Option<View>> {
        let owner = &self.offline_personal.as_ref().ok_or(Error::Offline)?.reader;
        if owner.security != epoch.security || !owner.store_generation.is_current() {
            return Err(Error::Cancelled);
        }
        Ok(owner
            .views
            .clone()
            .read(id.to_owned(), cancel.clone())
            .await?
            .map(|publication| {
                View::OfflineWindow(NativeCachedChatPublication {
                    publication,
                    store_generation: owner.store_generation.clone(),
                })
            }))
    }

    pub(super) fn close_offline_personal(&mut self) {
        if let Some(offline) = self.offline_personal.take() {
            offline.reader.views.close();
        }
    }

    pub(super) fn offline_principal_matches(&self) -> bool {
        self.offline_personal
            .as_ref()
            .map(|offline| &offline.receipt)
            .or(self.offline_expected.as_ref())
            .is_none_or(|receipt| receipt.matches_online_principal(self.core.client()))
    }

    /// Retire any previously issued local grant before a verified denial can
    /// be followed by another process launch without server connectivity.
    pub(super) async fn invalidate_vault_receipt(&self, previous: Option<Session>) -> Result<()> {
        if self.trusted_path.is_none()
            && let Some(session) = previous
            && self.revoke_offline_record(session).await.is_err()
        {
            self.core.clear_credentials().await?;
        }
        Ok(())
    }

    async fn revoke_offline_record(&self, session: Session) -> Result<()> {
        self.store
            .revoke_personal_offline_receipt(session, self.passphrase.get())
            .await
    }

    pub(super) async fn offline_dispatch(
        &mut self,
        request: Request,
        replies: &mpsc::Sender<Reply>,
    ) -> Result<()> {
        let Request {
            epoch,
            work,
            cancel,
        } = request;
        match work {
            Work::Command(UiCommand::Logout) => {
                self.close_offline_personal();
                self.passphrase.set(None);
                self.core.client_mut().forget_session();
                let cleared = self.core.clear_credentials().await;
                Self::emit(replies, epoch, View::SignedOut).await?;
                cleared
            }
            Work::OfflineExpired => {
                self.close_offline_personal();
                self.passphrase.set(None);
                self.core.client_mut().forget_session();
                Self::emit(replies, epoch, View::Unlock).await
            }
            Work::Command(UiCommand::Open(Workspace::Chats, chat)) => {
                if let Some(view) = self.offline_window(&chat, epoch, &cancel).await? {
                    Self::emit(replies, epoch, view).await
                } else {
                    Err(Error::Offline)
                }
            }
            Work::Monitor => {
                self.reconnect_offline_personal(epoch, &cancel, replies)
                    .await
            }
            Work::Command(UiCommand::Cancel | UiCommand::MarkRead(_)) => Ok(()),
            _ => Err(Error::Unavailable {
                code: "native_offline_read_only",
                reason: "Only saved chats are available offline.",
            }),
        }
    }

    async fn reconnect_offline_personal(
        &mut self,
        epoch: Stamp,
        cancel: &CancellationToken,
        replies: &mpsc::Sender<Reply>,
    ) -> Result<()> {
        let previous = self.core.client().clone_session().ok_or(Error::Expired)?;
        self.core.begin_client_operation(cancel);
        let validation = tokio::select! {
            _ = cancel.cancelled() => return Err(Error::Cancelled),
            result = tokio::time::timeout(Duration::from_secs(4), self.core.client_mut().validate_session()) => result.unwrap_or(Err(Error::Offline)),
        };
        match validation {
            Err(Error::Offline) => Self::emit(replies, epoch, View::RetryOffline).await,
            Ok(()) if self.offline_principal_matches() => {
                // The passive monitor repeats live admission. Its expected
                // principal is rechecked before saving or reporting Auth.
                self.live_cancel = cancel.clone();
                match self.authorized_admission(replies, epoch).await {
                    Ok(()) => {
                        self.close_offline_personal();
                        Ok(())
                    }
                    Err(Error::Offline) => Self::emit(replies, epoch, View::RetryOffline).await,
                    Err(error) => {
                        self.deny_offline_personal(previous, error, replies, epoch)
                            .await
                    }
                }
            }
            Ok(()) => {
                self.deny_offline_personal(previous, Error::Expired, replies, epoch)
                    .await
            }
            Err(error) => {
                self.deny_offline_personal(previous, error, replies, epoch)
                    .await
            }
        }
    }

    async fn deny_offline_personal(
        &mut self,
        previous: Session,
        error: Error,
        replies: &mpsc::Sender<Reply>,
        epoch: Stamp,
    ) -> Result<()> {
        self.close_offline_personal();
        Self::emit(replies, epoch, View::SignedOut).await?;
        if self.revoke_offline_record(previous).await.is_err()
            || matches!(
                error,
                Error::Expired | Error::Authentication | Error::Forbidden
            )
        {
            self.core.clear_credentials().await?;
        }
        self.core.client_mut().forget_session();
        self.passphrase.set(None);
        if !matches!(
            error,
            Error::Expired | Error::Authentication | Error::Forbidden
        ) {
            Self::emit(replies, epoch, View::Unlock).await?;
        }
        Self::emit(replies, epoch, View::Failed(error)).await
    }
}
