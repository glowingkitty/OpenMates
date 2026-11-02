//! Physical WebSocket adapters. All envelope validation and protocol state stay
//! in client::transport and the existing send/sync/monitor/recovery reducers.
#[cfg(not(target_arch = "wasm32"))]
pub(crate) type Stream =
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>;
#[cfg(target_arch = "wasm32")]
#[path = "browser_socket.rs"]
mod browser;
#[cfg(target_arch = "wasm32")]
pub(crate) use browser::Stream;

pub(crate) async fn connect(
    request: tungstenite::handshake::client::Request,
    config: Option<tungstenite::protocol::WebSocketConfig>,
    disable_nagle: bool,
) -> Result<(Stream, ()), tungstenite::Error> {
    #[cfg(not(target_arch = "wasm32"))]
    {
        tokio_tungstenite::connect_async_with_config(request, config, disable_nagle)
            .await
            .map(|(stream, _)| (stream, ()))
    }
    #[cfg(target_arch = "wasm32")]
    {
        let _ = disable_nagle;
        browser::connect(request, config)
            .await
            .map(|stream| (stream, ()))
    }
}
