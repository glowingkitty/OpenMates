//! PRIVATE, UNCOMPILED thin Linux clock adapter. No subprocess or new dependency.
//! Proposed import after the SDK policy is reviewed and exported:
use openmates_sdk::client::CacheClockEvidence;

/// Unknown OS/boot/clock evidence skips warm admission and keeps full sync.
/// This identifier is local-only protected-cache metadata. Never log, publish,
/// send to the server, or expose it through user-visible output/telemetry.
pub fn cache_clock_evidence() -> Option<CacheClockEvidence> {
    #[cfg(target_os = "linux")]
    {
        let before = boot_id()?;
        let uptime_before = uptime_ms()?;
        let wall = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .ok()?
            .as_millis();
        let uptime_after = uptime_ms()?;
        let after = boot_id()?;
        // The narrow sample brackets wall time with the suspend-inclusive
        // boot clock. Reboot, rollback or a heavily delayed read fails closed.
        if before != after || uptime_after.checked_sub(uptime_before)? > 250 {
            return None;
        }
        CacheClockEvidence::from_platform(
            format!("linux-boottime-v1:{before}"),
            uptime_before,
            u64::try_from(wall).ok()?,
        )
    }
    #[cfg(not(target_os = "linux"))]
    {
        // Mac needs an existing safe boot-session identity + suspend-inclusive
        // monotonic adapter. The crates forbid unsafe code; adding a vetted
        // safe platform dependency is a separate review. Do not shell out.
        None
    }
}

#[cfg(target_os = "linux")]
fn boot_id() -> Option<String> {
    let value = std::fs::read_to_string("/proc/sys/kernel/random/boot_id").ok()?;
    let value = value.trim();
    if value.len() != 36
        || !value.bytes().enumerate().all(|(index, byte)| {
            if matches!(index, 8 | 13 | 18 | 23) {
                byte == b'-'
            } else {
                byte.is_ascii_hexdigit()
            }
        })
    {
        return None;
    }
    Some(value.to_ascii_lowercase())
}

#[cfg(target_os = "linux")]
fn uptime_ms() -> Option<u64> {
    parse_uptime_ms(&std::fs::read_to_string("/proc/uptime").ok()?)
}

#[cfg(any(target_os = "linux", test))]
fn parse_uptime_ms(value: &str) -> Option<u64> {
    // Integer parsing avoids precision loss/NaN/infinity and rejects malformed
    // clocks. Linux exposes two decimals today; accept 1..3 without rounding up.
    let first = value.split_ascii_whitespace().next()?;
    let (seconds, fractional) = first.split_once('.')?;
    if seconds.is_empty()
        || !seconds.bytes().all(|v| v.is_ascii_digit())
        || fractional.is_empty()
        || fractional.len() > 3
        || !fractional.bytes().all(|v| v.is_ascii_digit())
    {
        return None;
    }
    let millis = fractional
        .parse::<u64>()
        .ok()?
        .checked_mul(10u64.checked_pow(3 - fractional.len() as u32)?)?;
    seconds
        .parse::<u64>()
        .ok()?
        .checked_mul(1000)?
        .checked_add(millis)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn uptime_is_checked_integer_elapsed_time() {
        assert_eq!(parse_uptime_ms("123.45 999.00\n"), Some(123_450));
        assert_eq!(parse_uptime_ms("123.4 999.00"), Some(123_400));
        assert_eq!(parse_uptime_ms("123.456 999.00"), Some(123_456));
        for value in [
            "-1.0",
            "NaN",
            "inf",
            "1.",
            "1.1234",
            "1e3.0",
            "18446744073709551615.99",
        ] {
            assert_eq!(parse_uptime_ms(value), None);
        }
    }
}
