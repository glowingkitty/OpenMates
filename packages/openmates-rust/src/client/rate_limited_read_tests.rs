//! Rate-limited read policy: which responses are resent and how long to wait.

use std::time::Duration;

use reqwest::Method;
use reqwest::header::{HeaderMap, HeaderValue, RETRY_AFTER};

use super::{MAX_RATE_LIMIT_RESENDS, rate_limit_wait, resend_after_rate_limit};

#[test]
fn resends_only_body_less_get_on_429_within_budget() {
    assert!(resend_after_rate_limit(&Method::GET, false, 429, 0));
    assert!(resend_after_rate_limit(
        &Method::GET,
        false,
        429,
        MAX_RATE_LIMIT_RESENDS - 1
    ));
    assert!(!resend_after_rate_limit(
        &Method::GET,
        false,
        429,
        MAX_RATE_LIMIT_RESENDS
    ));
    assert!(!resend_after_rate_limit(&Method::GET, true, 429, 0));
    assert!(!resend_after_rate_limit(&Method::POST, false, 429, 0));
    assert!(!resend_after_rate_limit(&Method::DELETE, false, 429, 0));
    assert!(!resend_after_rate_limit(&Method::GET, false, 503, 0));
    assert!(!resend_after_rate_limit(&Method::GET, false, 200, 0));
}

#[test]
fn waits_for_retry_after_clamped_or_backs_off_without_it() {
    let wait = |value: Option<&'static str>| {
        let mut headers = HeaderMap::new();
        if let Some(value) = value {
            headers.insert(RETRY_AFTER, HeaderValue::from_static(value));
        }
        rate_limit_wait(&headers, 0)
    };
    assert_eq!(wait(Some("4")), Duration::from_secs(4));
    assert_eq!(wait(Some(" 7 ")), Duration::from_secs(7));
    assert_eq!(wait(Some("0")), Duration::from_secs(1));
    assert_eq!(wait(Some("60")), Duration::from_secs(10));
    assert_eq!(
        wait(Some("Wed, 21 Oct 2026 07:28:00 GMT")),
        Duration::from_secs(2)
    );
    assert_eq!(wait(None), Duration::from_secs(2));
    let backoff: Vec<u64> = (0..MAX_RATE_LIMIT_RESENDS)
        .map(|resends| rate_limit_wait(&HeaderMap::new(), resends).as_secs())
        .collect();
    assert_eq!(backoff, vec![2, 4, 8, 10]);
    assert_eq!(
        rate_limit_wait(&HeaderMap::new(), u32::MAX),
        Duration::from_secs(10)
    );
}
