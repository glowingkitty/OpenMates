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

#[cfg(not(target_arch = "wasm32"))]
#[path = "socket_preconnect.rs"]
mod preconnect;
#[cfg(not(target_arch = "wasm32"))]
pub(crate) use preconnect::preconnect;
#[cfg(target_arch = "wasm32")]
pub(crate) fn preconnect(_url: &url::Url) {}

pub(crate) async fn connect(
    request: tungstenite::handshake::client::Request,
    config: Option<tungstenite::protocol::WebSocketConfig>,
    disable_nagle: bool,
) -> Result<(Stream, ()), tungstenite::Error> {
    #[cfg(not(target_arch = "wasm32"))]
    {
        // Boxed and only entered with a pending connection, so the ordinary
        // connect future (inside deep recovery futures) does not grow.
        if let Some(pending) = (!disable_nagle).then(|| preconnect::take(request.uri())).flatten() {
            if let Some(result) = Box::pin(pending.upgrade(request.clone(), config)).await {
                return result.map(|stream| (stream, ()));
            }
        }
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
