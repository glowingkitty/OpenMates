//! Volatile selected-chat correlation for the protected Linux terminal benchmark.
//! Only a private abstract datagram socket receives keyed binary tags.
use base64::{Engine, engine::general_purpose::STANDARD};
use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::os::linux::net::SocketAddrExt;
use std::os::unix::net::{SocketAddr, UnixDatagram};
use zeroize::Zeroizing;

pub(super) struct BenchmarkIdentity {
    key: Zeroizing<Vec<u8>>,
    socket: UnixDatagram,
    frame: u64,
}

impl BenchmarkIdentity {
    pub(super) fn from_private_environment() -> Option<Self> {
        if std::env::var("OPENMATES_TEST_STARTUP_PHASE_DIAGNOSTIC")
            .ok()
            .as_deref()
            != Some("1")
        {
            return None;
        }
        let name = std::env::var("OPENMATES_TEST_TUI_IDENTITY_SOCKET").ok()?;
        let suffix = name.strip_prefix("openmates-private-tui-")?;
        if suffix.len() != 32 || !suffix.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return None;
        }
        let encoded = Zeroizing::new(std::env::var("OPENMATES_TEST_TUI_IDENTITY_KEY").ok()?);
        let key = Zeroizing::new(STANDARD.decode(encoded.as_bytes()).ok()?);
        if key.len() != 32 {
            return None;
        }
        let address = SocketAddr::from_abstract_name(name.as_bytes()).ok()?;
        let socket = UnixDatagram::unbound().ok()?;
        socket.connect_addr(&address).ok()?;
        socket.set_nonblocking(true).ok()?;
        Some(Self {
            key,
            socket,
            frame: 0,
        })
    }

    fn send(&self, ordinal: u64, chat_id: &str) {
        let Ok(mut mac) = Hmac::<Sha256>::new_from_slice(self.key.as_slice()) else {
            return;
        };
        mac.update(b"openmates private terminal selection\0");
        mac.update(chat_id.as_bytes());
        let mut packet = [0; 40];
        packet[..8].copy_from_slice(&ordinal.to_be_bytes());
        packet[8..].copy_from_slice(&mac.finalize().into_bytes());
        let _ = self.socket.send(&packet);
    }

    /// An accepted explicit selection still requires the separate durable ACK.
    pub(super) fn selected(&self, chat_id: &str) {
        self.send(0, chat_id);
    }

    /// The ordinal tracks complete synchronized PTY paints, even without a chat.
    pub(super) fn painted(&mut self, chat_id: Option<&str>) {
        self.frame = self.frame.saturating_add(1);
        if let Some(chat_id) = chat_id {
            self.send(self.frame, chat_id);
        }
    }
}
