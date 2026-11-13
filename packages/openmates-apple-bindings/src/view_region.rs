//! Server region preference on `ViewModelCore` for the Apple shell (Settings >
//! AI "Prefer EU servers"): the device-local setting each `send` carries as the
//! turn's `model_routing_restrictions`. The core owns the wire value and when
//! it is sent (`client::server_region`, `SendOptions::server_region`); Swift
//! stores the setting in its own preferences and sets it at launch, as the web
//! keeps `server_region_preference` in its profile store.
use crate::view_core::ViewModelCore;
use openmates_sdk::client::server_region::ServerRegionPreference;
use std::sync::atomic::Ordering;

/// Where this device's AI turns preferably run.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum ServerRegionPreferenceRecord {
    /// Prefer EU-hosted servers (default).
    Eu,
    /// Each model's fastest server, worldwide.
    Global,
}

impl From<ServerRegionPreference> for ServerRegionPreferenceRecord {
    fn from(preference: ServerRegionPreference) -> Self {
        match preference {
            ServerRegionPreference::Eu => Self::Eu,
            ServerRegionPreference::Global => Self::Global,
        }
    }
}

impl From<ServerRegionPreferenceRecord> for ServerRegionPreference {
    fn from(preference: ServerRegionPreferenceRecord) -> Self {
        match preference {
            ServerRegionPreferenceRecord::Eu => Self::Eu,
            ServerRegionPreferenceRecord::Global => Self::Global,
        }
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// The server region preference applied to this core's sends (`Eu`
    /// until Swift sets it).
    pub fn server_region_preference(&self) -> ServerRegionPreferenceRecord {
        if self.shared.server_region_global.load(Ordering::SeqCst) {
            ServerRegionPreferenceRecord::Global
        } else {
            ServerRegionPreferenceRecord::Eu
        }
    }

    /// Set the server region preference of the following sends. Not
    /// persisted by the core: Swift keeps the setting and sets it again after
    /// launch. Kept across sign-ins of this core; applies from the next `send`.
    pub fn set_server_region_preference(&self, preference: ServerRegionPreferenceRecord) {
        self.shared.server_region_global.store(
            preference == ServerRegionPreferenceRecord::Global,
            Ordering::SeqCst,
        );
    }

    /// The stored preference read the way every shell reads it: `"global"`
    /// is `Global`, any other value (or none) `Eu`. For migrating a setting
    /// Swift kept as text.
    pub fn server_region_preference_from_stored(
        &self,
        value: Option<String>,
    ) -> ServerRegionPreferenceRecord {
        value
            .as_deref()
            .map_or(
                ServerRegionPreference::Eu,
                ServerRegionPreference::from_stored,
            )
            .into()
    }
}

/// The core preference of the shared flag (`view_send.rs`).
pub(crate) fn preference_of(global: bool) -> ServerRegionPreference {
    if global {
        ServerRegionPreference::Global
    } else {
        ServerRegionPreference::Eu
    }
}
