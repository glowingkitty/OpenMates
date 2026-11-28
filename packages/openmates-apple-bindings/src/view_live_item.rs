//! Live collaboration items for the Apple shell (spec `feature.live-collaboration`,
//! `live-collab.core.live-session`): marshalling only. One `LiveItemSession` keeps the
//! core `LiveSession` and `IoState` between calls and runs `LiveDriver<ClientLiveIo>` on the
//! signed-in `Client` held by the view-model actor, exactly as the web Worker binding
//! (`browser_live_item.rs`) does. Swift sends frames on the `/v1/ws` socket, stores opaque
//! outbox bytes and receives events; it holds no live logic and no Yjs.
use crate::view_core::ViewModelCore;
use crate::view_embeds::EmbedEditError;
use openmates_sdk::client::live::client_io::{
    ClientLiveIo, IoState, LiveSend, OutboxStorage, OutboxStorageFuture,
};
use openmates_sdk::client::live::driver::{ASSISTANT_FRAME_PREFIX, FRAME_PREFIX, LiveDriver};
use openmates_sdk::client::live::session::LiveSession;
use openmates_sdk::client::live::session_types::{Action, Event};
use openmates_sdk::client::live::session_wire::action_event;
use openmates_sdk::client::live::{LiveError, LiveItemKind, ops_json};
use std::rc::Rc;
use std::sync::{Arc, Mutex as StdMutex, MutexGuard};
use std::time::{SystemTime, UNIX_EPOCH};

/// Sends outgoing live frames on the authenticated `/v1/ws` socket. Swift implements it
/// with `sendUnownedFrame`. Called on a core thread; it must return at once.
#[uniffi::export(foreign)]
pub trait LiveItemSender: Send + Sync {
    /// Queue one frame `{"type": message_type, "payload": <payload_json>}`; `false` when
    /// the socket is closed or the frame could not be queued (the core retries on reconnect).
    fn send_frame(&self, message_type: String, payload_json: String) -> bool;
}

/// Result of reading one opaque outbox record.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum LiveOutboxReadRecord {
    /// No record under the key.
    Missing,
    /// The stored text.
    Found {
        /// Stored value.
        value: String,
    },
    /// Storage failed (distinct from absence).
    Unavailable,
}

/// Result of a compare-and-put on an outbox record.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum LiveOutboxWriteRecord {
    /// The record was replaced or removed.
    Written,
    /// The stored bytes differ from `expected`: nothing was changed.
    Conflict,
    /// Storage failed.
    Unavailable,
}

/// Opaque durable storage for the sealed update queue, backed by Swift's encrypted store.
/// It never sees item keys or plaintext; calls are synchronous and must return quickly.
#[uniffi::export(foreign)]
pub trait LiveOutboxStorage: Send + Sync {
    /// Keys beginning with `prefix`; `None` when storage failed.
    fn keys(&self, prefix: String) -> Option<Vec<String>>;
    /// The record under `key`.
    fn read(&self, key: String) -> LiveOutboxReadRecord;
    /// Replace (`next` set) or delete (`next` nil) the record only if it still holds
    /// `expected` (`nil`: absent).
    fn compare_and_put(
        &self,
        key: String,
        expected: Option<String>,
        next: Option<String>,
    ) -> LiveOutboxWriteRecord;
}

/// One live event for Swift.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum LiveItemEventRecord {
    /// Plain Yjs v1 update bytes for a document or code item.
    RemoteUpdate {
        /// Item id.
        item_id: String,
        /// Update bytes.
        bytes: Vec<u8>,
    },
    /// Any other event: `liveView`, `livePresence`, `liveStatus`, `livePrivateCopy`,
    /// `liveVersion` with the core's camelCase JSON payload (`session_wire`).
    Named {
        /// Event name.
        name: String,
        /// JSON object text.
        payload_json: String,
    },
}

/// Receives live events in order on a core thread; it must not block.
#[uniffi::export(foreign)]
pub trait LiveItemListener: Send + Sync {
    /// One event.
    fn on_live_event(&self, event: LiveItemEventRecord);
}

/// A restored version: its new checkpoint number and text.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct LiveRestoreRecord {
    /// Version written by the restore.
    pub version: i64,
    /// Restored text form.
    pub content: String,
}

struct AppleSend(Arc<dyn LiveItemSender>);

impl LiveSend for AppleSend {
    fn send(&self, message_type: &str, payload_json: &str) -> Result<(), LiveError> {
        if self
            .0
            .send_frame(message_type.to_owned(), payload_json.to_owned())
        {
            Ok(())
        } else {
            Err(LiveError::Io("live_not_connected"))
        }
    }
}

struct AppleOutbox(Arc<dyn LiveOutboxStorage>);

const UNAVAILABLE: LiveError = LiveError::Io("live_outbox_unavailable");

impl OutboxStorage for AppleOutbox {
    fn keys<'a>(&'a self, prefix: &'a str) -> OutboxStorageFuture<'a, Vec<String>> {
        Box::pin(async move { self.0.keys(prefix.to_owned()).ok_or(UNAVAILABLE) })
    }

    fn read<'a>(&'a self, key: &'a str) -> OutboxStorageFuture<'a, Option<String>> {
        Box::pin(async move {
            match self.0.read(key.to_owned()) {
                LiveOutboxReadRecord::Missing => Ok(None),
                LiveOutboxReadRecord::Found { value } => Ok(Some(value)),
                LiveOutboxReadRecord::Unavailable => Err(UNAVAILABLE),
            }
        })
    }

    fn compare_and_put<'a>(
        &'a self,
        key: &'a str,
        expected: Option<&'a str>,
        next: Option<&'a str>,
    ) -> OutboxStorageFuture<'a, bool> {
        Box::pin(async move {
            match self.0.compare_and_put(
                key.to_owned(),
                expected.map(str::to_owned),
                next.map(str::to_owned),
            ) {
                LiveOutboxWriteRecord::Written => Ok(true),
                LiveOutboxWriteRecord::Conflict => Ok(false),
                LiveOutboxWriteRecord::Unavailable => Err(UNAVAILABLE),
            }
        })
    }
}

/// The session and I/O state that outlive one call.
struct Live {
    session: LiveSession,
    state: IoState,
}

/// `Live` holds `Rc` handles (the core's I/O state is single-threaded by design).
struct Guarded(Live);

// SAFETY: every `Rc` inside `Live` is created in `LiveItemSession::new` around an
// `Arc<dyn ... + Send + Sync>` and never cloned out of the struct; the struct is only
// reached through the `StdMutex` that wraps it, so the non-atomic reference counts are
// never touched from two threads at once. Calls run to completion on one thread
// (`block_in_place`), so nothing borrowed from it crosses an await point of a `Send` future.
unsafe impl Send for Guarded {}

/// Whether `message_type` is a live frame the core consumes (`live_item_*`,
/// `embed_assistant_*`). Feed those frames, and only those, to `LiveItemSession.onFrame`.
#[uniffi::export]
pub fn live_is_frame(message_type: String) -> bool {
    message_type.starts_with(FRAME_PREFIX) || message_type.starts_with(ASSISTANT_FRAME_PREFIX)
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| elapsed.as_millis() as u64)
}

fn failed(error: LiveError) -> EmbedEditError {
    EmbedEditError::Unavailable {
        code: error.code().to_owned(),
    }
}

/// Maps one core event to its Swift record (`None` for events the shell never sees).
pub(crate) fn event_record(event: Event) -> Option<LiveItemEventRecord> {
    if let Event::RemoteUpdate { item_id, bytes } = event {
        return Some(LiveItemEventRecord::RemoteUpdate { item_id, bytes });
    }
    let (name, payload) = action_event(&Action::Emit(event))?;
    Some(LiveItemEventRecord::Named {
        name: name.to_owned(),
        payload_json: payload.to_string(),
    })
}

fn live_lock(live: &StdMutex<Guarded>) -> MutexGuard<'_, Guarded> {
    // A poisoned lock only means an earlier call panicked; the state is still consistent
    // because the session is put back before any fallible step is reported.
    live.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
}

/// One signed-in user's live collaboration replica on this device. Create one per
/// signed-in session, after `ViewModelCore` is signed in; calls queue on the core actor and
/// fail with `EmbedEditError` (`Unavailable` carrying the core's stable `live_*` code,
/// `Authentication`, `Offline`, ...). Events arrive on the listener, never as return values.
#[derive(uniffi::Object)]
pub struct LiveItemSession {
    core: Arc<ViewModelCore>,
    live: Arc<StdMutex<Guarded>>,
    listener: Arc<dyn LiveItemListener>,
}

#[uniffi::export]
impl LiveItemSession {
    /// A session for `user_id` (contributor of stored versions) using `core`'s signed-in
    /// client, sending frames through `sender`, persisting the outbox in `storage`.
    #[uniffi::constructor]
    pub fn new(
        core: Arc<ViewModelCore>,
        user_id: String,
        sender: Arc<dyn LiveItemSender>,
        storage: Arc<dyn LiveOutboxStorage>,
        listener: Arc<dyn LiveItemListener>,
    ) -> Arc<Self> {
        let mut session = LiveSession::default();
        session.set_user(&user_id);
        let mut state = IoState::default();
        state.send = Some(Rc::new(AppleSend(sender)));
        state.outbox_storage = Some(Rc::new(AppleOutbox(storage)));
        Arc::new(Self {
            core,
            live: Arc::new(StdMutex::new(Guarded(Live { session, state }))),
            listener,
        })
    }

    /// The materialized text of an open item (document HTML, sheet or code text); `nil`
    /// when it is not open or empty. Non-blocking apart from a running call.
    pub fn text_of(&self, item_id: String) -> Option<String> {
        live_lock(&self.live).0.session.text_of(&item_id)
    }

    /// Opens and subscribes an item. `kind`: `doc`, `sheet`, `code` or `deck`; `project_id`
    /// and `team_id` are the scope the embed is shown in. Its state arrives as events.
    ///
    /// # Errors
    /// `Unavailable { live_unknown_kind | live_* }` and the actor errors.
    pub async fn open(
        &self,
        item_id: String,
        kind: String,
        project_id: Option<String>,
        team_id: Option<String>,
    ) -> Result<(), EmbedEditError> {
        let kind = LiveItemKind::parse(&kind).map_err(failed)?;
        self.drive(move |live, client| {
            live.state.kinds.insert(item_id.clone(), kind);
            match project_id {
                Some(project) => live.state.projects.insert(item_id.clone(), project),
                None => live.state.projects.remove(&item_id),
            };
            match team_id {
                Some(team) => live.state.teams.insert(item_id.clone(), team),
                None => live.state.teams.remove(&item_id),
            };
            run_driver_value(live, client, move |driver| {
                Box::pin(async move { driver.open(&item_id, kind, now_ms()).await.map(|events| (events, ())) })
            })
        })
        .await
    }

    /// Applies a local Yjs update (documents and code text).
    ///
    /// # Errors
    /// `Unavailable { live_invalid_update | live_* }` and the actor errors.
    pub async fn apply_update(&self, item_id: String, bytes: Vec<u8>) -> Result<(), EmbedEditError> {
        self.drive(move |live, client| {
            run_driver_value(live, client, move |driver| {
                Box::pin(async move {
                    driver
                        .apply_mirror_update(&item_id, &bytes, now_ms())
                        .await
                        .map(|events| (events, ()))
                })
            })
        })
        .await
    }

    /// Applies one typed operation (`ops_json`: sheet, deck, code).
    ///
    /// # Errors
    /// `Unavailable { live_invalid_update }` for a malformed operation, plus `live_*`.
    pub async fn apply_op(&self, item_id: String, op_json: String) -> Result<(), EmbedEditError> {
        let op = ops_json::parse_op(&op_json).map_err(failed)?;
        self.drive(move |live, client| {
            run_driver_value(live, client, move |driver| {
                Box::pin(async move { driver.apply_local_op(&item_id, op, now_ms()).await.map(|events| (events, ())) })
            })
        })
        .await
    }

    /// Sets local presence (JSON object); sealed in the core and relayed.
    ///
    /// # Errors
    /// `Unavailable { live_* }` and the actor errors.
    pub async fn set_presence(
        &self,
        item_id: String,
        presence_json: String,
    ) -> Result<(), EmbedEditError> {
        self.drive(move |live, client| {
            run_driver_value(live, client, move |driver| {
                Box::pin(async move {
                    driver
                        .set_presence(&item_id, &presence_json, now_ms())
                        .await
                        .map(|events| (events, ()))
                })
            })
        })
        .await
    }

    /// Closes an item (writes the pending checkpoint).
    ///
    /// # Errors
    /// `Unavailable { live_* }` and the actor errors.
    pub async fn close(&self, item_id: String) -> Result<(), EmbedEditError> {
        self.drive(move |live, client| {
            run_driver_value(live, client, move |driver| {
                Box::pin(async move { driver.close(&item_id, now_ms()).await.map(|events| (events, ())) })
            })
        })
        .await
    }

    /// Reports the socket state: resubscribes and resends the outbox on connect.
    ///
    /// # Errors
    /// `Unavailable { live_* }` and the actor errors.
    pub async fn set_connected(&self, connected: bool) -> Result<(), EmbedEditError> {
        self.drive(move |live, client| {
            run_driver_value(live, client, move |driver| {
                Box::pin(async move { driver.set_connected(connected, now_ms()).await.map(|events| (events, ())) })
            })
        })
        .await
    }

    /// Periodic tick (every 2 seconds while an item is open): presence expiry and due
    /// checkpoints.
    ///
    /// # Errors
    /// `Unavailable { live_* }` and the actor errors.
    pub async fn tick(&self) -> Result<(), EmbedEditError> {
        self.drive(move |live, client| {
            run_driver_value(live, client, move |driver| {
                Box::pin(async move { driver.tick(now_ms()).await.map(|events| (events, ())) })
            })
        })
        .await
    }

    /// Feeds one server frame (`live_item_state`, `live_item_update_ack`, `live_item_update`,
    /// `live_item_snapshot_available`, `live_item_presence`, `live_item_refused`,
    /// `embed_assistant_*`). `false` when it was not a live frame.
    ///
    /// # Errors
    /// `Unavailable { protocol }` for a payload that is not JSON, plus `live_*`.
    pub async fn on_frame(
        &self,
        message_type: String,
        payload_json: String,
    ) -> Result<bool, EmbedEditError> {
        if !live_is_frame(message_type.clone()) {
            return Ok(false);
        }
        let payload: serde_json::Value =
            serde_json::from_str(&payload_json).map_err(|_| EmbedEditError::Unavailable {
                code: "protocol".to_owned(),
            })?;
        self.drive(move |live, client| {
            run_driver_value(live, client, move |driver| {
                Box::pin(async move {
                    let Some(mut events) = driver.on_frame(&message_type, &payload, now_ms()).await?
                    else {
                        return Ok((Vec::new(), false));
                    };
                    // Assistant changes for items that are not open: open, then feed again.
                    for (embed_id, frame) in driver.io_mut().take_pending_opens() {
                        let kind = driver.io_mut().kind_of(&embed_id).await?;
                        events.extend(driver.open(&embed_id, kind, now_ms()).await?);
                        driver.session_mut().mark_headless(&embed_id);
                        if let Some(more) = driver
                            .on_frame("embed_assistant_change", &frame, now_ms())
                            .await?
                        {
                            events.extend(more);
                        }
                    }
                    events.extend(driver.close_settled_headless(now_ms()).await?);
                    Ok((events, true))
                })
            })
        })
        .await
    }

    /// Restores an older version on the open item and returns its new checkpoint.
    ///
    /// # Errors
    /// `Unavailable { live_restore_stale | live_restore_checkpoint_failed | live_* }`.
    pub async fn restore_version(
        &self,
        item_id: String,
        source: i64,
        head: i64,
    ) -> Result<LiveRestoreRecord, EmbedEditError> {
        self.drive(move |live, client| {
            run_driver_value(live, client, move |driver| {
                Box::pin(async move {
                    let (events, version, content) = driver
                        .restore_version(&item_id, source, head, now_ms())
                        .await?;
                    Ok((events, LiveRestoreRecord { version, content }))
                })
            })
        })
        .await
    }

    /// Handles an editor Undo when the assistant authored the latest change: `true` when
    /// the assistant's change was undone.
    ///
    /// # Errors
    /// `Unavailable { live_* }` and the actor errors.
    pub async fn undo_latest_assistant(&self, item_id: String) -> Result<bool, EmbedEditError> {
        self.drive(move |live, client| {
            run_driver_value(live, client, move |driver| {
                Box::pin(async move {
                    let events = driver.undo_latest_assistant(&item_id, now_ms()).await?;
                    let undone = !events.is_empty();
                    Ok((events, undone))
                })
            })
        })
        .await
    }
}

type DriverFuture<'d, T> =
    futures_util::future::LocalBoxFuture<'d, Result<(Vec<Event>, T), LiveError>>;
type Io<'a> = ClientLiveIo<'a>;

fn run_driver_value<T, F>(
    live: &mut Live,
    client: &mut openmates_sdk::client::Client,
    work: F,
) -> Result<(Vec<Event>, T), EmbedEditError>
where
    F: for<'d, 'a> FnOnce(&'d mut LiveDriver<Io<'a>>) -> DriverFuture<'d, T>,
{
    let session = std::mem::take(&mut live.session);
    let io = ClientLiveIo::new(client, &mut live.state);
    let mut driver = LiveDriver::with_session(session, io);
    let result = tokio::runtime::Handle::current().block_on(work(&mut driver));
    let (session, _) = driver.into_parts();
    live.session = session;
    result.map_err(failed)
}

impl LiveItemSession {
    /// Runs `work` on the signed-in client under the core actor; the driver future is
    /// single-threaded, so it runs in place on the worker thread (`block_in_place`), and its
    /// events reach the listener after the call (also those of a failed call are dropped).
    async fn drive<T, F>(&self, work: F) -> Result<T, EmbedEditError>
    where
        T: Send + 'static,
        F: FnOnce(
                &mut Live,
                &mut openmates_sdk::client::Client,
            ) -> Result<(Vec<Event>, T), EmbedEditError>
            + Send
            + 'static,
    {
        let live = self.live.clone();
        let (events, value) = self
            .core
            .embed_command(None, move |client| {
                Box::pin(async move {
                    tokio::task::block_in_place(move || {
                        let mut guard = live_lock(&live);
                        work(&mut guard.0, client)
                    })
                })
            })
            .await?;
        for event in events.into_iter().filter_map(event_record) {
            self.listener.on_live_event(event);
        }
        Ok(value)
    }
}

#[cfg(test)]
#[path = "view_live_item_tests.rs"]
mod view_live_item_tests;
