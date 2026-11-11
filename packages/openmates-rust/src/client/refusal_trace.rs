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

/// The last remembered site, cleared on read.
pub(in crate::client) fn take() -> String {
    LAST.lock()
        .ok()
        .and_then(|mut last| last.take())
        .unwrap_or_else(|| "none".into())
}
