//! Presence: who is where in an item. Sealed with packet type 3, never stored; an entry
//! expires 30 s after its last heartbeat. Time is injected (milliseconds).

use super::packet::{PacketType, open_packet, seal_packet};
use super::{LiveError, LiveItemKind};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Heartbeat expiry.
pub const PRESENCE_TTL_MS: u64 = 30_000;

/// Cursor of one participant, by item kind.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Cursor {
    /// Document: Yjs relative positions (JSON strings).
    Doc {
        /// Selection anchor.
        anchor: String,
        /// Selection head.
        head: String,
    },
    /// Code: Yjs relative positions (JSON strings).
    Code {
        /// Selection anchor.
        anchor: String,
        /// Selection head.
        head: String,
    },
    /// Sheet: the selected cell by stable ids.
    Sheet {
        /// Row id.
        row_id: String,
        /// Column id.
        col_id: String,
    },
    /// Deck: the slide and optionally the selected element.
    Deck {
        /// Slide id.
        slide_id: String,
        /// Element id.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        element_id: Option<String>,
    },
}

/// The "mate is editing here" lock.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MatePresence {
    /// The mate's display name.
    pub mate_name: String,
    /// What the mate is editing (a section, range or cell range).
    pub editing_scope: String,
}

/// One participant's presence payload.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Presence {
    /// User id.
    pub user_id: String,
    /// Name shown next to the cursor.
    pub display_name: String,
    /// Cursor colour `#rrggbb`, see [`color_for`].
    pub color: String,
    /// Cursor, if the user has one in the item.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cursor: Option<Cursor>,
    /// Set while a mate edits for this user.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mate: Option<MatePresence>,
}

/// Deterministic colour for a user id (same on every client).
pub fn color_for(user_id: &str) -> String {
    let mut hash: u32 = 0x811c_9dc5;
    for byte in user_id.bytes() {
        hash = (hash ^ u32::from(byte)).wrapping_mul(0x0100_0193);
    }
    let hue = f64::from(hash % 360);
    let (s, l) = (0.65_f64, 0.5_f64);
    let c = (1.0 - (2.0 * l - 1.0).abs()) * s;
    let x = c * (1.0 - ((hue / 60.0) % 2.0 - 1.0).abs());
    let m = l - c / 2.0;
    let (r, g, b) = match (hue / 60.0) as u32 {
        0 => (c, x, 0.0),
        1 => (x, c, 0.0),
        2 => (0.0, c, x),
        3 => (0.0, x, c),
        4 => (x, 0.0, c),
        _ => (c, 0.0, x),
    };
    let byte = |v: f64| ((v + m) * 255.0).round() as u8;
    format!("#{:02x}{:02x}{:02x}", byte(r), byte(g), byte(b))
}

/// Seals a presence payload as a type-3 packet.
///
/// # Errors
/// Sealing errors.
pub fn seal_presence(
    key: &[u8; 32],
    item_id: &str,
    kind: LiveItemKind,
    epoch: u32,
    presence: &Presence,
) -> Result<Vec<u8>, LiveError> {
    let json = serde_json::to_vec(presence).map_err(|e| LiveError::InvalidUpdate(e.to_string()))?;
    seal_packet(key, item_id, kind, epoch, PacketType::Presence, &json)
}

/// Opens a type-3 packet.
///
/// # Errors
/// Packet errors, [`LiveError::InvalidUpdate`] for a payload that is not presence JSON.
pub fn open_presence(
    key: &[u8; 32],
    item_id: &str,
    kind: LiveItemKind,
    epoch: u32,
    packet: &[u8],
) -> Result<Presence, LiveError> {
    let json = open_packet(key, item_id, kind, epoch, PacketType::Presence, packet)?;
    serde_json::from_slice(&json).map_err(|e| LiveError::InvalidUpdate(e.to_string()))
}

/// Who is present right now; entries expire without heartbeats.
#[derive(Debug, Default)]
pub struct PresenceTable {
    entries: HashMap<String, (Presence, u64)>,
}

impl PresenceTable {
    /// Empty table.
    pub fn new() -> Self {
        Self::default()
    }

    /// Records a heartbeat from `presence.user_id` at `now_ms`.
    pub fn heartbeat(&mut self, presence: Presence, now_ms: u64) {
        self.entries
            .insert(presence.user_id.clone(), (presence, now_ms));
    }

    /// Removes a participant (they left).
    pub fn remove(&mut self, user_id: &str) {
        self.entries.remove(user_id);
    }

    /// Drops expired entries and returns the live ones sorted by user id.
    pub fn active(&mut self, now_ms: u64) -> Vec<&Presence> {
        self.entries
            .retain(|_, (_, seen)| now_ms.saturating_sub(*seen) < PRESENCE_TTL_MS);
        let mut live: Vec<&Presence> = self.entries.values().map(|(p, _)| p).collect();
        live.sort_by(|a, b| a.user_id.cmp(&b.user_id));
        live
    }
}
