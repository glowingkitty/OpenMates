//! Server frames of [`LiveSession`]: `live_item_state`, `_update_ack`, `_update`,
//! `_snapshot_available`, `_presence` and `_refused`.

use super::LiveError;
use super::engine::{LiveItem, RemoteUpdate};
use super::offline::{EditAccess, OfflineMerge, merge_offline};
use super::packet::{PacketType, open_packet};
use super::session::{
    LiveSession, SNAPSHOT_BYTES_THRESHOLD, SNAPSHOT_UPDATE_THRESHOLD, Slot, b64, emit_change,
    emit_full, flush, persist, presence_event, status_event, subscribe, touch,
};
use super::session_types::{Action, Event, Status};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};

fn decode(value: &Value) -> Result<Vec<u8>, LiveError> {
    let text = value.as_str().ok_or(LiveError::PacketTooShort)?;
    STANDARD
        .decode(text)
        .map_err(|e| LiveError::InvalidUpdate(e.to_string()))
}

fn remote(value: &Value) -> Result<RemoteUpdate, LiveError> {
    Ok(RemoteUpdate {
        seq: value["seq"].as_u64().unwrap_or(0),
        sealed: decode(&value["payload"])?,
    })
}

fn stale(item_id: &str) -> Action {
    Action::NeedKey {
        item_id: item_id.to_string(),
        stale: true,
    }
}

impl LiveSession {
    /// Handles one server frame. Frames for items that are not open are ignored.
    ///
    /// # Errors
    /// Malformed payloads and packet errors other than a stale key epoch (which becomes
    /// [`Action::NeedKey`]).
    pub fn on_frame(
        &mut self,
        message_type: &str,
        payload: &Value,
        now_ms: u64,
    ) -> Result<Vec<Action>, LiveError> {
        if matches!(
            message_type,
            "embed_assistant_change" | "embed_assistant_editing"
        ) {
            return self.on_assistant_frame(message_type, payload, now_ms);
        }
        let Some(item_id) = payload["item_id"].as_str().map(str::to_string) else {
            return Ok(Vec::new());
        };
        let connected = self.connected;
        // A frame that arrives while the host reports the connection down belongs to a
        // subscription the session already dropped; the resubscribe on reconnect replays
        // everything after the local head, so ignoring it loses nothing.
        if !connected {
            return Ok(Vec::new());
        }
        let Some(slot) = self.slots.get_mut(&item_id) else {
            return Ok(Vec::new());
        };
        let mut out = Vec::new();
        let reason = payload["reason"].as_str();
        // The relay deliberately replies not_found to a fresh subscription by
        // a removed member. A replica we already hold can still be recovered locally.
        if message_type == "live_item_refused"
            && (reason == Some("access_revoked")
                || (reason == Some("not_found") && slot.item.is_some()))
        {
            offer_private_copy(&item_id, slot, &mut out);
            out.push(Action::Emit(Event::Status {
                item_id: item_id.clone(),
                status: Status::AccessRevoked,
            }));
            self.forget(&item_id);
            return Ok(out);
        }
        let result = match message_type {
            "live_item_state" => on_state(
                &item_id,
                slot,
                payload,
                connected,
                now_ms,
                &self.user_id,
                &mut out,
            ),
            "live_item_update_ack" => {
                if let Some(item) = slot.item.as_mut() {
                    item.ack(
                        payload["client_msg_id"].as_str().unwrap_or_default(),
                        payload["seq"].as_u64().unwrap_or(0),
                    );
                    slot.sent
                        .remove(payload["client_msg_id"].as_str().unwrap_or_default());
                    out.push(persist(&item_id, slot));
                    maybe_snapshot(&item_id, slot, &mut out)?;
                }
                status_event(&item_id, slot, connected, &mut out);
                Ok(())
            }
            "live_item_update" => on_update(&item_id, slot, payload, &mut out),
            "live_item_snapshot_available" => {
                if let (Some(covers), Some(epoch)) = (
                    payload["covers_seq"].as_u64(),
                    payload["epoch"]
                        .as_u64()
                        .and_then(|epoch| u32::try_from(epoch).ok()),
                ) {
                    slot.verify_snapshot = Some((covers, epoch));
                    out.push(subscribe(&item_id, slot, None));
                }
                Ok(())
            }
            "live_item_presence" => {
                on_presence(&item_id, slot, payload, now_ms, &mut out);
                Ok(())
            }
            "live_item_refused" => {
                on_refused(&item_id, slot, payload, connected, &mut out);
                Ok(())
            }
            _ => Ok(()),
        };
        match result {
            Ok(()) => {}
            Err(LiveError::EpochMismatch { expected, found }) if found > expected => {
                out.push(stale(&item_id));
            }
            Err(error) => return Err(error),
        }
        if message_type == "live_item_update_ack" {
            out.extend(self.assistant_acked(&item_id, payload, now_ms)?);
        }
        Ok(out)
    }
}

fn on_state(
    item_id: &str,
    slot: &mut Slot,
    payload: &Value,
    connected: bool,
    now_ms: u64,
    user: &Option<String>,
    out: &mut Vec<Action>,
) -> Result<(), LiveError> {
    if let Some(epoch) = payload["epoch"].as_u64()
        && epoch > u64::from(slot.epoch)
    {
        out.push(stale(item_id));
        return Ok(());
    }
    let key: [u8; 32] = **slot.key.as_ref().ok_or(LiveError::Empty)?;
    let can_edit = payload["role"] == "edit";
    if !can_edit && slot.can_edit == Some(true) {
        offer_private_copy(item_id, slot, out);
    }
    slot.can_edit = Some(can_edit);
    slot.subscribed = true;
    let snapshot = match payload.get("snapshot").filter(|s| s.is_object()) {
        Some(s) => Some(remote(s)?),
        None => None,
    };
    let updates = payload["updates"]
        .as_array()
        .map(|list| list.iter().map(remote).collect::<Result<Vec<_>, _>>())
        .transpose()?
        .unwrap_or_default();
    if let (Some((covers, epoch)), Some(snapshot)) = (slot.verify_snapshot, snapshot.as_ref())
        && snapshot.seq == covers
        && super::packet::packet_epoch(&snapshot.sealed)? == epoch
    {
        // Load the other client's snapshot to prove it opens, then confirm it.
        LiveItem::open_with_history(
            slot.kind,
            item_id,
            &key,
            slot.epoch,
            &slot.previous_keys,
            Some(snapshot),
            &[],
        )?;
        out.push(Action::Send {
            message_type: "live_item_snapshot_confirm",
            payload: json!({"item_id": item_id, "covers_seq": covers, "epoch": epoch}),
        });
        slot.verify_snapshot = None;
    }
    if let Some(item) = slot.item.as_mut() {
        let before = item.state_vector();
        let mut changed = false;
        if let Some(snapshot) = &snapshot
            && snapshot.seq > item.head_seq()
        {
            item.apply_snapshot(snapshot)?;
            changed = true;
        }
        // Only the positions not applied yet: a replay after a missed update fills the hole.
        let missing: Vec<_> = updates.iter().filter(|u| !item.has_seq(u.seq)).collect();
        for update in missing {
            changed |= item.apply_remote(update.seq, &update.sealed)?.changed;
            slot.updates_since_snapshot += 1;
            slot.bytes_since_snapshot += update.sealed.len();
        }
        if changed {
            emit_change(item_id, slot, &before, out);
        }
    } else {
        let empty = snapshot.is_none() && updates.is_empty();
        if empty && slot.stored_outbox.is_empty() {
            out.push(Action::NeedContent {
                item_id: item_id.to_string(),
            });
            status_event(item_id, slot, connected, out);
            return Ok(());
        }
        let mut item = LiveItem::open_with_history(
            slot.kind,
            item_id,
            &key,
            slot.epoch,
            &slot.previous_keys,
            snapshot.as_ref(),
            &updates,
        )?;
        if snapshot.as_ref().is_some_and(|packet| {
            super::packet::packet_epoch(&packet.sealed).is_ok_and(|epoch| epoch < slot.epoch)
        }) {
            slot.updates_since_snapshot = SNAPSHOT_UPDATE_THRESHOLD;
        }
        let recovered_edits = !slot.stored_outbox.is_empty();
        item.restore_outbox(std::mem::take(&mut slot.stored_outbox))?;
        slot.updates_since_snapshot = slot.updates_since_snapshot.max(updates.len());
        slot.bytes_since_snapshot = updates.iter().map(|u| u.sealed.len()).sum();
        slot.item = Some(item);
        if recovered_edits {
            if can_edit {
                // Checkpoint recovered content even if the user makes no further edits.
                // Persist first in case restore resealed packets for a new epoch.
                touch(slot, now_ms, user);
                out.push(persist(item_id, slot));
            } else {
                offer_private_copy(item_id, slot, out);
            }
        }
        emit_full(item_id, slot, out);
    }
    flush(item_id, slot, connected, out);
    status_event(item_id, slot, connected, out);
    maybe_snapshot(item_id, slot, out)
}

fn on_update(
    item_id: &str,
    slot: &mut Slot,
    payload: &Value,
    out: &mut Vec<Action>,
) -> Result<(), LiveError> {
    let Some(item) = slot.item.as_mut() else {
        return Ok(());
    };
    let update = remote(payload)?;
    if item.has_seq(update.seq) {
        return Ok(());
    }
    let before = item.state_vector();
    let changed = item.apply_remote(update.seq, &update.sealed)?.changed;
    slot.updates_since_snapshot += 1;
    slot.bytes_since_snapshot += update.sealed.len();
    if changed {
        emit_change(item_id, slot, &before, out);
    }
    maybe_snapshot(item_id, slot, out)
}

/// Seals and sends a snapshot once the thresholds are reached and nothing is pending.
fn maybe_snapshot(item_id: &str, slot: &mut Slot, out: &mut Vec<Action>) -> Result<(), LiveError> {
    let due = slot.updates_since_snapshot >= SNAPSHOT_UPDATE_THRESHOLD
        || slot.bytes_since_snapshot >= SNAPSHOT_BYTES_THRESHOLD;
    let (true, true, Some(item)) = (
        due,
        slot.subscribed && slot.can_edit == Some(true),
        slot.item.as_ref(),
    ) else {
        return Ok(());
    };
    if !item.outbox().is_empty() {
        return Ok(());
    }
    let (covers_seq, sealed) = item.seal_snapshot()?;
    out.push(Action::Send {
        message_type: "live_item_snapshot",
        payload: json!({"item_id": item_id, "covers_seq": covers_seq,
            "epoch": item.epoch(), "payload": b64(&sealed)}),
    });
    slot.updates_since_snapshot = 0;
    slot.bytes_since_snapshot = 0;
    Ok(())
}

/// Presence that fails to open (other epoch, other item, tampered) is dropped: it is
/// ephemeral and never stored, so there is nothing to recover.
fn on_presence(
    item_id: &str,
    slot: &mut Slot,
    payload: &Value,
    now_ms: u64,
    out: &mut Vec<Action>,
) {
    let (Some(key), Ok(sealed)) = (slot.key.as_ref(), decode(&payload["payload"])) else {
        return;
    };
    let Ok(plain) = open_packet(
        key,
        item_id,
        slot.kind,
        slot.epoch,
        PacketType::Presence,
        &sealed,
    ) else {
        return;
    };
    let Ok(value) = serde_json::from_slice::<Value>(&plain) else {
        return;
    };
    let connection = payload["connection"].as_str().unwrap_or("?").to_string();
    slot.presence.insert(connection, (value, now_ms));
    out.push(presence_event(item_id, slot));
}

fn offer_private_copy(item_id: &str, slot: &Slot, out: &mut Vec<Action>) {
    if let Some(item) = slot.item.as_ref()
        && let Some(latest) = item.outbox().last()
        && let Ok(OfflineMerge::AccessLost { private_copy_text }) =
            merge_offline(item, EditAccess::Lost)
    {
        out.push(Action::Emit(Event::PrivateCopy {
            item_id: item_id.to_string(),
            copy_id: latest.client_msg_id.clone(),
            kind: slot.kind,
            text: private_copy_text,
        }));
    }
}

fn on_refused(
    item_id: &str,
    slot: &mut Slot,
    payload: &Value,
    connected: bool,
    out: &mut Vec<Action>,
) {
    match payload["reason"].as_str().unwrap_or_default() {
        "read_only" => {
            if slot.can_edit == Some(true) {
                offer_private_copy(item_id, slot, out);
            }
            slot.can_edit = Some(false);
            status_event(item_id, slot, connected, out);
        }
        "key_epoch_stale" => {
            // A burst of refused packets may reach this replica after one reply
            // already refreshed the keys. Older relays omit the rejected epoch.
            if payload["rejected_epoch"]
                .as_u64()
                .is_none_or(|epoch| epoch >= u64::from(slot.epoch))
            {
                out.push(stale(item_id));
            }
        }
        // The relay limits updates and presence per connection and second. A refused update
        // is still in the outbox: forget that it was sent so the next tick sends it again.
        // A refusal without a message id was a presence.
        "rate_limited" => match payload["client_msg_id"].as_str() {
            Some(msg_id) => {
                slot.sent.remove(msg_id);
                slot.resend_due = true;
            }
            None => slot.presence_refused = true,
        },
        _ => {}
    }
}
