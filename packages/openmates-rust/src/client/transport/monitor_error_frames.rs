//! Receive side of the live monitor socket that hands a generic `error` frame
//! back to the monitor instead of failing the receive. Server error frames
//! carry no request type or generic request id (`backend/core/api/app/routes/
//! websockets.py`), so only the monitor, which knows what it sent, can tell a
//! reply to a forwarded shell frame from one to its own request
//! (`client/monitor_error_frames.rs`). Every other frame is admitted exactly
//! as by `receive_monitor`.
use super::*;

/// One frame of the live monitor socket.
pub(in crate::client) enum MonitorFrame {
    /// A frame `receive_monitor` returns as data: its type and payload.
    Frame(String, Value),
    /// A generic `error` frame that `receive_monitor` refuses as a protocol
    /// violation; its payload, for the monitor to attribute.
    Error(Value),
}

/// [`receive_monitor`], except that a generic `error` frame is returned as
/// [`MonitorFrame::Error`] instead of `Err(Protocol)`.
///
/// # Errors
/// As `receive_monitor`: `Expired` on `force_logout`, `Offline` on a closed
/// or silent socket, `Protocol` for a malformed frame, `Unavailable` for a
/// turn preflight rejection.
pub(in crate::client) async fn receive_monitor_frame(ws: &mut Socket) -> Result<MonitorFrame> {
    let _original_receive = ws.own_receive()?;
    if let Some((kind, payload)) = ws.pop_pending()? {
        return Ok(MonitorFrame::Frame(kind, payload));
    }
    let (kind, payload) = receive_raw_policy(ws, false, true, ErrorAllowance::Monitor).await?;
    if kind == "error" && rejects_error_frame(&payload, false, ErrorAllowance::None) {
        return Ok(MonitorFrame::Error(payload));
    }
    Ok(MonitorFrame::Frame(kind, payload))
}
