//! Live collaboration core: sealed packets, the per-item replica engine and one schema
//! adapter per item kind (document, sheet, deck, code). Shared client core (plan
//! `live-collaboration-crdt`, build contract section 1). Pure: no I/O, no clock, no
//! transport; bindings and shells feed it bytes and persist its outbox. The server only
//! ever sees the sealed packets this module produces.

pub mod assistant;
pub mod assistant_session;
mod assistant_sheet;
pub mod client_io;
pub mod code;
pub mod doc;
mod doc_html;
pub mod driver;
#[cfg(test)]
mod driver_tests;
pub mod engine;
pub mod offline;
pub mod ops_json;
pub mod packet;
pub mod presence;
mod restore;
pub mod session;
mod session_frames;
#[cfg(test)]
mod session_tests;
pub mod session_types;
pub mod session_wire;
pub mod sheet;
mod sheet_formatting;
#[cfg(test)]
mod sheet_formatting_tests;
mod sheet_formula;
pub mod stored_form;
pub mod timeline;

pub use engine::{LiveItem, LocalChange, LocalOp, RemoteUpdate, SealedUpdate, ViewChange};
pub use packet::{PacketType, open_packet, seal_packet};
pub use sheet::SheetOp;
pub use sheet_formatting::{SheetFormatCell, SheetFormatChange};

use std::fmt;
use yrs::block::ClientID;
use yrs::{Doc, OffsetKind, Options};

/// Kind of a live item; the wire string is part of every packet's AAD.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum LiveItemKind {
    /// Rich-text document (`Y.XmlFragment` `default`, TipTap shape).
    Doc,
    /// Sheet (stable row/column ids plus a cell map).
    Sheet,
    /// Slide deck (the `shared_items` deck model).
    Deck,
    /// Code file (`Y.Text` `content`).
    Code,
}

impl LiveItemKind {
    /// Wire string: `doc`, `sheet`, `deck` or `code`.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Doc => "doc",
            Self::Sheet => "sheet",
            Self::Deck => "deck",
            Self::Code => "code",
        }
    }

    /// Parses a wire string.
    ///
    /// # Errors
    /// [`LiveError::UnknownKind`] for anything else.
    pub fn parse(value: &str) -> Result<Self, LiveError> {
        match value {
            "doc" => Ok(Self::Doc),
            "sheet" => Ok(Self::Sheet),
            "deck" => Ok(Self::Deck),
            "code" => Ok(Self::Code),
            other => Err(LiveError::UnknownKind(other.to_string())),
        }
    }
}

/// Why a live operation failed. Nothing is applied when an operation returns an error.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LiveError {
    /// A kind string that is not `doc`, `sheet`, `deck` or `code`.
    UnknownKind(String),
    /// Packet shorter than the fixed header plus the AEAD tag.
    PacketTooShort,
    /// Packet version byte this core does not know.
    UnsupportedVersion(u8),
    /// Packet type byte that is not 1, 2 or 3.
    UnknownPacketType(u8),
    /// The packet is a different type than the caller expected.
    WrongPacketType {
        /// Type the caller asked for.
        expected: u8,
        /// Type in the header.
        found: u8,
    },
    /// The packet was sealed under another key epoch; fetch the new key wrapper.
    EpochMismatch {
        /// Epoch the item holds.
        expected: u32,
        /// Epoch in the packet header.
        found: u32,
    },
    /// Wrong key, other item/kind/epoch/type (AAD mismatch) or a modified packet.
    Authentication,
    /// The system random source failed while sealing.
    Randomness,
    /// The operation does not apply to this item kind.
    WrongKind {
        /// Kind of the item.
        kind: LiveItemKind,
    },
    /// Undecodable or inapplicable Yjs update bytes.
    InvalidUpdate(String),
    /// Text form that the kind's parser rejects.
    InvalidText(&'static str),
    /// No row with this id.
    RowNotFound(String),
    /// No column with this id.
    ColumnNotFound(String),
    /// A cell value the markdown table cannot hold (pipe or line break).
    InvalidCell(&'static str),
    /// A deck operation failed.
    Deck(String),
    /// The replica has no content yet (nothing was synced or created).
    Empty,
    /// A platform primitive failed; carries its stable code (key unavailable, read failed, ...).
    Io(&'static str),
}

impl fmt::Display for LiveError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.code())?;
        match self {
            Self::UnknownKind(v) | Self::RowNotFound(v) | Self::ColumnNotFound(v) => {
                write!(f, ": {v}")
            }
            Self::InvalidUpdate(v) | Self::Deck(v) => write!(f, ": {v}"),
            Self::InvalidText(v) | Self::InvalidCell(v) => write!(f, ": {v}"),
            _ => Ok(()),
        }
    }
}

impl std::error::Error for LiveError {}

impl LiveError {
    /// Stable code that crosses bindings unchanged.
    pub fn code(&self) -> &'static str {
        match self {
            Self::UnknownKind(_) => "live_unknown_kind",
            Self::PacketTooShort => "live_packet_too_short",
            Self::UnsupportedVersion(_) => "live_unsupported_version",
            Self::UnknownPacketType(_) => "live_unknown_packet_type",
            Self::WrongPacketType { .. } => "live_wrong_packet_type",
            Self::EpochMismatch { .. } => "live_key_epoch_stale",
            Self::Authentication => "live_authentication_failed",
            Self::Randomness => "live_randomness_failed",
            Self::WrongKind { .. } => "live_wrong_kind",
            Self::InvalidUpdate(_) => "live_invalid_update",
            Self::InvalidText(_) => "live_invalid_text",
            Self::RowNotFound(_) => "live_row_not_found",
            Self::ColumnNotFound(_) => "live_column_not_found",
            Self::InvalidCell(_) => "live_invalid_cell",
            Self::Deck(_) => "live_deck_error",
            Self::Empty => "live_empty",
            Self::Io(code) => code,
        }
    }
}

/// A Yjs doc whose text offsets count UTF-16 code units, like Yjs (JS).
pub(crate) fn new_doc(client_id: u32) -> Doc {
    let mut options = Options::with_client_id(ClientID::new(u64::from(client_id)));
    options.offset_kind = OffsetKind::Utf16;
    Doc::with_options(options)
}

/// A fresh random stable id with a one-letter prefix (`r` rows, `c` columns).
pub(crate) fn new_id(prefix: char) -> String {
    format!("{prefix}{:016x}", rand::random::<u64>())
}

#[cfg(test)]
mod assistant_session_tests;
#[cfg(test)]
mod assistant_tests;
#[cfg(test)]
mod client_io_tests;
#[cfg(test)]
mod code_tests;
#[cfg(test)]
mod convergence_tests;
#[cfg(test)]
mod doc_tests;
#[cfg(test)]
mod engine_tests;
#[cfg(test)]
mod offline_tests;
#[cfg(test)]
mod packet_tests;
#[cfg(test)]
mod presence_tests;
#[cfg(test)]
mod sheet_tests;
#[cfg(test)]
mod support;
#[cfg(test)]
mod timeline_tests;
