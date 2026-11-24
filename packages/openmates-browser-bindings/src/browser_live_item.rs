//! Worker glue of live collaboration items. The core `Client` runs a
//! `LiveDriver<ClientLiveIo>` (`openmates_sdk::client::live`): this file only keeps the
//! driver's long-lived state between calls, forwards typed calls and server frames into it,
//! and pushes the resulting events and outgoing frames to the page. No live logic lives here
//! (`.claude/rules/client-core.md`). Errors reject with the core's stable code string.
use super::BrowserCoreClient;
use js_sys::{Array, Function, Object, Promise, Reflect, Uint8Array};
use openmates_sdk::client::live::client_io::{
    ClientLiveIo, IoState, LiveSend, OutboxStorage, OutboxStorageFuture,
};
use openmates_sdk::client::live::driver::{ASSISTANT_FRAME_PREFIX, FRAME_PREFIX, LiveDriver};
use openmates_sdk::client::live::session::LiveSession;
use openmates_sdk::client::live::session_types::{Action, Event};
use openmates_sdk::client::live::session_wire::action_event;
use openmates_sdk::client::live::{LiveError, LiveItemKind, ops_json};
use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;
use wasm_bindgen::prelude::*;
use wasm_bindgen_futures::JsFuture;

struct JsSend(Function);

impl LiveSend for JsSend {
    fn send(&self, message_type: &str, payload_json: &str) -> Result<(), LiveError> {
        self.0
            .call2(
                &JsValue::NULL,
                &JsValue::from_str(message_type),
                &JsValue::from_str(payload_json),
            )
            .map(|_| ())
            .map_err(|_| LiveError::Io("live_not_connected"))
    }
}

struct JsOutbox {
    keys: Function,
    read: Function,
    compare_and_put: Function,
}

impl OutboxStorage for JsOutbox {
    fn keys<'a>(&'a self, prefix: &'a str) -> OutboxStorageFuture<'a, Vec<String>> {
        Box::pin(async move {
            let result = await_outbox(self.keys.call1(&JsValue::NULL, &prefix.into())).await?;
            if !Array::is_array(&result) {
                return Err(LiveError::Io("live_outbox_unavailable"));
            }
            Array::from(&result)
                .iter()
                .map(|key| {
                    key.as_string()
                        .ok_or(LiveError::Io("live_outbox_unavailable"))
                })
                .collect()
        })
    }

    fn read<'a>(&'a self, key: &'a str) -> OutboxStorageFuture<'a, Option<String>> {
        Box::pin(async move {
            let result = await_outbox(self.read.call1(&JsValue::NULL, &key.into())).await?;
            if result.is_null() {
                return Ok(None);
            }
            result
                .as_string()
                .map(Some)
                .ok_or(LiveError::Io("live_outbox_unavailable"))
        })
    }

    fn compare_and_put<'a>(
        &'a self,
        key: &'a str,
        expected: Option<&'a str>,
        next: Option<&'a str>,
    ) -> OutboxStorageFuture<'a, bool> {
        Box::pin(async move {
            let bytes = |value: Option<&str>| value.map(JsValue::from_str).unwrap_or(JsValue::NULL);
            let result = await_outbox(self.compare_and_put.call3(
                &JsValue::NULL,
                &key.into(),
                &bytes(expected),
                &bytes(next),
            ))
            .await?;
            result
                .as_bool()
                .ok_or(LiveError::Io("live_outbox_unavailable"))
        })
    }
}

async fn await_outbox(result: Result<JsValue, JsValue>) -> Result<JsValue, LiveError> {
    let value = result.map_err(|_| LiveError::Io("live_outbox_unavailable"))?;
    JsFuture::from(Promise::resolve(&value))
        .await
        .map_err(|_| LiveError::Io("live_outbox_unavailable"))
}

/// Everything that outlives one call: the session, the I/O state and the event sink.
struct Live {
    session: LiveSession,
    state: IoState,
    sink: Function,
}

thread_local! {
    // Each page owns a socket and receives acknowledgements for its replica.
    // Opening a second Worker port must not replace the first page's replica.
    static LIVE: RefCell<HashMap<String, Option<Live>>> = RefCell::new(HashMap::new());
}

fn js<T>(result: Result<T, LiveError>) -> Result<T, JsValue> {
    result.map_err(|error| JsValue::from_str(error.code()))
}

fn now() -> u64 {
    js_sys::Date::now() as u64
}

fn take(connection: &str) -> Result<Live, JsValue> {
    LIVE.with(|cell| cell.borrow_mut().get_mut(connection).and_then(Option::take))
        .ok_or_else(|| JsValue::from_str("live_not_configured"))
}

impl Live {
    /// Puts the state back, then delivers the events (also those of a failed call) and
    /// returns the call's result.
    fn finish<T>(
        self,
        connection: &str,
        result: Result<(Vec<Event>, T), LiveError>,
    ) -> Result<T, JsValue> {
        let (events, value) = match result {
            Ok((events, value)) => (events, Ok(value)),
            Err(error) => (Vec::new(), Err(JsValue::from_str(error.code()))),
        };
        let sink = self.sink.clone();
        let active = LIVE.with(|cell| {
            let mut connections = cell.borrow_mut();
            let Some(slot) = connections.get_mut(connection) else {
                return false;
            };
            *slot = Some(self);
            true
        });
        if active {
            for event in events {
                deliver(&sink, event);
            }
        }
        value
    }
}

fn push(sink: &Function, event: &str, payload: &JsValue) {
    let _ = sink.call2(&JsValue::NULL, &JsValue::from_str(event), payload);
}

fn deliver(sink: &Function, event: Event) {
    if let Event::RemoteUpdate { item_id, bytes } = &event {
        let payload = Object::new();
        let _ = Reflect::set(&payload, &"itemId".into(), &item_id.as_str().into());
        let _ = Reflect::set(
            &payload,
            &"bytes".into(),
            &Uint8Array::from(bytes.as_slice()),
        );
        push(sink, "liveRemoteUpdate", &payload);
    } else if let Some((name, value)) = action_event(&Action::Emit(event))
        && let Ok(payload) = js_sys::JSON::parse(&value.to_string())
    {
        push(sink, name, &payload);
    }
}

/// Runs `$body` (an async block using the driver `$d`) over the stored session and a
/// `ClientLiveIo` borrowing the core client for this call only.
macro_rules! drive {
    ($connection:expr, $client:expr, $d:ident => $body:expr) => {{
        let mut live = take($connection)?;
        let session = std::mem::take(&mut live.session);
        let io = ClientLiveIo::new(&mut $client, &mut live.state);
        let mut $d = LiveDriver::with_session(session, io);
        let result = $body.await;
        let (session, _) = $d.into_parts();
        live.session = session;
        live.finish($connection, result)
    }};
}

/// Installs one page's replica and callbacks for the corresponding WebSocket.
#[wasm_bindgen]
pub fn live_configure(
    connection: &str,
    sink: Function,
    send: Function,
    list_outbox: Function,
    read_outbox: Function,
    compare_and_put_outbox: Function,
) {
    let mut state = IoState::default();
    state.send = Some(Rc::new(JsSend(send)));
    state.outbox_storage = Some(Rc::new(JsOutbox {
        keys: list_outbox,
        read: read_outbox,
        compare_and_put: compare_and_put_outbox,
    }));
    LIVE.with(|cell| {
        cell.borrow_mut().insert(
            connection.to_owned(),
            Some(Live {
                session: LiveSession::default(),
                state,
                sink,
            }),
        );
    });
}

/// Releases a page replica when its Worker port closes.
#[wasm_bindgen]
pub fn live_dispose(connection: &str) {
    LIVE.with(|cell| cell.borrow_mut().remove(connection));
}

/// Host: the signed-in user id (contributor of versions).
#[wasm_bindgen]
pub fn live_set_user(connection: &str, user_id: &str) -> Result<(), JsValue> {
    let mut live = take(connection)?;
    live.session.set_user(user_id);
    live.finish(connection, Ok((Vec::new(), ())))
}

/// Whether `message_type` is a live frame the core consumes (`live_item_*`, `embed_assistant_*`).
#[wasm_bindgen]
pub fn live_is_frame(message_type: &str) -> bool {
    message_type.starts_with(FRAME_PREFIX) || message_type.starts_with(ASSISTANT_FRAME_PREFIX)
}

#[wasm_bindgen]
impl BrowserCoreClient {
    fn live_writable(&self, handle: &str, generation: f64) -> Result<(), JsValue> {
        if self.status(handle, generation)?.local_read_only() {
            return Err(JsValue::from_str("session_expired"));
        }
        Ok(())
    }

    /// Opens a Team-encrypted Project head in the Worker without exporting a key.
    pub async fn live_open_team_revision_content(
        &mut self,
        handle: &str,
        generation: f64,
        team: &str,
        item_id: &str,
        version: i32,
        ciphertext: &str,
        display_text: bool,
    ) -> Result<Option<String>, JsValue> {
        self.live_writable(handle, generation)?;
        let version = i64::from(version);
        let opened = if display_text {
            self.client
                .open_team_revision_text(team, item_id, version, ciphertext)
                .await
        } else {
            self.client
                .open_team_revision_content(team, item_id, version, ciphertext)
                .await
        };
        opened
            .map(|plain| plain.map(|value| value.to_string()))
            .map_err(crate::browser_chat_state::error_code)
    }

    /// Publishes private copies of known pending items whose access was lost.
    pub async fn live_scan_recovery(
        &mut self,
        connection: &str,
        handle: &str,
        generation: f64,
    ) -> Result<(), JsValue> {
        self.live_writable(handle, generation)?;
        drive!(connection, self.client, d => async {
            let events = d.io_mut().revoked_private_copies().await?;
            Ok((events, ()))
        })
    }

    /// Opens an item; its full state reaches the page as `liveRemoteUpdate` / `liveView`.
    pub async fn live_open(
        &mut self,
        connection: &str,
        handle: &str,
        generation: f64,
        item_id: &str,
        kind: &str,
        project_id: Option<String>,
        team_id: Option<String>,
    ) -> Result<(), JsValue> {
        self.live_writable(handle, generation)?;
        let kind = js(LiveItemKind::parse(kind))?;
        if let Some(team) = &team_id {
            uuid::Uuid::parse_str(team).map_err(|_| JsValue::from_str("invalid_team_id"))?;
        }
        LIVE.with(|cell| {
            if let Some(Some(live)) = cell.borrow_mut().get_mut(connection) {
                live.state.kinds.insert(item_id.to_owned(), kind);
                match project_id {
                    Some(project) => live.state.projects.insert(item_id.to_owned(), project),
                    None => live.state.projects.remove(item_id),
                };
                match team_id {
                    Some(team) => live.state.teams.insert(item_id.to_owned(), team),
                    None => live.state.teams.remove(item_id),
                };
            }
        });
        drive!(connection, self.client, d => async { d.open(item_id, kind, now()).await.map(|e| (e, ())) })
    }

    /// Update bytes from the page's Yjs mirror (documents and code).
    pub async fn live_apply_mirror_update(
        &mut self,
        connection: &str,
        handle: &str,
        generation: f64,
        item_id: &str,
        bytes: &[u8],
    ) -> Result<(), JsValue> {
        self.live_writable(handle, generation)?;
        drive!(connection, self.client, d => async { d.apply_mirror_update(item_id, bytes, now()).await.map(|e| (e, ())) })
    }

    /// One typed operation JSON (sheet, deck, code).
    pub async fn live_apply_op(
        &mut self,
        connection: &str,
        handle: &str,
        generation: f64,
        item_id: &str,
        op_json: &str,
    ) -> Result<(), JsValue> {
        self.live_writable(handle, generation)?;
        let op = js(ops_json::parse_op(op_json))?;
        drive!(connection, self.client, d => async { d.apply_local_op(item_id, op, now()).await.map(|e| (e, ())) })
    }

    /// Local presence JSON; sealed in the core and relayed.
    pub async fn live_set_presence(
        &mut self,
        connection: &str,
        handle: &str,
        generation: f64,
        item_id: &str,
        presence_json: &str,
    ) -> Result<(), JsValue> {
        self.live_writable(handle, generation)?;
        drive!(connection, self.client, d => async { d.set_presence(item_id, presence_json, now()).await.map(|e| (e, ())) })
    }

    /// Closes an item.
    pub async fn live_close(
        &mut self,
        connection: &str,
        handle: &str,
        generation: f64,
        item_id: &str,
    ) -> Result<(), JsValue> {
        self.live_writable(handle, generation)?;
        drive!(connection, self.client, d => async { d.close(item_id, now()).await.map(|e| (e, ())) })
    }

    /// Restores an older version on the open item and returns its new checkpoint.
    pub async fn live_restore_version(
        &mut self,
        connection: &str,
        handle: &str,
        generation: f64,
        item_id: &str,
        source: f64,
        head: f64,
    ) -> Result<JsValue, JsValue> {
        self.live_writable(handle, generation)?;
        drive!(connection, self.client, d => async {
            let (events, version, content) = d
                .restore_version(item_id, source as i64, head as i64, now())
                .await?;
            Ok((events, serde_json::json!({ "version": version, "content": content })))
        })
        .and_then(|value| js_sys::JSON::parse(&value.to_string()))
    }

    /// Handles an editor Undo when the assistant authored the latest change.
    pub async fn live_undo_latest_assistant(
        &mut self,
        connection: &str,
        handle: &str,
        generation: f64,
        item_id: &str,
    ) -> Result<bool, JsValue> {
        self.live_writable(handle, generation)?;
        drive!(connection, self.client, d => async {
            let events = d.undo_latest_assistant(item_id, now()).await?;
            let undone = !events.is_empty();
            Ok((events, undone))
        })
    }

    /// Host: WebSocket connected or lost.
    pub async fn live_set_connected(
        &mut self,
        connection: &str,
        connected: bool,
    ) -> Result<(), JsValue> {
        drive!(connection, self.client, d => async { d.set_connected(connected, now()).await.map(|e| (e, ())) })
    }

    /// Host: periodic tick (every 2 seconds): presence expiry and due checkpoints.
    pub async fn live_tick(&mut self, connection: &str) -> Result<(), JsValue> {
        drive!(connection, self.client, d => async { d.tick(now()).await.map(|e| (e, ())) })
    }

    /// Host: one server frame. Resolves `true` when it was a live frame the core consumed.
    pub async fn live_on_frame(
        &mut self,
        connection: &str,
        message_type: &str,
        payload_json: &str,
    ) -> Result<bool, JsValue> {
        if !live_is_frame(message_type) {
            return Ok(false);
        }
        let payload: serde_json::Value =
            serde_json::from_str(payload_json).map_err(|_| JsValue::from_str("protocol"))?;
        drive!(connection, self.client, d => async {
            let Some(mut events) = d.on_frame(message_type, &payload, now()).await? else {
                return Ok((Vec::new(), false));
            };
            // Assistant changes for items that are not open: open them, then feed the frame again.
            for (embed_id, frame) in d.io_mut().take_pending_opens() {
                let kind = d.io_mut().kind_of(&embed_id).await?;
                events.extend(d.open(&embed_id, kind, now()).await?);
                d.session_mut().mark_headless(&embed_id);
                if let Some(more) = d.on_frame("embed_assistant_change", &frame, now()).await? {
                    events.extend(more);
                }
            }
            events.extend(d.close_settled_headless(now()).await?);
            Ok((events, true))
        })
    }
}
