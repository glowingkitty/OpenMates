//! A saved turn split into a short admission on the actor's `Client` and a
//! stream step that owns the turn's socket and borrows the `Client` only per
//! typed phase through a [`ClientLease`], so a shell actor serves other calls
//! while the reply streams. Same protocol, fences and outcome as
//! `Client::send` (`send.rs`, `send_turn_runtime.rs::receive_turn`); native
//! only. Plan `apple-client-core-migration`; spec `client-core`.
use super::prepared_transport::PreparedTurnTransport;
use super::prepared_turn::PreparedTurnContext;
use super::turn_runtime::{BorrowedTurnPhases, SavedTurnClientPhases, TurnPhaseFuture};
use super::*;
use futures_util::future::BoxFuture;
use std::ops::DerefMut;

/// Exclusive access to the actor's one `Client` for one phase of a streaming
/// turn. The lease is held only while a phase runs (a frame check, a stream
/// update hand-off, an artifact write), never while the turn waits for the
/// server, so the actor serves other calls in between.
pub(crate) trait ClientLease: Send + Sync {
    /// Lock the actor's client.
    ///
    /// # Errors
    /// `Authentication` when the actor is signed out, `Cancelled` when it now
    /// holds another session's client.
    fn lease(&self) -> BoxFuture<'_, Result<LeasedClient<'_>>>;
}

/// The locked client of one phase; dropping it releases the actor.
pub(crate) type LeasedClient<'a> = Box<dyn DerefMut<Target = Client> + Send + 'a>;

/// A turn the server was asked to admit (`chat_turn_admit` written), waiting
/// for its stream step. Owns the turn's socket, chat key and prepared private
/// context; never a `Client` borrow. Dropping it closes nothing gracefully:
/// run [`AdmittedTurn::stream`] to the end.
pub(crate) struct AdmittedTurn {
    ws: Socket,
    prepared: PreparedTurnContext,
    turn_scope: AsyncCryptoScope,
    release_scope: AsyncCryptoScope,
    id: String,
    turn: String,
    message: String,
    input: Plain<String>,
    key: Key,
    wrapped: String,
    baseline: u64,
    new_chat: bool,
    chat: Plain<Chat>,
    updates: mpsc::Sender<StreamUpdate>,
    cancel: CancellationToken,
    generation: u64,
    options: SendOptions,
    trace: SendTrace,
    original: OriginalOperation,
}

/// The operation identity at admission, for the cancel withdrawal fence.
struct OriginalOperation {
    parent: CancellationToken,
    child: CancellationToken,
    epoch: u64,
    gate: Option<std::sync::Arc<dyn Fn() -> Result<()> + Send + Sync>>,
}

impl Client {
    /// The admission step of a saved turn: validate, open the turn socket,
    /// prepare the private context and write `chat_turn_admit`. `Started` and
    /// `Submitted` go out on `updates` before the admit is written. The
    /// returned turn streams through [`AdmittedTurn::stream`].
    ///
    /// # Errors
    /// `Invalid` for an incognito turn (volatile turns run whole through
    /// `Client::send`) and as `Client::send` for every other refusal;
    /// transport, crypto and `Cancelled` errors. The socket is closed on
    /// every error.
    pub(crate) async fn admit_send(
        &mut self,
        chat_id: Option<&str>,
        text_input: &str,
        options: SendOptions,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> Result<AdmittedTurn> {
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        options.validate()?;
        if options.incognito {
            return Err(Error::Invalid(
                "An incognito turn cannot stream beside the actor.",
            ));
        }
        self.validate_saved_send_request(chat_id, text_input, &options, &cancel)?;
        let prepared = self
            .prepare_saved_turn_transport(chat_id, text_input, &options, &cancel)
            .await?;
        let PreparedTurnTransport {
            generation,
            id,
            turn,
            message,
            chat,
            new_chat,
            key,
            wrapped,
            baseline,
            existing,
            team_preparation,
            ws,
            release_scope,
        } = prepared;
        let admission = Admission {
            id,
            turn,
            message,
            input: text_input,
            key,
            wrapped,
            baseline,
            new_chat,
            chat,
            generation,
            release_scope,
        };
        self.admit_on_socket(
            ws,
            admission,
            existing.into_inner(),
            team_preparation.into_inner(),
            options,
            updates,
            cancel,
        )
        .await
    }

    /// The socket half of [`Self::admit_send`] (tests drive it over a
    /// loopback socket).
    #[allow(clippy::too_many_arguments)]
    pub(in crate::client) async fn admit_on_socket(
        &mut self,
        mut ws: Socket,
        admission: Admission<'_>,
        existing: Vec<Value>,
        team_preparation: Option<Value>,
        options: SendOptions,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> Result<AdmittedTurn> {
        let trace = SendTrace::new();
        let admitted = async {
            let turn_scope = AsyncCryptoScope::begin(self)?;
            turn_scope.check_chat(self, &admission.id)?;
            let original = OriginalOperation {
                parent: self.operation_parent.clone(),
                child: self.current_operation_child(),
                epoch: self.fresh_auth.operation_epoch(),
                gate: self.options.private_operation_gate.clone(),
            };
            let existing = Plain::new(existing);
            let prepared = self
                .prepare_turn_on_socket(
                    &mut ws,
                    &admission.id,
                    &admission.turn,
                    &admission.message,
                    admission.input,
                    &admission.key,
                    &admission.wrapped,
                    admission.baseline,
                    admission.new_chat,
                    &existing,
                    &admission.chat,
                    &updates,
                    &cancel,
                    admission.generation,
                    team_preparation,
                    &options,
                    &turn_scope,
                )
                .await?;
            Ok((turn_scope, original, prepared))
        }
        .await;
        let (turn_scope, original, prepared) = match admitted {
            Ok(parts) => parts,
            Err(error) => {
                let _ = ws.close(None).await;
                if matches!(&error, Error::Protocol | Error::Offline) {
                    trace.report_protocol_error();
                }
                if matches!(&error, Error::Forbidden) {
                    trace.report_refusal();
                }
                return Err(error);
            }
        };
        let Admission {
            id,
            turn,
            message,
            input,
            key,
            wrapped,
            baseline,
            new_chat,
            chat,
            generation,
            release_scope,
        } = admission;
        Ok(AdmittedTurn {
            ws,
            prepared,
            turn_scope,
            release_scope,
            id,
            turn,
            message,
            input: Plain::new(input.to_owned()),
            key,
            wrapped,
            baseline,
            new_chat,
            chat,
            updates,
            cancel,
            generation,
            options,
            trace,
            original,
        })
    }
}

/// The prepared identity and key material of one turn before its admission.
pub(in crate::client) struct Admission<'a> {
    pub(in crate::client) id: String,
    pub(in crate::client) turn: String,
    pub(in crate::client) message: String,
    pub(in crate::client) input: &'a str,
    pub(in crate::client) key: Key,
    pub(in crate::client) wrapped: String,
    pub(in crate::client) baseline: u64,
    pub(in crate::client) new_chat: bool,
    pub(in crate::client) chat: Plain<Chat>,
    pub(in crate::client) generation: u64,
    pub(in crate::client) release_scope: AsyncCryptoScope,
}

impl AdmittedTurn {
    /// The stream step: receive the turn on its own socket and run each
    /// client phase under a short `lease`, then close the socket and release
    /// the outcome. A cancel (the admission token) withdraws the server task
    /// on the same socket when the original operation is still current, as
    /// `Client::send` does.
    ///
    /// # Errors
    /// As `Client::send`; `Authentication`/`Cancelled` from the lease when
    /// the actor signed out or changed session meanwhile.
    pub(crate) async fn stream(self, lease: &dyn ClientLease) -> Result<SendOutcome> {
        let Self {
            mut ws,
            prepared,
            turn_scope,
            release_scope,
            id,
            turn,
            message,
            input,
            key,
            wrapped,
            baseline,
            new_chat,
            mut chat,
            updates,
            cancel,
            generation,
            options,
            mut trace,
            original,
        } = self;
        let mut task_id = String::new();
        let mut phases = LeasedTurnPhases { lease };
        let result = turn_runtime::receive_turn(
            &mut phases,
            &mut ws,
            prepared,
            &turn_scope,
            &id,
            &turn,
            &message,
            &input,
            &key,
            &wrapped,
            baseline,
            new_chat,
            &mut chat,
            &updates,
            &cancel,
            generation,
            &options,
            &mut trace,
            &mut task_id,
        )
        .await;
        if result.is_err()
            && !task_id.is_empty()
            && (cancel.is_cancelled() || original.child.is_cancelled())
        {
            withdraw(lease, &mut ws, &turn_scope, &original, &id, &task_id).await;
        }
        let _ = ws.close(None).await;
        let result = match result {
            Ok(outcome) => {
                trace.phase = SendPhase::Release;
                let client = lease.lease().await?;
                client.release_send_outcome(&release_scope, &id, &cancel, Plain::new(outcome))
            }
            Err(error) => Err(error),
        };
        if matches!(&result, Err(Error::Protocol | Error::Offline)) {
            trace.report_protocol_error();
        }
        if matches!(&result, Err(Error::Forbidden)) {
            trace.report_refusal();
        }
        result
    }
}

/// `cancel_ai_task` on the turn's own socket after a local cancel, under the
/// same fences as `Client::send_on_socket`: an authenticated negative request
/// of the still-current original operation, never a retry or resend.
async fn withdraw(
    lease: &dyn ClientLease,
    ws: &mut Socket,
    scope: &AsyncCryptoScope,
    original: &OriginalOperation,
    id: &str,
    task_id: &str,
) {
    let Ok(client) = lease.lease().await else {
        return;
    };
    let current = !original.parent.is_cancelled()
        && original.parent == client.operation_parent
        && original.epoch == client.fresh_auth.operation_epoch()
        && same_private_gate(&original.gate, &client.options.private_operation_gate)
        && client.verify_private_operation().is_ok()
        && scope.check_terminated_child_context(&client).is_ok()
        && client.task_watch_authority.cached_chat_allowed(id)
        && !original.parent.is_cancelled()
        && original.parent == client.operation_parent;
    if current {
        let _ = send(
            ws,
            "cancel_ai_task",
            json!({"task_id":task_id,"chat_id":id}),
        )
        .await;
    }
}

/// The client phases of [`turn_runtime::receive_turn`] over a lease: each
/// phase locks the client, runs the borrowed phase and unlocks. A stream
/// update waits for channel capacity without the lease, so a slow shell
/// never holds the actor.
struct LeasedTurnPhases<'l> {
    lease: &'l dyn ClientLease,
}

/// Run one borrowed phase under a fresh lease.
macro_rules! leased {
    ($self:ident, $phase:ident ( $($arg:expr),* )) => {
        Box::pin(async move {
            let mut client = $self.lease.lease().await?;
            let mut phases = BorrowedTurnPhases { client: &mut **client };
            phases.$phase($($arg),*).await
        })
    };
}

impl LeasedTurnPhases<'_> {
    /// Wait without the lease until `updates` has room (or the update's
    /// fences fire), with the select order of `Client::deliver_turn_update`.
    async fn capacity(
        &self,
        updates: &mpsc::Sender<StreamUpdate>,
        cancel: &CancellationToken,
        marker: bool,
    ) -> Result<()> {
        let (operation, authority, master, expiry) = {
            let client = self.lease.lease().await?;
            let master = client
                .browser_credentials
                .as_ref()
                .map(|credentials| credentials.master.clone());
            (
                client.operation_cancel.clone(),
                client.task_watch_authority.cancel.clone(),
                master,
                client.require_credentials()?.paired_session_expires_at,
            )
        };
        let master_revoked = async {
            match &master {
                Some(master) => master.cancelled().await,
                None => std::future::pending::<()>().await,
            }
        };
        let expired = async {
            match expiry {
                Some(deadline) => loop {
                    let remaining = deadline.saturating_sub(now_ms());
                    if remaining == 0 {
                        break;
                    }
                    crate::platform::time::sleep(Duration::from_millis(remaining)).await;
                },
                None => std::future::pending::<()>().await,
            }
        };
        let user_cancel = async {
            if marker {
                std::future::pending::<()>().await
            } else {
                cancel.cancelled().await
            }
        };
        // The permit is released at once: this turn is the channel's only
        // producer, so the room stays for the leased hand-off below.
        tokio::select! {biased;
            () = user_cancel => Err(Error::Cancelled),
            () = operation.cancelled() => Err(Error::Cancelled),
            () = authority.cancelled() => Err(Error::Cancelled),
            // Revocation and expiry are decided by the leased hand-off.
            () = master_revoked => Ok(()),
            () = expired => Ok(()),
            _ = updates.reserve() => Ok(()),
            () = cancel.cancelled() => Err(Error::Cancelled),
        }
    }
}

impl SavedTurnClientPhases for LeasedTurnPhases<'_> {
    fn check<'a>(
        &'a mut self,
        scope: &'a AsyncCryptoScope,
        chat: &'a str,
        generation: u64,
    ) -> TurnPhaseFuture<'a, ()> {
        leased!(self, check(scope, chat, generation))
    }
    fn deliver_update<'a>(
        &'a mut self,
        scope: &'a AsyncCryptoScope,
        chat: &'a str,
        updates: &'a mpsc::Sender<StreamUpdate>,
        cancel: &'a CancellationToken,
        update: StreamUpdate,
    ) -> TurnPhaseFuture<'a, ()> {
        Box::pin(async move {
            let marker = matches!(
                &update,
                StreamUpdate::Started { .. }
                    | StreamUpdate::Submitted { .. }
                    | StreamUpdate::Admitted { .. }
                    | StreamUpdate::Status(_)
            );
            let update = Plain::new(update);
            self.capacity(updates, cancel, marker).await?;
            let client = self.lease.lease().await?;
            client
                .deliver_turn_update(scope, chat, updates, cancel, update.into_inner())
                .await
        })
    }
    fn persist_focus_event<'a>(
        &'a mut self,
        ws: &'a mut Socket,
        kind: &'a str,
        event: &'a Value,
        chat: &'a str,
        key: &'a [u8; 32],
        previous: &'a mut Value,
    ) -> TurnPhaseFuture<'a, ()> {
        leased!(
            self,
            persist_focus_event(ws, kind, event, chat, key, previous)
        )
    }
    fn project_routing_catalog<'a>(&'a mut self, id: &'a str) -> TurnPhaseFuture<'a, Vec<Value>> {
        leased!(self, project_routing_catalog(id))
    }
    fn subchat_consent<'a>(
        &'a mut self,
        ws: &'a mut Socket,
        event: &'a Value,
        chat: &'a str,
        task: &'a str,
        updates: &'a mpsc::Sender<StreamUpdate>,
        cancel: &'a CancellationToken,
        policy: SendConsentPolicy,
    ) -> TurnPhaseFuture<'a, Vec<(String, Value)>> {
        leased!(
            self,
            subchat_consent(ws, event, chat, task, updates, cancel, policy)
        )
    }
    fn memory_consent<'a>(
        &'a mut self,
        ws: &'a mut Socket,
        event: &'a Value,
        chat: &'a str,
        message: &'a str,
        key: &'a [u8; 32],
        memories: &'a [Value],
        mappings: &'a [Value],
        updates: &'a mpsc::Sender<StreamUpdate>,
        cancel: &'a CancellationToken,
        policy: SendConsentPolicy,
    ) -> TurnPhaseFuture<'a, (Vec<(String, Value)>, SendMemoryRequest, Vec<Value>)> {
        leased!(
            self,
            memory_consent(
                ws, event, chat, message, key, memories, mappings, updates, cancel, policy
            )
        )
    }
    fn replay_outputs<'a>(
        &'a mut self,
        ws: &'a mut Socket,
        outputs: &'a BTreeMap<String, Value>,
        root: Option<(&'a str, &'a [u8; 32])>,
    ) -> TurnPhaseFuture<'a, usize> {
        leased!(self, replay_outputs(ws, outputs, root))
    }
    fn persist_stream_artifacts<'a>(
        &'a mut self,
        ws: &'a mut Socket,
        chat: &'a str,
        message: &'a str,
        key: &'a [u8; 32],
        task: &'a str,
        embeds: &'a BTreeMap<String, Value>,
        checkpoints: &'a [Value],
    ) -> TurnPhaseFuture<'a, Vec<Item>> {
        leased!(
            self,
            persist_stream_artifacts(ws, chat, message, key, task, embeds, checkpoints)
        )
    }
    fn open_chat_live<'a>(&'a mut self, id: &'a str) -> TurnPhaseFuture<'a, Chat> {
        leased!(self, open_chat_live(id))
    }
    fn finish_task_jobs<'a>(
        &'a mut self,
        ws: &'a mut Socket,
        observed: &'a mut SendObservations,
        id: &'a str,
        message: &'a str,
        key: &'a [u8; 32],
        cancel: &'a CancellationToken,
        options: &'a SendOptions,
    ) -> TurnPhaseFuture<'a, ()> {
        leased!(
            self,
            finish_task_jobs(ws, observed, id, message, key, cancel, options)
        )
    }
    fn project_create<'a>(
        &'a mut self,
        ws: &'a mut Socket,
        kind: &'a str,
        event: &'a Value,
        chat: &'a str,
        state: &'a mut project_create_request::ProjectCreateState,
    ) -> TurnPhaseFuture<'a, ()> {
        leased!(self, project_create(ws, kind, event, chat, state))
    }
    fn owner_id(&mut self) -> TurnPhaseFuture<'_, String> {
        leased!(self, owner_id())
    }
    fn current_messages_version<'a>(
        &'a mut self,
        id: &'a str,
        key: &'a [u8; 32],
        version: u64,
    ) -> TurnPhaseFuture<'a, u64> {
        leased!(self, current_messages_version(id, key, version))
    }
}

#[cfg(test)]
#[path = "send_split_tests.rs"]
mod tests;
