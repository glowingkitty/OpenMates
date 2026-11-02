//! Local UTC offset for zone-less due-soon times (architecture.sync@2).
//!
//! The web app reads zone-less ISO times as local time; the overview order
//! must classify them identically. The OS offset is captured once at process
//! start, before any thread exists (the `time` crate refuses to read it
//! afterwards because other threads could race `setenv`). It is the offset
//! in force at start-up; an undeterminable offset falls back to UTC.
use std::sync::OnceLock;

static OFFSET_MINUTES: OnceLock<i32> = OnceLock::new();

fn minutes_of(offset: Result<time::UtcOffset, time::error::IndeterminateOffset>) -> i32 {
    offset.map_or(0, |offset| offset.whole_minutes().into())
}

/// Capture the local offset. Call first in `main`, before building a runtime.
pub fn capture() {
    let minutes = minutes_of(time::UtcOffset::current_local_offset());
    let _ = OFFSET_MINUTES.set(minutes);
    openmates_sdk::client::overview::set_local_utc_offset_minutes(minutes);
}

/// Local UTC offset in minutes (east positive); 0 when never captured or unknown.
pub fn utc_offset_minutes() -> i32 {
    OFFSET_MINUTES.get().copied().unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    // contract-test: supporting surface=cli assertions=sync.overview.priority-order
    #[test]
    fn offset_converts_to_minutes_and_unknown_falls_back_to_utc() {
        let berlin = time::UtcOffset::from_hms(2, 0, 0).unwrap();
        let india = time::UtcOffset::from_hms(5, 30, 0).unwrap();
        let newfoundland = time::UtcOffset::from_hms(-3, -30, 0).unwrap();
        assert_eq!(minutes_of(Ok(berlin)), 120);
        assert_eq!(minutes_of(Ok(india)), 330);
        assert_eq!(minutes_of(Ok(newfoundland)), -210);
        assert_eq!(minutes_of(Err(time::error::IndeterminateOffset)), 0);
    }

    // contract-test: supporting surface=cli assertions=sync.overview.priority-order
    #[test]
    fn zone_less_due_time_follows_the_captured_offset() {
        use openmates_sdk::client::overview::parse_time;
        let value = serde_json::json!("2027-01-15T09:00:00");
        let utc = parse_time(Some(&value), 0).unwrap();
        // The same wall time one hour east of UTC happened one hour earlier.
        assert_eq!(parse_time(Some(&value), 60), Some(utc - 3_600_000));
        assert_eq!(parse_time(Some(&value), -330), Some(utc + 330 * 60_000));
    }
}
