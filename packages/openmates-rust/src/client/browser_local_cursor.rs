//! Rust-owned bounded local IDB scheduling under an existing admitted profile.
//! Platform callbacks execute readonly IO; plans are selectors, never authority.
//! Physical index/key order is explicit and no full retained history is hydrated.
//! Every await rechecks owner/key/generation/negative/operation admission.
//! Unknown coverage remains local/incomplete; no writes or durability ACK occur.
//! Around performs one physical-key lookup and two independently bounded legs.
use super::*;
use crate::client::local_cached_read::{LocalCachedBoundary, wire};
use crate::client::message_window::{MessageWindowDirection, MessageWindowOptions};
use crate::client::plaintext::Plain;
use crate::client::saved_chat_read::SavedChatReadOptions;
use serde::Serialize;
use std::future::Future;

const MAX_PACKET_BYTES: usize = 256 * 1024;
// Match the unchanged thin boundedJson whole-envelope limit and reserve.
// The callback producer cannot know the future RPC id. Reserve the complete
// largest-safe-id/fourth-effect frame; the plan fills the empty value below.
const LOCAL_JSON_FRAME_RESERVE_BYTES: usize = 8192;
const MAX_EFFECT_ENVELOPE_FRAMING_BYTES: usize = b"{\"version\":1,\"id\":9007199254740991,\"effectId\":4,\"localReadEffect\":}".len();
const MAX_PLAN_BYTES: usize = MAX_PACKET_BYTES - LOCAL_JSON_FRAME_RESERVE_BYTES - MAX_EFFECT_ENVELOPE_FRAMING_BYTES;
const RECEIPT_RESERVE_BYTES: usize = 2048;
const MAX_CHECKPOINT_ROWS: usize = 128;
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct Bound {
    created_at: i64,
    message_id: Option<String>,
    open: bool,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Plan<'a> {
    version: u8,
    kind: &'static str,
    operation_id: &'a str,
    owner: &'a str,
    chat_id: &'a str,
    max_packet_bytes: usize,
    max_checkpoint_rows: usize,
    max_payload_rows: usize,
    lower: Option<Bound>,
    upper: Option<Bound>,
    direction: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    anchor_message_id: Option<&'a str>,
}
fn closed(value: &Value, keys: &[&str]) -> bool {
    value.as_object().is_some_and(|object| {
        object.len() == keys.len() && keys.iter().all(|key| object.contains_key(*key))
    })
}
fn version(value: &Value) -> Result<u64> {
    value
        .as_u64()
        .filter(|v| (1..=9_007_199_254_740_991).contains(v))
        .ok_or(Error::Protocol)
}
fn raw_position(value: &Value) -> Result<(i64, &str)> {
    if !closed(value, &["createdAt", "messageId"]) {
        return Err(Error::Protocol);
    }
    let time = value["createdAt"]
        .as_i64()
        .filter(|v| (0..=9_007_199_254_740_991).contains(v))
        .ok_or(Error::Protocol)?;
    let id = required(value, "messageId")?;
    wire::storage_id(id)?;
    Ok((time, id))
}
fn local_plan_bytes(plan: &Plan<'_>) -> Result<usize> {
    crate::client::monitor::cached_view::bounded_bytes(plan, MAX_PLAN_BYTES).ok_or(Error::Protocol)
}
fn in_range(position: (i64, &str), lower: Option<&Bound>, upper: Option<&Bound>) -> bool {
    let lower_ok = lower.is_none_or(|bound| {
        if let Some(id) = &bound.message_id {
            wire::position_cmp(position, (bound.created_at, id.as_str())).is_gt()
                || !bound.open && position == (bound.created_at, id.as_str())
        } else {
            position.0 > bound.created_at || !bound.open && position.0 == bound.created_at
        }
    });
    let upper_ok = upper.is_none_or(|bound| {
        if let Some(id) = &bound.message_id {
            wire::position_cmp(position, (bound.created_at, id.as_str())).is_lt()
                || !bound.open && position == (bound.created_at, id.as_str())
        } else {
            position.0 < bound.created_at || !bound.open && position.0 == bound.created_at
        }
    });
    lower_ok && upper_ok
}
impl Client {
    async fn local_cursor_io<F, Fut>(
        &self,
        principal: &str,
        chat: &str,
        scope: &sync_capability::AsyncCryptoScope,
        plan: &Plan<'_>,
        io: &mut F,
    ) -> Result<Plain<Value>>
    where
        F: FnMut(String) -> Fut,
        Fut: Future<Output = Result<String>>,
    {
        scope.check_chat(self, chat)?;
        self.browser_local_read_scope(principal, chat)?;
        local_plan_bytes(plan)?;
        let request = serde_json::to_string(plan)?;
        // Own/wipe a successful rich IO string before any post-await refusal.
        let result = io(request).await.map(zeroize::Zeroizing::new);
        scope.check_chat(self, chat)?;
        self.browser_local_read_scope(principal, chat)?;
        let encoded = result?;
        if encoded.len() > plan.max_packet_bytes {
            return Err(Error::Protocol);
        }
        local_json::validate(&encoded)?;
        let value = Plain::new(serde_json::from_str::<Value>(&encoded)?);
        if value["version"] != 1
            || value["operationId"].as_str() != Some(plan.operation_id)
            || value["kind"].as_str() != Some(plan.kind)
        {
            return Err(Error::Protocol);
        }
        Ok(value)
    }
    async fn local_cursor_rows<F, Fut>(
        &self,
        principal: &str,
        chat: &str,
        admission: &sync_capability::AsyncCryptoScope,
        plan: &Plan<'_>,
        database_version: u64,
        io: &mut F,
    ) -> Result<(Plain<Vec<Value>>, bool)>
    where
        F: FnMut(String) -> Fut,
        Fut: Future<Output = Result<String>>,
    {
        let descending = plan.direction == "prev";
        let mut frame = self
            .local_cursor_io(principal, chat, admission, plan, io)
            .await?;
        if !closed(
            &frame,
            &[
                "version",
                "kind",
                "operationId",
                "databaseVersion",
                "messages",
                "nextKey",
                "rangeExhausted",
            ],
        ) || version(&frame["databaseVersion"])? != database_version
        {
            return Err(Error::Protocol);
        }
        let exhausted = frame["rangeExhausted"].as_bool().ok_or(Error::Protocol)?;
        let next = if frame["nextKey"].is_null() {
            None
        } else {
            Some(raw_position(&frame["nextKey"])?)
        };
        if exhausted != next.is_none() {
            return Err(Error::Protocol);
        }
        let raw = frame["messages"].as_array().ok_or(Error::Protocol)?;
        if raw.len() > plan.max_payload_rows || next.is_some() && raw.len() != plan.max_payload_rows
        {
            return Err(Error::Protocol);
        }
        // Retain only a non-private selector before moving the raw row array.
        let next = next.map(|(time, id)| (time, id.to_owned()));
        let mut rows = Plain::new(std::mem::take(frame["messages"].as_array_mut().unwrap()));
        if descending {
            rows.reverse();
        }
        let normalized = Plain::new(wire::message_rows(&rows, chat)?);
        for row in &*normalized {
            if !in_range(
                wire::position(row)?,
                plan.lower.as_ref(),
                plan.upper.as_ref(),
            ) {
                return Err(Error::Protocol);
            }
        }
        if let Some((time, key)) = &next {
            let position = (*time, key.as_str());
            if !in_range(position, plan.lower.as_ref(), plan.upper.as_ref()) {
                return Err(Error::Protocol);
            }
            let edge = if descending {
                normalized.first()
            } else {
                normalized.last()
            }
            .ok_or(Error::Protocol)?;
            let edge = wire::position(edge)?;
            if descending && !wire::position_cmp(position, edge).is_lt()
                || !descending && !wire::position_cmp(position, edge).is_gt() {
                return Err(Error::Protocol);
            }
        }
        Ok((rows, exhausted))
    }
    async fn local_cursor_around<F, Fut>(
        &self,
        principal: &str,
        chat: &str,
        admission: &sync_capability::AsyncCryptoScope,
        operation_id: &str,
        database_version: u64,
        input: crate::client::local_cached_read::LocalEncryptedWindowInput,
        options: SavedChatReadOptions,
        selector: &MessageWindowOptions,
        compression: Option<i64>,
        io: &mut F,
    ) -> Result<zeroize::Zeroizing<String>>
    where
        F: FnMut(String) -> Fut,
        Fut: Future<Output = Result<String>>,
    {
        let mut input = Plain::new(input);
        let remaining =
            |input: &crate::client::local_cached_read::LocalEncryptedWindowInput| -> Result<usize> {
                let bytes =
                    crate::client::monitor::cached_view::bounded_bytes(input, MAX_PACKET_BYTES)
                        .ok_or(Error::Protocol)?;
                MAX_PACKET_BYTES
                    .checked_sub(bytes)
                    .and_then(|n| n.checked_sub(RECEIPT_RESERVE_BYTES))
                    .filter(|n| *n >= 1024)
                    .ok_or(Error::Protocol)
            };
        let anchor_id = selector
            .anchor_message_id
            .as_deref()
            .ok_or(Error::Protocol)?;
        let plan = Plan {
            version: 1,
            kind: "anchor",
            operation_id,
            owner: principal,
            chat_id: chat,
            max_packet_bytes: remaining(&input)?,
            max_checkpoint_rows: 0,
            max_payload_rows: 1,
            lower: None,
            upper: None,
            direction: "next",
            anchor_message_id: Some(anchor_id),
        };
        let mut frame = self
            .local_cursor_io(principal, chat, admission, &plan, io)
            .await?;
        if !closed(
            &frame,
            &[
                "version",
                "kind",
                "operationId",
                "databaseVersion",
                "messages",
            ],
        ) || version(&frame["databaseVersion"])? != database_version
        {
            return Err(Error::Protocol);
        }
        let raw = frame["messages"].as_array().ok_or(Error::Protocol)?;
        if raw.len() > 1 {
            return Err(Error::Protocol);
        }
        let mut anchor = Plain::new(std::mem::take(frame["messages"].as_array_mut().unwrap()));
        let normalized = Plain::new(wire::message_rows(&anchor, chat)?);
        if normalized.is_empty() {
            input.boundary = Some(LocalCachedBoundary {
                has_more_before: None,
                has_more_after: None,
                compression_boundary_timestamp: None,
            });
            return self
                .local_cursor_output(principal, chat, admission, input.into_inner(), options)
                .await;
        }
        let (time, physical) = wire::position(&normalized[0])?;
        if physical != anchor_id {
            return Err(Error::Protocol);
        }
        let bound = Bound {
            created_at: time,
            message_id: Some(physical.to_owned()),
            open: true,
        };
        drop(normalized);
        input.messages.append(&mut anchor);
        let before = (selector.limit - 1) / 2;
        let after = selector.limit - 1 - before;
        let mut has_more_before = None;
        let mut has_more_after = None;
        if before > 0 {
            // The checkpoint bounds the older leg. An explicit retained anchor
            // remains readable even when older than that checkpoint.
            if compression.is_some_and(|cutoff| cutoff >= time) {
                has_more_before = Some(false);
            } else {
                let plan = Plan {
                    version: 1,
                    kind: "messages",
                    operation_id,
                    owner: principal,
                    chat_id: chat,
                    max_packet_bytes: remaining(&input)?,
                    max_checkpoint_rows: 0,
                    max_payload_rows: before,
                    lower: compression.map(|created_at| Bound {
                        created_at,
                        message_id: None,
                        open: true,
                    }),
                    upper: Some(bound.clone()),
                    direction: "prev",
                    anchor_message_id: None,
                };
                let (mut rows, exhausted) = self
                    .local_cursor_rows(principal, chat, admission, &plan, database_version, io)
                    .await?;
                rows.append(&mut input.messages);
                input.messages = rows.into_inner();
                has_more_before = Some(!exhausted);
            }
        }
        if after > 0 {
            let plan = Plan {
                version: 1,
                kind: "messages",
                operation_id,
                owner: principal,
                chat_id: chat,
                max_packet_bytes: remaining(&input)?,
                max_checkpoint_rows: 0,
                max_payload_rows: after,
                // Deployed after range is timestamp-open, so later physical
                // keys sharing the anchor timestamp are not in this leg.
                lower: Some(Bound {
                    created_at: time,
                    message_id: None,
                    open: true,
                }),
                upper: None,
                direction: "next",
                anchor_message_id: None,
            };
            let (mut rows, exhausted) = self
                .local_cursor_rows(principal, chat, admission, &plan, database_version, io)
                .await?;
            input.messages.append(&mut rows);
            has_more_after = Some(!exhausted);
        }
        if input.messages.len() > selector.limit
            || crate::client::monitor::cached_view::bounded_bytes(&*input, MAX_PACKET_BYTES)
                .is_none()
        {
            return Err(Error::Protocol);
        }
        input.boundary = Some(LocalCachedBoundary {
            has_more_before,
            has_more_after,
            compression_boundary_timestamp: None,
        });
        self.local_cursor_output(principal, chat, admission, input.into_inner(), options)
            .await
    }
    async fn local_cursor_metadata<F,Fut>(&self,principal:&str,chat:&str,admission:&sync_capability::AsyncCryptoScope,
        operation_id:&str,io:&mut F)->Result<(Plain<crate::client::local_cached_read::LocalEncryptedWindowInput>,u64)>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        let metadata_plan = Plan {
            version: 1,
            kind: "metadata",
            operation_id: &operation_id,
            owner: principal,
            chat_id: chat,
            max_packet_bytes: MAX_PACKET_BYTES,
            max_checkpoint_rows: MAX_CHECKPOINT_ROWS,
            max_payload_rows: 0,
            lower: None,
            upper: None,
            direction: "next",
            anchor_message_id: None,
        };
        let mut frame = self
            .local_cursor_io(principal, chat, admission, &metadata_plan, io)
            .await?;
        if !closed(
            &frame,
            &[
                "version",
                "kind",
                "operationId",
                "databaseVersion",
                "chat_metadata",
                "messages",
                "wrappers",
                "boundary",
                "compression_checkpoints",
            ],
        ) {
            return Err(Error::Protocol);
        }
        let database_version = version(&frame["databaseVersion"])?;
        // Only validated fixed correlation primitives are removed. All rich
        // source values stay inside guarded JSON during the parser handoff.
        for field in ["version", "kind", "operationId", "databaseVersion"] {
            frame.as_object_mut().unwrap().remove(field);
        }
        let encoded = zeroize::Zeroizing::new(serde_json::to_string(&*frame)?);
        let input = Plain::new(self.browser_local_read_input(&encoded)?);
        if !input.messages.is_empty()
            || input.boundary.is_some()
            || required(&input.chat_metadata, "id")? != chat
        {
            return Err(Error::Protocol);
        }
        admission.check_chat(self,chat)?;self.browser_local_read_scope(principal,chat)?;
        Ok((input,database_version))
    }
    /// One exact retained checkpoint summary. No global PII lookup or history IO.
    /// Uses the same bounded metadata plan and genuine current key capability.
    pub async fn browser_local_checkpoint_summary_with_io_json<F,Fut>(&self,principal:&str,chat:&str,checkpoint_id:&str,mut io:F)->Result<zeroize::Zeroizing<String>>
    where F:FnMut(String)->Fut,Fut:Future<Output=Result<String>> {
        let admission=self.browser_local_read_scope(principal,chat)?;wire::storage_id(checkpoint_id)?;
        let local_scope=self.local_cached_scope()?;let operation_id=uuid::Uuid::new_v4().to_string();
        let (input,_)=self.local_cursor_metadata(principal,chat,&admission,&operation_id,&mut io).await?;
        let wrapping=self.cached_wrapping_capability()?;
        let key=self.chat_key_with_capability_from(&input.chat_metadata,&wrapping,&input.wrappers).await?;
        admission.check_chat(self,chat)?;self.browser_local_read_scope(principal,chat)?;
        let mut output=crate::client::local_cached_read::checkpoint_presentation::project(&input.compression_checkpoints,chat,&key,Some(checkpoint_id),||{
            admission.check_chat(self,chat)?;self.browser_local_read_scope(principal,chat)?;
            if self.local_cached_scope()?!=local_scope{return Err(Error::Cancelled);}Ok(())
        })?;
        const FRAME_LIMIT:usize=crate::client::local_cached_read::checkpoint_presentation::MAX_PRESENTATION_FRAME_BYTES;
        if crate::client::monitor::cached_view::bounded_bytes(&output,FRAME_LIMIT).is_none(){output.mark_oversized();}
        if crate::client::monitor::cached_view::bounded_bytes(&output,FRAME_LIMIT).is_none(){return Err(Error::Protocol);}
        let encoded=zeroize::Zeroizing::new(serde_json::to_string(&output)?);
        admission.check_chat(self,chat)?;self.browser_local_read_scope(principal,chat)?;
        if self.local_cached_scope()?!=local_scope{return Err(Error::Cancelled);}Ok(encoded)
    }
    async fn local_cursor_output(
        &self,
        principal: &str,
        chat: &str,
        admission: &sync_capability::AsyncCryptoScope,
        input: crate::client::local_cached_read::LocalEncryptedWindowInput,
        options: SavedChatReadOptions,
    ) -> Result<zeroize::Zeroizing<String>> {
        admission.check_chat(self, chat)?;
        self.browser_local_read_scope(principal, chat)?;
        let output = self
            .local_cached_saved_chat_read(chat, options, input)
            .await?;
        admission.check_chat(self, chat)?;
        self.browser_local_read_scope(principal, chat)?;
        let encoded = zeroize::Zeroizing::new(serde_json::to_string(&output)?);
        if encoded.len() > MAX_PACKET_BYTES {
            return Err(Error::Protocol);
        }
        admission.check_chat(self, chat)?;
        self.browser_local_read_scope(principal, chat)?;
        Ok(encoded)
    }
    /// Bounded existing local-store read. Callback plans contain only selectors;
    /// they do not enroll a key, authenticate an owner or acknowledge persistence.
    /// Callers retain their existing selection/cancellation publication guards.
    pub async fn browser_local_saved_chat_read_with_io_json<F, Fut>(
        &self,
        principal: &str,
        chat: &str,
        options: SavedChatReadOptions,
        mut io: F,
    ) -> Result<zeroize::Zeroizing<String>>
    where
        F: FnMut(String) -> Fut,
        Fut: Future<Output = Result<String>>,
    {
        let admission = self.browser_local_read_scope(principal, chat)?;
        uuid::Uuid::parse_str(chat).map_err(|_| Error::Invalid("A full chat ID is required."))?;
        let local_scope = self.local_cached_scope()?;
        if !(1..=100).contains(&options.limit)
            || !(1..=5).contains(&options.max_pages)
            || usize::from(options.before.is_some())
                + usize::from(options.after.is_some())
                + usize::from(options.anchor_message_id.is_some())
                > 1
        {
            return Err(Error::Invalid("Invalid saved chat local selector."));
        }
        let direction = if options.before.is_some() {
            MessageWindowDirection::Before
        } else if options.after.is_some() {
            MessageWindowDirection::After
        } else if options.anchor_message_id.is_some() {
            MessageWindowDirection::Around
        } else {
            MessageWindowDirection::Latest
        };
        let selector = MessageWindowOptions {
            direction,
            limit: options
                .limit
                .min(super::super::message_window::MAX_MESSAGES),
            cursor: options.before.clone().or(options.after.clone()),
            anchor_message_id: options.anchor_message_id.clone(),
            respect_compression_boundary: options.respect_compression_boundary,
        };
        wire::validate_options(&selector, chat, &local_scope)?;
        let operation_id = uuid::Uuid::new_v4().to_string();
        let (mut input,database_version)=self.local_cursor_metadata(principal,chat,&admission,&operation_id,&mut io).await?;
        let timestamp = wire::compression_timestamp(&input.compression_checkpoints, chat)?;
        let compression = if options.respect_compression_boundary {
            timestamp
        } else {
            None
        };
        if direction == MessageWindowDirection::Around {
            return self
                .local_cursor_around(
                    principal,
                    chat,
                    &admission,
                    &operation_id,
                    database_version,
                    input.into_inner(),
                    options,
                    &selector,
                    compression,
                    &mut io,
                )
                .await;
        }
        let mut lower = compression.map(|created_at| Bound {
            created_at,
            message_id: None,
            open: true,
        });
        let mut upper = None;
        if let Some(cursor) = &selector.cursor {
            let bound = Bound {
                created_at: cursor.created_at,
                message_id: Some(cursor.message_id.clone()),
                open: true,
            };
            if direction == MessageWindowDirection::Before {
                upper = Some(bound);
            } else if compression.is_none_or(|time| cursor.created_at > time) {
                lower = Some(bound);
            }
        }
        if lower
            .as_ref()
            .zip(upper.as_ref())
            .is_some_and(|(low, high)| {
                low.message_id.is_none() && low.created_at >= high.created_at
            })
        {
            input.boundary = Some(LocalCachedBoundary {
                has_more_before: Some(false),
                has_more_after: None,
                compression_boundary_timestamp: None,
            });
            return self
                .local_cursor_output(principal, chat, &admission, input.into_inner(), options)
                .await;
        }
        let metadata_bytes =
            crate::client::monitor::cached_view::bounded_bytes(&*input, MAX_PACKET_BYTES)
                .ok_or(Error::Protocol)?;
        let available = MAX_PACKET_BYTES
            .checked_sub(metadata_bytes)
            .and_then(|v| v.checked_sub(RECEIPT_RESERVE_BYTES))
            .filter(|v| *v >= 1024)
            .ok_or(Error::Protocol)?;
        let descending = direction != MessageWindowDirection::After;
        let rows_plan = Plan {
            version: 1,
            kind: "messages",
            operation_id: &operation_id,
            owner: principal,
            chat_id: chat,
            max_packet_bytes: available,
            max_checkpoint_rows: 0,
            max_payload_rows: selector.limit,
            lower,
            upper,
            direction: if descending { "prev" } else { "next" },
            anchor_message_id: None,
        };
        let (rows, exhausted) = self
            .local_cursor_rows(
                principal,
                chat,
                &admission,
                &rows_plan,
                database_version,
                &mut io,
            )
            .await?;
        admission.check_chat(self, chat)?;
        self.browser_local_read_scope(principal, chat)?;
        input.messages = rows.into_inner();
        input.boundary = Some(LocalCachedBoundary {
            has_more_before: if descending { Some(!exhausted) } else { None },
            has_more_after: if !descending {
                Some(!exhausted)
            } else if direction == MessageWindowDirection::Latest {
                Some(false)
            } else {
                None
            },
            compression_boundary_timestamp: None,
        });
        self.local_cursor_output(principal, chat, &admission, input.into_inner(), options)
            .await
    }
}
#[cfg(test)]
#[path = "browser_local_cursor_tests.rs"]
mod tests;
