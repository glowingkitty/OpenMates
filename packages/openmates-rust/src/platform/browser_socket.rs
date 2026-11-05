//! Worker-local browser WebSocket. Callback and outbound queues are bounded;
//! overflow closes the connection rather than dropping a protocol frame.
use futures_channel::{mpsc, oneshot};
use futures_util::{Sink, Stream as FutureStream};
use std::{
    cell::{Cell, RefCell},
    future::{Future, poll_fn},
    pin::Pin,
    rc::Rc,
    task::{Context, Poll},
};
use tungstenite::{
    Error, Message,
    protocol::{CloseFrame, WebSocketConfig},
};
use wasm_bindgen::{JsCast, closure::Closure};

pub(crate) struct Stream {
    socket: web_sys::WebSocket,
    receiver: mpsc::Receiver<Result<Message, Error>>,
    queued: Rc<Cell<usize>>,
    failed: Rc<Cell<bool>>,
    close_wait: oneshot::Receiver<()>,
    close_requested: bool,
    max: usize,
    _open: Closure<dyn FnMut(web_sys::Event)>,
    _message: Closure<dyn FnMut(web_sys::MessageEvent)>,
    _error: Closure<dyn FnMut(web_sys::Event)>,
    _close: Closure<dyn FnMut(web_sys::CloseEvent)>,
}
impl Drop for Stream {
    fn drop(&mut self) {
        self.socket.set_onopen(None);
        self.socket.set_onmessage(None);
        self.socket.set_onerror(None);
        self.socket.set_onclose(None);
        let _ = self.socket.close();
    }
}
pub(super) async fn connect(
    request: tungstenite::handshake::client::Request,
    config: Option<WebSocketConfig>,
) -> Result<Stream, Error> {
    // Cookie/Origin/User-Agent are browser managed. Never translate native
    // secret headers into query parameters or a subprotocol.
    if request
        .headers()
        .get("Cookie")
        .is_some_and(|value| !value.as_bytes().is_empty())
    {
        return Err(Error::ConnectionClosed);
    }
    let max = config
        .and_then(|config| config.max_message_size)
        .unwrap_or(16 * 1024 * 1024)
        .min(16 * 1024 * 1024);
    let socket =
        web_sys::WebSocket::new(&request.uri().to_string()).map_err(|_| Error::ConnectionClosed)?;
    let (stream, ready) = own_socket(socket, max);
    ready.await.map_err(|_| Error::ConnectionClosed)??;
    Ok(stream)
}
// Own the callbacks and completion channel for this exact physical socket.
// Tests use the same assembly with a real browser WebSocket, never fake flags.
pub(super) fn own_socket(socket:web_sys::WebSocket,max:usize)->(Stream,oneshot::Receiver<Result<(),Error>>) {
    let (closed, close_wait) = oneshot::channel();
    let closed = Rc::new(RefCell::new(Some(closed)));
    let (sender, receiver) = mpsc::channel(32);
    let sender = Rc::new(RefCell::new(sender));
    let (opened, ready) = oneshot::channel();
    let opened = Rc::new(RefCell::new(Some(opened)));
    let queued = Rc::new(Cell::new(0usize));
    let failed = Rc::new(Cell::new(false));
    let open = {
        let opened = opened.clone();
        Closure::new(move |_: web_sys::Event| {
            if let Some(sender) = opened.borrow_mut().take() {
                let _ = sender.send(Ok(()));
            }
        })
    };
    let message = {
        let sender = sender.clone();
        let queued = queued.clone();
        let failed = failed.clone();
        let socket = socket.clone();
        Closure::new(move |event: web_sys::MessageEvent| {
            // Browser message storage already exists, but bound its length
            // before allocating the Rust string. UTF-8 bytes are checked again.
            let value = event.data();
            let text = value.dyn_ref::<js_sys::JsString>();
            let admitted = text.is_some_and(|text| text.length() as usize <= max);
            let text = if admitted { value.as_string() } else { None };
            let Some(text) = text.filter(|text| text.len() <= max) else {
                failed.set(true);
                let _ = socket.close();
                return;
            };
            let Some(total) = queued
                .get()
                .checked_add(text.len())
                .filter(|total| *total <= max)
            else {
                failed.set(true);
                let _ = socket.close();
                return;
            };
            if sender
                .borrow_mut()
                .try_send(Ok(Message::Text(text.into())))
                .is_err()
            {
                failed.set(true);
                let _ = socket.close();
                return;
            }
            queued.set(total);
        })
    };
    let error = {
        let opened = opened.clone();
        let failed = failed.clone();
        let sender = sender.clone();
        Closure::new(move |_: web_sys::Event| {
            failed.set(true);
            if let Some(sender) = opened.borrow_mut().take() {
                let _ = sender.send(Err(Error::ConnectionClosed));
            }
            sender.borrow_mut().close_channel();
        })
    };
    let close = {
        let opened = opened.clone();
        let sender = sender.clone();
        let socket = socket.clone();
        let closed = closed.clone();
        Closure::new(move |_: web_sys::CloseEvent| {
            // A synthetic dispatched CloseEvent cannot acknowledge an open
            // socket. The same original WebSocket must actually be CLOSED.
            if socket.ready_state() == web_sys::WebSocket::CLOSED {
                if let Some(sender) = closed.borrow_mut().take() {let _ = sender.send(());}
            }
            if let Some(sender) = opened.borrow_mut().take() {
                let _ = sender.send(Err(Error::ConnectionClosed));
            }
            sender.borrow_mut().close_channel();
        })
    };
    socket.set_onopen(Some(open.as_ref().unchecked_ref()));
    socket.set_onmessage(Some(message.as_ref().unchecked_ref()));
    socket.set_onerror(Some(error.as_ref().unchecked_ref()));
    socket.set_onclose(Some(close.as_ref().unchecked_ref()));
    // Construct before awaiting so a cancelled handshake releases all callbacks
    // and closes its physical socket, including a late browser open event.
    let stream = Stream {
        socket,
        receiver,
        queued,
        failed,
        close_wait,
        close_requested: false,
        max,
        _open: open,
        _message: message,
        _error: error,
        _close: close,
    };
    (stream, ready)
}
impl FutureStream for Stream {
    type Item = Result<Message, Error>;
    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        if self.failed.replace(false) {
            return Poll::Ready(Some(Err(Error::ConnectionClosed)));
        }
        match Pin::new(&mut self.receiver).poll_next(cx) {
            Poll::Ready(Some(Ok(message))) => {
                self.queued
                    .set(self.queued.get().saturating_sub(message.len()));
                Poll::Ready(Some(Ok(message)))
            }
            other => other,
        }
    }
}
impl Sink<Message> for Stream {
    type Error = Error;
    fn poll_ready(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Result<(), Error>> {
        if self.socket.ready_state() != web_sys::WebSocket::OPEN
            || self.failed.get()
            || self.socket.buffered_amount() as usize > self.max
        {
            return Poll::Ready(Err(Error::ConnectionClosed));
        }
        Poll::Ready(Ok(()))
    }
    fn start_send(self: Pin<&mut Self>, message: Message) -> Result<(), Error> {
        match message {
            Message::Text(text)
                if text
                    .len()
                    .checked_add(self.socket.buffered_amount() as usize)
                    .is_some_and(|size| size <= self.max) =>
            {
                self.socket
                    .send_with_str(&text)
                    .map_err(|_| Error::ConnectionClosed)
            }
            Message::Close(_) => self.socket.close().map_err(|_| Error::ConnectionClosed),
            // Browser handles control ping/pong internally; no synthetic frames.
            _ => Err(Error::ConnectionClosed),
        }
    }
    fn poll_flush(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Result<(), Error>> {
        Poll::Ready(Ok(()))
    }
    fn poll_close(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Result<(), Error>> {
        let original = self.get_mut();
        // This is the browser's state of the original physical WebSocket,
        // independent of queue closure, error callbacks and caller labels.
        if original.socket.ready_state() == web_sys::WebSocket::CLOSED {
            return Poll::Ready(Ok(()));
        }
        if !original.close_requested {
            if original.socket.close().is_err() {return Poll::Ready(Err(Error::ConnectionClosed));}
            original.close_requested = true;
        }
        match Pin::new(&mut original.close_wait).poll(cx) {
            Poll::Pending => Poll::Pending,
            Poll::Ready(Ok(())) if original.socket.ready_state() == web_sys::WebSocket::CLOSED => Poll::Ready(Ok(())),
            Poll::Ready(_) => Poll::Ready(Err(Error::ConnectionClosed)),
        }
    }
}
impl Stream {
    pub(crate) async fn close(&mut self, _: Option<CloseFrame>) -> Result<(), Error> {
        poll_fn(|cx| Pin::new(&mut *self).poll_close(cx)).await
    }
}
