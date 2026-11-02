//! Target-specific execution primitives for the shared client state machines.
//!
//! Native behavior delegates unchanged to Tokio. Browser work runs on its owning
//! worker's local executor: no future or JavaScript handle is asserted Send.
//! This runtime seam alone does not make Client browser-ready; transport,
//! browser-managed sessions and opaque worker key handles require their own
//! admitted adapters before a browser entry point can be exposed.
use std::future::Future;
pub(crate) mod http;
pub(crate) mod socket;

#[cfg(target_arch = "wasm32")]
#[path = "platform/browser_recovery_port.rs"]
pub(crate) mod browser_recovery_port;

#[cfg(not(target_arch = "wasm32"))]
pub(crate) use tokio::time;
#[cfg(target_arch = "wasm32")]
#[path = "platform/browser_time.rs"]
pub(crate) mod time;

#[cfg(not(target_arch = "wasm32"))]
pub(crate) fn spawn(future: impl Future<Output = ()> + Send + 'static) {
    // Dropping JoinHandle detaches, matching the existing monitor ownership:
    // its cancellation token and socket close fence own shutdown.
    drop(tokio::spawn(future));
}

#[cfg(target_arch = "wasm32")]
pub(crate) fn spawn(future: impl Future<Output = ()> + 'static) {
    wasm_bindgen_futures::spawn_local(future);
}

pub(crate) fn unix_ms() -> u64 {
    #[cfg(not(target_arch = "wasm32"))]
    use std::time::{SystemTime, UNIX_EPOCH};
    #[cfg(target_arch = "wasm32")]
    use web_time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

// A browser timer must never wrap a long duration into a shorter delay, or
// expire a positive fractional millisecond early. Also pure-tested natively.
#[cfg(any(target_arch = "wasm32", test))]
fn timer_delay_ms(duration: std::time::Duration) -> u32 {
    duration
        .as_millis()
        .saturating_add(u128::from(duration.subsec_nanos() % 1_000_000 != 0))
        .min(i32::MAX as u128) as u32
}

#[cfg(all(test, not(target_arch = "wasm32")))]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn browser_timer_delay_rounds_up_and_splits_without_integer_wrap() {
        assert_eq!(timer_delay_ms(Duration::ZERO), 0);
        assert_eq!(timer_delay_ms(Duration::from_nanos(1)), 1);
        assert_eq!(timer_delay_ms(Duration::from_micros(1001)), 2);
        assert_eq!(timer_delay_ms(Duration::from_millis(1)), 1);
        assert_eq!(
            timer_delay_ms(Duration::from_millis(i32::MAX as u64)),
            i32::MAX as u32
        );
        assert_eq!(timer_delay_ms(Duration::MAX), i32::MAX as u32);
    }

    #[tokio::test]
    async fn native_deadlines_preserve_tokio_ready_and_timeout_behavior() {
        assert_eq!(time::timeout(Duration::ZERO, async { 7 }).await.unwrap(), 7);
        assert!(
            time::timeout(Duration::from_millis(1), std::future::pending::<()>())
                .await
                .is_err()
        );
    }

    #[tokio::test]
    async fn detached_monitor_task_still_observes_owned_cancellation() {
        let token = tokio_util::sync::CancellationToken::new();
        let stopping = token.clone();
        let (sent, received) = tokio::sync::oneshot::channel();
        spawn(async move {
            stopping.cancelled().await;
            let _ = sent.send(());
        });
        token.cancel();
        time::timeout(Duration::from_secs(1), received)
            .await
            .unwrap()
            .unwrap();
    }
}

// Expensive native work retains Tokio's blocking pool. Browser crypto runs only
// on the admitted DedicatedWorker, never by pretending a local future is Send.
#[cfg(not(target_arch = "wasm32"))]
pub(crate) async fn blocking<T: Send + 'static>(
    work: impl FnOnce() -> T + Send + 'static,
) -> Result<T, ()> {
    tokio::task::spawn_blocking(work).await.map_err(|_| ())
}
#[cfg(target_arch = "wasm32")]
pub(crate) async fn blocking<T>(work: impl FnOnce() -> T) -> Result<T, ()> {
    use wasm_bindgen::JsCast;
    if !js_sys::global().is_instance_of::<web_sys::DedicatedWorkerGlobalScope>() {
        return Err(());
    }
    Ok(work())
}

// HTTP budgets are stricter than generic timeout polling preference: a ready
// response cannot cross its deadline after Worker suspension or paused reading.
#[cfg(any(target_arch = "wasm32", test))]
pub(crate) fn require_http_budget<Tick: Ord>(
    now: Tick,
    deadline: Tick,
    abort: &impl Fn(),
) -> crate::Result<()> {
    if now >= deadline {
        abort();
        return Err(crate::Error::Offline);
    }
    Ok(())
}

#[cfg(any(target_arch = "wasm32", test))]
pub(crate) async fn within_http_budget<T, Tick: Copy + Ord>(
    deadline: Tick,
    now: impl Fn() -> Tick,
    abort: impl Fn(),
    operation: impl std::future::Future<Output = crate::Result<T>>,
) -> crate::Result<T> {
    require_http_budget(now(), deadline, &abort)?;
    let result = operation.await;
    require_http_budget(now(), deadline, &abort)?;
    if result.is_err() {
        abort();
    }
    result
}

#[cfg(test)]
mod http_budget_tests {
    use super::*;
    use crate::{Error, Result};
    use std::{
        cell::Cell,
        future::{Future, poll_fn, ready},
        pin::pin,
        task::{Context, Poll, Waker},
    };

    fn settle<T>(operation: impl Future<Output = Result<T>>) -> Result<T> {
        let mut operation = pin!(operation);
        let mut context = Context::from_waker(Waker::noop());
        match operation.as_mut().poll(&mut context) {
            Poll::Ready(result) => result,
            Poll::Pending => panic!("synthetic ready operation must settle"),
        }
    }

    #[test]
    fn expired_http_budget_aborts_before_polling_ready_operation() {
        for moment in [10, 11] {
            let polled = Cell::new(false);
            let aborts = Cell::new(0);
            let result = settle(within_http_budget(
                10,
                || moment,
                || aborts.set(aborts.get() + 1),
                poll_fn(|_| {
                    polled.set(true);
                    Poll::Ready(Ok(()))
                }),
            ));
            assert!(matches!(result, Err(Error::Offline)));
            assert!(!polled.get());
            assert_eq!(aborts.get(), 1);
        }
    }

    fn reject_ready_result_after_deadline<T>(value: T) {
        let clock = Cell::new(9);
        let aborts = Cell::new(0);
        let mut value = Some(value);
        let result = settle(within_http_budget(
            10,
            || clock.get(),
            || aborts.set(aborts.get() + 1),
            poll_fn(|_| {
                clock.set(10);
                Poll::Ready(Ok(value.take().unwrap()))
            }),
        ));
        assert!(matches!(result, Err(Error::Offline)));
        assert_eq!(aborts.get(), 1);
    }

    #[test]
    fn headers_chunk_and_eof_ready_after_deadline_are_rejected_and_aborted() {
        reject_ready_result_after_deadline("synthetic headers");
        reject_ready_result_after_deadline(Some(vec![1u8, 2]));
        reject_ready_result_after_deadline(None::<Vec<u8>>);
    }

    #[test]
    fn queued_continuation_after_suspension_rechecks_http_deadline() {
        let clock = Cell::new(1);
        let polls = Cell::new(0);
        let aborts = Cell::new(0);
        let operation = within_http_budget(
            10,
            || clock.get(),
            || aborts.set(aborts.get() + 1),
            poll_fn(|_| {
                polls.set(polls.get() + 1);
                if polls.get() == 1 {
                    Poll::Pending
                } else {
                    Poll::Ready(Ok("buffered result"))
                }
            }),
        );
        let mut operation = pin!(operation);
        let mut context = Context::from_waker(Waker::noop());
        assert!(operation.as_mut().poll(&mut context).is_pending());
        clock.set(11);
        assert!(matches!(
            operation.as_mut().poll(&mut context),
            Poll::Ready(Err(Error::Offline))
        ));
        assert_eq!(aborts.get(), 1);
    }

    #[test]
    fn successful_reads_reuse_captured_deadline_and_do_not_renew_it() {
        let clock = Cell::new(0);
        let aborts = Cell::new(0);
        let deadline = 10;
        for moment in [2, 8, 9] {
            clock.set(moment);
            let result = settle(within_http_budget(
                deadline,
                || clock.get(),
                || aborts.set(aborts.get() + 1),
                ready(Ok(Some(vec![1u8]))),
            ));
            assert!(matches!(result, Ok(Some(_))));
        }
        assert_eq!(aborts.get(), 0);
        clock.set(10);
        let result = settle(within_http_budget(
            deadline,
            || clock.get(),
            || aborts.set(aborts.get() + 1),
            ready(Ok(None::<Vec<u8>>)),
        ));
        assert!(matches!(result, Err(Error::Offline)));
        assert_eq!(aborts.get(), 1);
    }

    #[test]
    fn http_operation_error_aborts_without_inventing_error_classification() {
        let aborts = Cell::new(0);
        let result = settle(within_http_budget(
            10,
            || 1,
            || aborts.set(aborts.get() + 1),
            ready(Err::<(), _>(Error::Crypto)),
        ));
        assert!(matches!(result, Err(Error::Crypto)));
        assert_eq!(aborts.get(), 1);
    }
}

#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
#[path="platform/browser_metadata_native.rs"]
pub(crate) mod browser_metadata_native;
