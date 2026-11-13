//! Opt-in test diagnostic for refused (`Forbidden`) sends in the shared core.
//! With `OPENMATES_TEST_SEND_PHASE_DIAGNOSTIC=1` the last refusal site (a
//! static label, or an HTTP route with every id segment masked) is kept for
//! the send trace to print. Never holds ids, keys or content; off by default.
use std::sync::Mutex;

static LAST: Mutex<Option<String>> = Mutex::new(None);

fn enabled() -> bool {
    std::env::var_os("OPENMATES_TEST_SEND_PHASE_DIAGNOSTIC").as_deref()
        == Some(std::ffi::OsStr::new("1"))
}

/// Remember a static refusal site label.
pub(in crate::client) fn note(label: &'static str) {
    if enabled()
        && let Ok(mut last) = LAST.lock()
    {
        *last = Some(label.into());
    }
}

/// Remember a refused HTTP route; segments that are not plain route words
/// (ids, queries) are replaced by `_`.
pub(in crate::client) fn note_http(status: u16, path: &str) {
    if !enabled() {
        return;
    }
    let route: Vec<&str> = path
        .split('?')
        .next()
        .unwrap_or("")
        .split('/')
        .map(|part| {
            if part.len() <= 24 && part.bytes().all(|b| b.is_ascii_lowercase() || b == b'-') {
                part
            } else {
                "_"
            }
        })
        .collect();
    if let Ok(mut last) = LAST.lock() {
        *last = Some(format!("http_{status}:{}", route.join("/")));
    }
}

/// A fixed server identifier, or `_` for anything else (ids, free text).
fn fixed_code(code: Option<&str>) -> &str {
    code.filter(|c| !c.is_empty() && c.len() <= 64 && c.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_'))
        .unwrap_or("_")
}

/// Remember a rejected WebSocket `error` frame by its server code and reason
/// (both fixed identifiers; anything else is masked as `_`).
pub(in crate::client) fn note_ws_error(code: Option<&str>, reason: Option<&str>) {
    if !enabled() {
        return;
    }
    let (code, reason) = (fixed_code(code), fixed_code(reason));
    if let Ok(mut last) = LAST.lock() {
        *last = Some(format!("ws_error:{code}/{reason}"));
    }
}

/// The last remembered site, cleared on read.
pub(in crate::client) fn take() -> String {
    LAST.lock()
        .ok()
        .and_then(|mut last| last.take())
        .unwrap_or_else(|| "none".into())
}

/// `Error::Protocol` that also notes its source location (file:line, a static
/// label) for the opt-in send diagnostic.
macro_rules! protocol_at {
    () => {{
        $crate::client::send::refusal_trace::note(concat!(file!(), ":", line!()));
        $crate::Error::Protocol
    }};
}
pub(in crate::client) use protocol_at;

/// Remember the source location of a JSON decode failure or missing field
/// into `Error::Protocol` (file:line only, never the input).
pub(crate) fn note_caller(location: &'static std::panic::Location<'static>) {
    if enabled()
        && let Ok(mut last) = LAST.lock()
    {
        *last = Some(format!("at:{}:{}", location.file(), location.line()));
    }
}

/// Remember the failing turn step unless a deeper site was already noted. A
/// rejected WebSocket frame names no step, so the first step is added to it.
pub(in crate::client) fn note_step(label: &'static str) {
    if enabled()
        && let Ok(mut last) = LAST.lock()
    {
        match last.as_mut() {
            None => *last = Some(format!("step:{label}")),
            Some(site) if site.starts_with("ws_error:") && !site.contains('@') => {
                site.push('@');
                site.push_str(label);
            }
            Some(_) => {}
        }
    }
}
