//! Worker-local browser timers. Deadlines use a monotonic browser clock, while
//! expiry validation uses the separate wall clock in the parent module.
use futures_util::future::{Either, select};
use std::future::Future;
pub(crate) use std::time::Duration;
pub(crate) use web_time::Instant;

#[derive(Debug)]
pub(crate) struct Elapsed;

pub(crate) async fn sleep(duration: Duration) {
    // JS timers accept a signed 32-bit delay. Round upward to avoid completing
    // a positive sub-millisecond expiry early, and split longer waits safely.
    let mut remaining = duration;
    while !remaining.is_zero() {
        let millis = super::timer_delay_ms(remaining);
        gloo_timers::future::TimeoutFuture::new(millis).await;
        remaining = remaining.saturating_sub(Duration::from_millis(u64::from(millis)));
    }
}

pub(crate) async fn sleep_until(deadline: Instant) {
    sleep(deadline.saturating_duration_since(Instant::now())).await;
}

pub(crate) async fn timeout<F: Future>(
    duration: Duration,
    future: F,
) -> Result<F::Output, Elapsed> {
    timeout_at(Instant::now() + duration, future).await
}

pub(crate) async fn timeout_at<F: Future>(
    deadline: Instant,
    future: F,
) -> Result<F::Output, Elapsed> {
    // Poll operation first, preserving Tokio's ready-operation preference.
    // Dropping the losing branch cancels its timer; no detached timer task.
    futures_util::pin_mut!(future);
    let timer = sleep_until(deadline);
    futures_util::pin_mut!(timer);
    match select(future, timer).await {
        Either::Left((value, _)) => Ok(value),
        Either::Right(_) => Err(Elapsed),
    }
}

pub(crate) enum MissedTickBehavior {
    Skip,
}
pub(crate) struct Interval {
    next: Instant,
    period: Duration,
}
pub(crate) fn interval_at(start: Instant, period: Duration) -> Interval {
    assert!(!period.is_zero(), "interval period must be nonzero");
    Interval {
        next: start,
        period,
    }
}
impl Interval {
    pub(crate) fn set_missed_tick_behavior(&mut self, _: MissedTickBehavior) {}
    pub(crate) async fn tick(&mut self) -> Instant {
        sleep_until(self.next).await;
        let due = self.next;
        let now = Instant::now();
        // Skip missed heartbeats instead of emitting an unbounded burst after
        // suspension. Keep the original cadence rather than delaying each tick.
        let elapsed = now.saturating_duration_since(due).as_nanos();
        let remainder = elapsed % self.period.as_nanos();
        let remainder = Duration::new(
            (remainder / 1_000_000_000) as u64,
            (remainder % 1_000_000_000) as u32,
        );
        self.next = now + (self.period - remainder);
        due
    }
}
