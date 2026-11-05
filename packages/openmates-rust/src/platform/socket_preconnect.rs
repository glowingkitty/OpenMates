//! One pre-established TCP/TLS connection for the next WebSocket to the same
//! origin. It carries no request, credential or token: the WebSocket upgrade
//! (with the then-current credentials) is written only when `connect` takes
//! it. A connection that fails, is for another origin, or is never taken is
//! dropped and the ordinary connect path runs.
use std::sync::{Arc, Mutex, OnceLock};
use tokio::net::TcpStream;
use tokio_tungstenite::MaybeTlsStream;

type Origin = (String, u16, bool);
pub(super) struct Pending {
    origin: Origin,
    task: Option<tokio::task::JoinHandle<std::io::Result<MaybeTlsStream<TcpStream>>>>,
}
impl Drop for Pending {
    fn drop(&mut self) {
        if let Some(task) = &self.task {
            task.abort();
        }
    }
}
static SLOT: Mutex<Option<Pending>> = Mutex::new(None);

fn tls_config() -> Arc<rustls::ClientConfig> {
    static CONFIG: OnceLock<Arc<rustls::ClientConfig>> = OnceLock::new();
    CONFIG
        .get_or_init(|| {
            // Identical roots/defaults to tokio-tungstenite's rustls-tls-webpki-roots.
            let mut roots = rustls::RootCertStore::empty();
            roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
            Arc::new(rustls::ClientConfig::builder().with_root_certificates(roots).with_no_client_auth())
        })
        .clone()
}

fn origin(scheme: Option<&str>, host: Option<&str>, port: Option<u16>) -> Option<Origin> {
    let tls = match scheme? {
        "wss" => true,
        "ws" => false,
        _ => return None,
    };
    let host = host?.trim_start_matches('[').trim_end_matches(']').to_ascii_lowercase();
    Some((host, port.unwrap_or(if tls { 443 } else { 80 }), tls))
}

async fn establish(origin: Origin) -> std::io::Result<MaybeTlsStream<TcpStream>> {
    let (host, port, tls) = origin;
    let tcp = TcpStream::connect((host.as_str(), port)).await?;
    if !tls {
        return Ok(MaybeTlsStream::Plain(tcp));
    }
    let name = rustls::pki_types::ServerName::try_from(host)
        .map_err(|_| std::io::Error::new(std::io::ErrorKind::InvalidInput, "invalid server name"))?;
    let stream = tokio_rustls::TlsConnector::from(tls_config()).connect(name, tcp).await?;
    Ok(MaybeTlsStream::Rustls(stream))
}

/// Start connecting to `url`'s WebSocket origin (ws/wss) in the background,
/// replacing any earlier pre-established connection.
pub(crate) fn preconnect(url: &url::Url) {
    let Some(origin) = origin(Some(url.scheme()), url.host_str(), url.port()) else { return };
    let Ok(runtime) = tokio::runtime::Handle::try_current() else { return };
    let task = runtime.spawn(establish(origin.clone()));
    if let Ok(mut slot) = SLOT.lock() {
        *slot = Some(Pending { origin, task: Some(task) });
    }
}

/// The pre-established connection when it is for exactly this origin.
/// The pending connection for this request's origin, if any (taken once).
pub(super) fn take(uri: &tungstenite::http::Uri) -> Option<Pending> {
    let pending = SLOT.lock().ok()?.take()?;
    (Some(&pending.origin) == origin(uri.scheme_str(), uri.host(), uri.port_u16()).as_ref()).then_some(pending)
}
impl Pending {
    /// Upgrade over the pre-established connection. None: it failed or was
    /// dead before any server answer, so the caller connects afresh.
    pub(super) async fn upgrade(
        mut self,
        request: tungstenite::handshake::client::Request,
        config: Option<tungstenite::protocol::WebSocketConfig>,
    ) -> Option<Result<super::Stream, tokio_tungstenite::tungstenite::Error>> {
        let stream = self.task.take()?.await.ok()?.ok()?;
        match tokio_tungstenite::client_async_with_config(request, stream, config).await {
            Ok((stream, _)) => Some(Ok(stream)),
            Err(error) if transport_failure(&error) => None,
            // Any server answer (HTTP status, protocol) stays final.
            Err(error) => Some(Err(error)),
        }
    }
}

/// The upgrade failed before any server answer: the pre-established
/// connection was closed or broken, so a fresh connection may be tried.
fn transport_failure(error: &tokio_tungstenite::tungstenite::Error) -> bool {
    matches!(
        error,
        tokio_tungstenite::tungstenite::Error::Io(_)
            | tokio_tungstenite::tungstenite::Error::ConnectionClosed
            | tokio_tungstenite::tungstenite::Error::AlreadyClosed
            | tokio_tungstenite::tungstenite::Error::Protocol(
                tokio_tungstenite::tungstenite::error::ProtocolError::HandshakeIncomplete
            )
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn origin_matches_scheme_host_and_default_port_only() {
        assert_eq!(origin(Some("wss"), Some("API.example"), None), Some(("api.example".into(), 443, true)));
        assert_eq!(origin(Some("ws"), Some("10.0.0.1"), Some(8000)), Some(("10.0.0.1".into(), 8000, false)));
        assert_eq!(origin(Some("https"), Some("api.example"), None), None);
        assert_ne!(origin(Some("wss"), Some("api.example"), None), origin(Some("ws"), Some("api.example"), Some(443)));
    }

    #[test]
    fn only_a_dead_transport_is_retried() {
        use tokio_tungstenite::tungstenite::Error;
        assert!(transport_failure(&Error::ConnectionClosed));
        assert!(transport_failure(&Error::Protocol(
            tokio_tungstenite::tungstenite::error::ProtocolError::HandshakeIncomplete
        )));
        assert!(transport_failure(&Error::Io(std::io::ErrorKind::ConnectionReset.into())));
        assert!(!transport_failure(&Error::Url(tokio_tungstenite::tungstenite::error::UrlError::NoHostName)));
    }

    #[tokio::test]
    async fn closed_preconnection_falls_back_to_a_fresh_upgrade() {
        use tokio_tungstenite::tungstenite::client::IntoClientRequest;
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = url::Url::parse(&format!("ws://{}/v1/ws", listener.local_addr().unwrap())).unwrap();
        let server = tokio::spawn(async move {
            // The pre-established connection is closed by the peer; the retry upgrades.
            drop(listener.accept().await.unwrap());
            let (stream, _) = listener.accept().await.unwrap();
            tokio_tungstenite::accept_async(stream).await.is_ok()
        });
        preconnect(&url);
        let request = url.as_str().into_client_request().unwrap();
        assert!(super::super::connect(request, None, false).await.is_ok());
        assert!(server.await.unwrap());
    }
}
