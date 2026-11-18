//! Bounded wait-and-resend policy for rate-limited or briefly unavailable reads
//! (shared client core, used by `transport.rs` for every shell).
//!
//! The API limits per client address, so one device replaying a finished turn
//! (many embed reads in a row) can meet HTTP 429 while other clients share the
//! same address; during a backend restart the proxy answers HTTP 503 for a few
//! seconds. A body-less GET has no server effect, so it waits for the
//! advertised `Retry-After` (or a growing backoff when the server names none;
//! the API's per-minute limiter sends no header) and is sent again a few times
//! before the caller sees `Error::Offline`. Writes are never resent here: their outcome after a
//! 429 belongs to the caller's idempotency and recovery rules.

use std::time::Duration;

use reqwest::Method;
use reqwest::header::{HeaderMap, RETRY_AFTER};

/// Resends after the first 429 or 503 of one read; the read then fails as before.
pub(super) const MAX_RATE_LIMIT_RESENDS: u32 = 4;
/// First backoff when the server names no usable `Retry-After`; it doubles
/// per resend (2, 4, 8, then the 10 s bound: about 24 s for one read).
const FIRST_BACKOFF: Duration = Duration::from_secs(2);
/// Upper bound of one wait, so a turn deadline is never consumed by one read.
const MAX_WAIT: Duration = Duration::from_secs(10);

/// Whether a response to this request may be waited out and the request sent
/// again: only body-less GETs that got 429 (rate limited) or 503 (briefly
/// unavailable), within the resend budget.
/// `keep_first` is true when the request has a body or its caller reads the
/// HTTP status itself; such responses are never resent.
pub(super) fn resend_after_rate_limit(
    method: &Method,
    keep_first: bool,
    status: u16,
    resends: u32,
) -> bool {
    *method == Method::GET
        && !keep_first
        && matches!(status, 429 | 503)
        && resends < MAX_RATE_LIMIT_RESENDS
}

/// The wait before resend number `resends + 1`: `Retry-After` in whole
/// seconds clamped to 1..=10 s; an absent, HTTP-date or malformed value uses
/// the doubling backoff, also bounded by 10 s.
pub(super) fn rate_limit_wait(headers: &HeaderMap, resends: u32) -> Duration {
    headers
        .get(RETRY_AFTER)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.trim().parse::<u64>().ok())
        .map(|seconds| Duration::from_secs(seconds).clamp(Duration::from_secs(1), MAX_WAIT))
        .unwrap_or_else(|| (FIRST_BACKOFF * 2u32.saturating_pow(resends.min(8))).min(MAX_WAIT))
}

#[cfg(test)]
#[path = "rate_limited_read_tests.rs"]
mod rate_limited_read_tests;
